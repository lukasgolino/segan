"""What songs and SFX share: file naming, metadata (description, tags, status, style_version, lint),
`extends` templates, and loading either kind of asset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from segan.findings import Finding, SeganError
from segan.kit import NAME_RE, Kit
from segan.patch import Report, line_of
from segan.yamlio import LineMap, YamlError, load_yaml

if TYPE_CHECKING:
    from segan.project import Project

SONG_SUFFIX = ".song.yaml"
SFX_SUFFIX = ".sfx.yaml"
ASSET_SUFFIXES = (SONG_SUFFIX, SFX_SUFFIX)
STATUSES = ("draft", "approved")
META_FIELDS = ("name", "description", "tags", "status", "style_version", "lint", "template", "extends", "remove")
OWN_FIELDS = ("name", "description", "tags", "status", "style_version", "template", "extends", "remove")
MERGE_BY_KEY = ("tracks", "patterns", "sections", "variants", "variant_axes", "markers", "phases", "instruments")


def asset_kind(path: Path) -> str | None:
    if path.name.endswith(SONG_SUFFIX):
        return "song"
    if path.name.endswith(SFX_SUFFIX):
        return "sfx"
    return None


def asset_name_from_path(path: Path) -> str | None:
    for suffix in ASSET_SUFFIXES:
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return None


@dataclass
class Meta:
    name: str
    kind: str
    path: Path | None
    description: str | None = None
    tags: tuple[str, ...] = ()
    status: str = "draft"
    style_version: int = 1
    lint_disable: frozenset[str] = frozenset()
    template: bool = False
    extends: str | None = None
    sources: list[Path] = field(default_factory=list)  # this file + templates it extends (for caching)


def parse_meta(data: dict[str, Any], path: Path | None, kind: str, report: Report, rule: str) -> Meta:
    line = data.line if isinstance(data, LineMap) else None
    expected = asset_name_from_path(path) if path is not None else None
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        report.error("E001", "name must be lowercase letters, digits, '_' or '-'", line_of(data, "name", line), "name")
        name = expected or "unnamed"
    elif expected is not None and name != expected:
        report.error("E001", f"name {name!r} must match the file name ({expected})", line_of(data, "name", line), "name")
    meta = Meta(name=name, kind=kind, path=path)
    description = data.get("description")
    if description is not None:
        if isinstance(description, str):
            meta.description = description
        else:
            report.error("E001", "description must be text", line_of(data, "description", line), "description")
    tags = data.get("tags", [])
    if isinstance(tags, list) and all(isinstance(t, str) for t in tags):
        meta.tags = tuple(tags)
    else:
        report.error("E001", "tags must be a list of words, e.g. [pickup, ui]", line_of(data, "tags", line), "tags")
    status = data.get("status", "draft")
    if status in STATUSES:
        meta.status = status
    else:
        report.error("E001", f"status must be one of {', '.join(STATUSES)}", line_of(data, "status", line), "status")
    style = data.get("style_version", 1)
    if isinstance(style, int) and not isinstance(style, bool) and style >= 1:
        meta.style_version = style
    else:
        report.error("E001", "style_version must be a positive integer", line_of(data, "style_version", line), "style_version")
    template = data.get("template", False)
    if isinstance(template, bool):
        meta.template = template
    else:
        report.error("E001", "template must be true or false", line_of(data, "template", line), "template")
    lint = data.get("lint")
    if lint is not None:
        disable = lint.get("disable") if isinstance(lint, dict) and set(lint) <= {"disable"} else None
        if isinstance(disable, list) and all(isinstance(r, str) and re.fullmatch(r"W\d{3}", r) for r in disable):
            meta.lint_disable = frozenset(disable)
        else:
            report.error("E001", 'lint must be { disable: [W..., ...] } (only warnings can be disabled)', line_of(data, "lint", line), "lint")
    return meta


# --- extends ------------------------------------------------------------------------------------


def plain(value: Any) -> Any:
    """A copy without source line numbers (a template's lines belong to another file)."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def merge_template(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """The child's fields over the template's. Own-identity fields aren't inherited; mappings like patterns,
    tracks and variants merge by key; `layers` merge by `id` (a child layer with a template layer's id changes
    just the fields it gives; layers without a matching id are added) and `remove` drops template layers by id."""
    merged = LineMap()
    if isinstance(child, LineMap):
        merged.line = child.line
    for key, value in base.items():
        if key not in OWN_FIELDS:
            merged[key] = plain(value)
    for key, value in child.items():
        if key in MERGE_BY_KEY and isinstance(value, dict) and isinstance(merged.get(key), dict):
            combined = LineMap()
            combined.update(merged[key])
            combined.update(value)
            if isinstance(value, LineMap):
                combined.line = value.line
                combined.key_lines = {**getattr(merged[key], "key_lines", {}), **value.key_lines}
            merged[key] = combined
        elif key == "layers" and isinstance(value, list) and isinstance(merged.get(key), list):
            layers = list(merged[key])
            ids = {layer.get("id"): i for i, layer in enumerate(layers) if isinstance(layer, dict) and layer.get("id")}
            for layer in value:
                lid = layer.get("id") if isinstance(layer, dict) else None
                if lid in ids:  # same id: the child's fields over the template layer's
                    combined_layer = LineMap()
                    combined_layer.update(layers[ids[lid]])
                    combined_layer.update(layer)
                    if isinstance(layer, LineMap):
                        combined_layer.line = layer.line
                    layers[ids[lid]] = combined_layer
                else:
                    layers.append(layer)
            merged[key] = layers
        else:
            merged[key] = value
        if isinstance(child, LineMap) and key in child.key_lines and isinstance(merged, LineMap):
            merged.key_lines[key] = child.key_lines[key]
    removed = child.get("remove")
    if isinstance(removed, list) and isinstance(merged.get("layers"), list):
        merged["layers"] = [layer for layer in merged["layers"] if not (isinstance(layer, dict) and layer.get("id") in removed)]
    return merged


def resolve_extends(data: dict[str, Any], path: Path | None, folder: Path | None, suffix: str, report: Report, seen: tuple[str, ...] = ()) -> tuple[dict[str, Any], list[Path]]:
    """Follow `extends:` chains (templates are files in the same folder with `template: true`)."""
    parent = data.get("extends")
    if parent is None:
        return data, []
    line = line_of(data, "extends", data.line if isinstance(data, LineMap) else None)
    if not isinstance(parent, str) or not NAME_RE.match(parent):
        report.error("E001", "extends must be the name of a template asset", line, "extends")
        return data, []
    if parent in seen:
        report.error("E001", f"extends cycle: {' -> '.join((*seen, parent))}", line, "extends")
        return data, []
    if folder is None:
        report.error("E001", "extends needs a project (templates are looked up by name)", line, "extends")
        return data, []
    base_path = folder / f"{parent}{suffix}"
    if not base_path.is_file():
        report.error("E001", f"extends: no template {parent!r} ({base_path.name} doesn't exist)", line, "extends")
        return data, []
    try:
        base = load_yaml(base_path)
    except YamlError as exc:
        report.error("E001", f"extends: template {parent!r} has a YAML error: {exc.message}", line, "extends")
        return data, []
    if not isinstance(base, dict) or base.get("template") is not True:
        report.error("E001", f"extends: {base_path.name} isn't a template (set template: true in it)", line, "extends")
        return data, []
    resolved_base, chain = resolve_extends(base, base_path, folder, suffix, report, (*seen, parent))
    return merge_template(resolved_base, data), [base_path, *chain]


# --- loading ------------------------------------------------------------------------------------


def resolve_kit(data: dict[str, Any], project: Project, report: Report, rule: str) -> Kit | None:
    """The kit an asset plays: `kit: name` (a kit file), the project default, or inline `instruments:`
    (open mode only, E009 in strict)."""
    from segan.kit import parse_groups, parse_instruments

    line = data.line if isinstance(data, LineMap) else None
    inline = data.get("instruments")
    if inline is not None:
        if project.config.mode == "strict" and project.config_path is not None:
            report.error("E009", "inline instruments aren't allowed in a strict-mode project: add them to a kit file and name it with `kit:`", line_of(data, "instruments", line), "instruments")
            return None
        instruments = parse_instruments(inline, report, rule, "instruments", line_of(data, "instruments", line))
        if data.get("kit") is not None and isinstance(data.get("kit"), str):
            try:
                base = project.load_kit(data["kit"])
            except SeganError as exc:
                report.findings.extend(exc.findings)
                return None
            instruments = {**base.instruments, **instruments}
        groups = parse_groups(data.get("groups"), instruments, report, rule, "groups", line_of(data, "groups", line))
        return Kit(None, instruments, groups)
    name = data.get("kit", project.config.default_kit)
    if name is None:
        return None
    if not isinstance(name, str):
        report.error("E005", "kit must be the name of a kit file in kits/", line_of(data, "kit", line), "kit")
        return None
    try:
        return project.load_kit(name)
    except SeganError as exc:
        report.findings.extend(Finding(f.rule, f.message, report.path, line_of(data, "kit", line), "kit") for f in exc.findings)
        return None


def load_source(path: Path) -> dict[str, Any]:
    try:
        data = load_yaml(path)
    except YamlError as exc:
        raise SeganError([Finding("E001", exc.message, path, exc.line)]) from None
    if not isinstance(data, dict):
        raise SeganError([Finding("E001", "an asset file must be a YAML mapping", path)])
    return data


def load_asset(path: Path, project: Project) -> tuple[Any, list[Finding]]:
    """Parse a song or SFX file: (asset or None, findings)."""
    kind = asset_kind(path)
    if kind == "sfx":
        from segan.sfx import load_sfx

        return load_sfx(path, project)
    if kind == "song":
        from segan.song import load_song

        return load_song(path, project)
    return None, [Finding("E000", f"not a SEGAN asset file (expected {' or '.join(ASSET_SUFFIXES)})", path)]


def load_asset_or_raise(path: Path, project: Project) -> Any:
    asset, findings = load_asset(path, project)
    if asset is None:
        raise SeganError(findings)
    return asset
