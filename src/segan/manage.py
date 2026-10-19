"""Long-term asset management: catalogue (`segan status`), status marks, style versions, mix adjustments.

Adapted from PAGAN's manage.py. Edits to source files are made textually (one line at a time) so comments and
formatting survive; segan.toml edits go through settings.py's comment-preserving TOML edits.
"""

from __future__ import annotations

import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from segan.asset import ASSET_SUFFIXES, STATUSES, asset_kind, asset_name_from_path
from segan.findings import Finding, SeganError
from segan.lint import lint_paths
from segan.project import CONFIG_NAME, Project, parse_config
from segan.settings import current_value, set_in_toml
from segan.yamlio import LineMap, YamlError, load_yaml, parse_yaml

# --- catalogue --------------------------------------------------------------------------------


@dataclass
class AssetStatus:
    name: str
    kind: str
    path: Path
    description: str | None
    status: str
    style_version: int
    category: str
    seconds: float | None
    outputs: int
    errors: int
    warnings: int
    tags: tuple[str, ...]
    template: bool = False

    def needs(self, current_style: int) -> list[str]:
        todo = []
        if self.errors:
            todo.append("fix errors")
        if self.style_version < current_style:
            todo.append(f"review for style v{current_style}")
        if self.status != "approved" and not self.template:
            todo.append("a human listen + approve")
        if not self.description or self.description.startswith("TODO"):
            todo.append("describe")
        return todo


def catalogue(project: Project, render: bool = True) -> list[AssetStatus]:
    """Every song and SFX with its status; `render=False` skips the audio (no lengths, no audio warnings)."""
    from segan.render import render_asset

    result = lint_paths(project, render=render)
    by_path = {a.path.resolve(): a for a in result.assets if a.path is not None}
    out: list[AssetStatus] = []
    for path in result.files:
        kind = asset_kind(path)
        if kind is None:
            continue
        asset = by_path.get(path.resolve())
        findings = [f for f in result.findings if f.path is not None and f.path.resolve() == path.resolve()]
        errors = sum(f.severity == "error" for f in findings)
        warnings = sum(f.severity == "warning" for f in findings)
        if asset is not None:
            seconds, outputs = None, 0
            if render and not asset.meta.template:
                rendered = render_asset(asset, project)
                seconds = round(rendered.main.seconds, 3)
                outputs = len([o for o in rendered.outputs if not o.id.startswith(("stem:", "mix:"))])
            meta = asset.meta
            out.append(AssetStatus(asset.name, kind, path, meta.description, meta.status, meta.style_version, asset.category,
                                   seconds, outputs, errors, warnings, meta.tags, meta.template))  # fmt: skip
        else:
            raw = _raw_fields(path)
            out.append(AssetStatus(asset_name_from_path(path) or path.stem, kind, path,
                                   raw.get("description") if isinstance(raw.get("description"), str) else None,
                                   str(raw.get("status", "draft")), _int(raw.get("style_version"), 1), str(raw.get("category", "?")),
                                   None, 0, errors, warnings, ()))  # fmt: skip
    return sorted(out, key=lambda e: (e.kind, e.name))


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _raw_fields(path: Path) -> dict[str, Any]:
    try:
        data = load_yaml(path)
    except Exception:  # noqa: BLE001 - the catalogue must list broken files too
        return {}
    return data if isinstance(data, dict) else {}


# --- status and style marks -------------------------------------------------------------------


def _apply_edits(text: str, edits: list[tuple[int, int, int, str]]) -> str:
    lines = text.split("\n")
    for line, start_col, end_col, replacement in sorted(edits, key=lambda e: (e[0], -e[1])):
        current = lines[line - 1]
        lines[line - 1] = current[:start_col] + replacement + current[end_col:]
    return "\n".join(lines)


def set_top_level_field(path: Path, field: str, value: str) -> None:
    """Set `field: value` at the top level of a YAML source file, keeping everything else as written. The edited
    text is parsed again before it's written; if that fails, nothing changes and an error explains why."""
    text = path.read_text(encoding="utf-8")
    data = load_yaml(path)
    if not isinstance(data, LineMap):
        raise SeganError([Finding("E001", "not a mapping; can't edit", path)])
    if text.lstrip().startswith("{"):
        raise SeganError([Finding("E001", f"can't edit {field!r} in a flow-style ({{...}}) file; write it as block YAML", path)])
    if field in data:
        span = data.value_spans.get(field)
        if span is None:
            raise SeganError([Finding("E001", f"can't edit {field!r}: write it as a one-line value", path, data.line_of(field))])
        line, start_col, end_col = span
        current = text.split("\n")[line - 1]
        needs_space = start_col == end_col and not current[:start_col].endswith(" ")
        text = _apply_edits(text, [(line, start_col, end_col, (" " if needs_space else "") + value)])
    else:
        lines = text.split("\n")
        after = data.line_of("name") if "name" in data else 0
        lines.insert(after or 0, f"{field}: {value}")
        text = "\n".join(lines)
    try:
        check = parse_yaml(text)
    except YamlError as exc:
        raise SeganError([Finding("E001", f"editing {field!r} would break the file ({exc.message}); nothing changed", path)]) from None
    if not isinstance(check, dict) or str(check.get(field)) != value:
        raise SeganError([Finding("E001", f"couldn't set {field!r} safely; nothing changed", path)])
    path.write_text(text, encoding="utf-8")


def mark(paths: list[Path], status: str | None, style_version: int | None) -> None:
    if status is not None and status not in STATUSES:
        raise SeganError([Finding("E000", f"status must be one of {', '.join(STATUSES)}")])
    for path in paths:
        if not path.name.endswith(ASSET_SUFFIXES):
            raise SeganError([Finding("E000", "not a song or SFX file", path)])
        if status is not None:
            set_top_level_field(path, "status", status)
        if style_version is not None:
            set_top_level_field(path, "style_version", str(style_version))


def bump_style(project: Project, note: str, today: dt.date | None = None) -> int:
    """Increment segan.toml's style_version and log the change in SOUND.md's changelog."""
    if project.config_path is None:
        raise SeganError([Finding("E000", f"no {CONFIG_NAME} found")])
    new_version = project.config.style_version + 1
    text = project.config_path.read_text(encoding="utf-8")
    pattern = re.compile(r"^style_version\s*=\s*\d+[^\n]*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(f"style_version = {new_version}", text, count=1)
    else:
        table = re.search(r"^\[", text, re.MULTILINE)
        at = table.start() if table else len(text)
        text = text[:at] + f"style_version = {new_version}\n\n" + text[at:]
    project.config_path.write_text(text, encoding="utf-8")
    sound = project.root / "SOUND.md"
    entry = f"- v{new_version} ({(today or dt.date.today()).isoformat()}): {note.strip()}"
    existing = sound.read_text(encoding="utf-8") if sound.exists() else "# Sound bible\n"
    if "## Changelog" in existing:
        head, tail = existing.split("## Changelog", 1)
        tail_lines = tail.split("\n")
        insert = 1
        while insert < len(tail_lines) and not tail_lines[insert].startswith("- v") and not tail_lines[insert].startswith("## "):
            insert += 1
        tail_lines.insert(insert, entry)
        existing = head + "## Changelog" + "\n".join(tail_lines)
    else:
        existing = existing.rstrip("\n") + f"\n\n## Changelog\n\n{entry}\n"
    sound.write_text(existing, encoding="utf-8")
    return new_version


def outdated(project: Project) -> list[Path]:
    """Asset files made under an older style version."""
    return [e.path for e in catalogue(project, render=False) if e.style_version < project.config.style_version]


# --- mix adjust ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class MixAdjustment:
    brightness: float = 0.0  # dB added to [mix] brightness
    warmth: float = 0.0  # dB added to [mix] warmth
    room: float = 0.0  # added to [mix] room
    crush: int | None = None  # [mix] crush_bits (0 = off)
    loudness: float = 0.0  # LU added to every [loudness] target

    def is_identity(self) -> bool:
        return self == MixAdjustment()


def _clamp(value: float, lo: float, hi: float) -> float:
    return round(min(hi, max(lo, value)), 4)


def adjust_mix(project: Project, adj: MixAdjustment, dry_run: bool = False) -> dict[str, tuple[Any, Any]]:
    """Relative changes to the shared mix, written to segan.toml (validated first; comments kept).
    Returns {setting: (old, new)}. Every song and SFX re-renders with them on the next build/preview."""
    if project.config_path is None:
        raise SeganError([Finding("E000", f"no {CONFIG_NAME} found; run `segan init` first")])
    config = project.config
    changes: dict[str, tuple[Any, Any]] = {}

    def change(key: str, new: Any) -> None:
        old = current_value(config, key)
        if new != old:
            changes[key] = (old, new)

    if adj.brightness:
        change("mix.brightness", _clamp(config.mix.brightness + adj.brightness, -12, 12))
    if adj.warmth:
        change("mix.warmth", _clamp(config.mix.warmth + adj.warmth, -12, 12))
    if adj.room:
        change("mix.room", _clamp(config.mix.room + adj.room, 0, 1))
    if adj.crush is not None:
        if adj.crush != 0 and not 2 <= adj.crush <= 16:
            raise SeganError([Finding("E000", "--crush is the bit depth: 2-16, or 0 to turn crushing off")])
        change("mix.crush_bits", adj.crush)
    if adj.loudness:
        for category, target in sorted(config.loudness.items()):
            change(f"loudness.{category}", _clamp(target + adj.loudness, -40, -5))
    text = project.config_path.read_text(encoding="utf-8")
    for key, (_, new) in changes.items():
        text = set_in_toml(text, key, new)
    parse_config(tomllib.loads(text), project.config_path)  # raises (and nothing is written) if invalid
    if not dry_run and changes:
        project.config_path.write_text(text, encoding="utf-8")
    return changes
