"""`segan build`: lint, then write final assets (WAVs, manifest.json, Godot resources) to the output dir.

Adapted from PAGAN's build.py. Output is deterministic: same sources -> byte-identical files, so projects can
commit it. Only changed files are rewritten (engines don't re-import everything); files the previous build
produced but this one doesn't (recorded in the previous manifest) are removed, with their `.import` sidecars.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from segan import __version__
from segan.exporters.godot import edit_import, find_godot_project, import_params, randomizer_tres, res_path, synchronized_tres
from segan.findings import Finding
from segan.lint import LintResult, lint_paths
from segan.project import Project
from segan.render import Output, render_asset

MANIFEST = "manifest.json"


@dataclass
class BuildResult:
    lint: LintResult
    written: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    imports: list[Path] = field(default_factory=list)
    errors: list[Finding] = field(default_factory=list)
    manifest: Path | None = None
    godot_root: Path | None = None
    assets: int = 0


def _write(path: Path, data: bytes, result: BuildResult) -> None:
    if path.is_file() and path.read_bytes() == data:
        result.unchanged.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    result.written.append(path)


def _ref(path: Path, out: Path, godot_root: Path | None) -> str:
    """How the manifest refers to a file: res:// inside Godot, else relative to the output dir."""
    if godot_root is not None:
        return res_path(path, godot_root)
    return path.resolve().relative_to(out.resolve()).as_posix()


def _loop(output: Output) -> dict[str, int] | None:
    return {"start": output.loop[0], "end": output.loop[1]} if output.loop else None


def build(project: Project) -> BuildResult:
    """Build the whole project (a partial build would leave an incomplete manifest)."""
    lint = lint_paths(project)
    result = BuildResult(lint=lint)
    if lint.errors:
        result.errors = lint.errors
        return result
    out = project.output_dir
    exporters = set(project.config.export)
    godot_root: Path | None = None
    if "godot" in exporters:
        godot_root = find_godot_project(out)
        if godot_root is None:
            result.errors.append(Finding("E000", f'export includes "godot" but output_dir ({out}) isn\'t inside a Godot project (no project.godot in it '
                                         "or any parent). Point output_dir into your Godot project, e.g. ../game/assets/generated/audio", project.config_path))  # fmt: skip
            return result
        result.godot_root = godot_root
    out.mkdir(parents=True, exist_ok=True)
    previous = _previous_outputs(out)
    produced: set[Path] = set()
    compress = project.config.godot.compress

    def emit(output: Output, folder: str) -> dict[str, Any]:
        path = out / folder / f"{output.stem}.wav"
        _write(path, output.wav(), result)
        produced.add(path.resolve())
        if godot_root is not None:
            sidecar = edit_import(path, import_params(output.loop, compress))
            if sidecar is not None:
                result.imports.append(sidecar)
        return {"file": _ref(path, out, godot_root), "seconds": round(output.seconds, 6), "samples": output.frames,
                "channels": output.channels, "loop": _loop(output)}  # fmt: skip

    def emit_tres(path: Path, text: str) -> str:
        _write(path, text.encode("utf-8"), result)
        produced.add(path.resolve())
        assert godot_root is not None
        return res_path(path, godot_root)

    entries: dict[str, Any] = {}
    for asset in sorted((a for a in lint.assets if not a.meta.template), key=lambda a: a.name):
        render = render_asset(asset, project)
        main = render.main
        meta = asset.meta
        entry: dict[str, Any] = {
            "kind": asset.kind,
            "description": meta.description,
            "tags": list(meta.tags),
            "status": meta.status,
            "style_version": meta.style_version,
            "category": asset.category,
            "sample_rate": main.rate,
        }
        if asset.kind == "sfx":
            if asset.layers:
                entry.update(emit(main, "sfx"))
                entry.update(_levels(main))
            variations = [o for o in render.outputs if o.id.startswith("variation:")]
            if variations:
                entry["variations"] = []
                for output in variations:
                    info = emit(output, "sfx")
                    info["pitch_offset_semitones"] = round(float(output.info.get("pitch_offset", 0.0)), 4)
                    entry["variations"].append(info)
                if godot_root is not None:
                    streams = [v["file"] for v in entry["variations"]]
                    entry["godot_randomizer"] = emit_tres(out / "sfx" / f"{asset.name}.tres", randomizer_tres(streams))
            phases = [o for o in render.outputs if o.id.startswith("phase:")]
            if phases:
                entry["phases"] = {o.id.split(":", 1)[1]: emit(o, "sfx") for o in phases}
        else:
            entry.update(emit(main, "music"))
            entry.update(_levels(main))
            entry.update(_song_timing(asset, main))
            variants = [o for o in render.outputs if o.id.startswith("variant:")]
            if variants:
                entry["variants"] = {}
                for output in variants:
                    variant = asset.all_variants()[output.id.split(":", 1)[1]]
                    entry["variants"][variant.name] = {**emit(output, "music"), **_levels(output), **_song_timing(asset, output, variant)}
            stems = [o for o in render.outputs if o.id.startswith("stem:")]
            if stems:
                entry["stems"] = {o.id.split(":", 1)[1]: emit(o, "stems") for o in stems}
                if godot_root is not None:
                    entry["godot_stems"] = emit_tres(out / "stems" / f"{asset.name}.tres", synchronized_tres([s["file"] for s in entry["stems"].values()]))
        entries[asset.name] = entry
        result.assets += 1

    manifest = {
        "generator": f"segan {__version__}",
        "note": "Generated by `segan build`. Do not edit: change the sources and rebuild. Loop ends and section ends are exclusive sample indices.",
        "assets": entries,
        "files": sorted(_ref(p, out, None) for p in produced),
    }
    manifest_path = out / MANIFEST
    _write(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"), result)
    result.manifest = manifest_path
    for stale in sorted(previous - produced):
        if stale.is_file():
            stale.unlink()
            result.removed.append(stale)
            stale.with_name(stale.name + ".import").unlink(missing_ok=True)  # Godot's sidecar for the removed file
    return result


def _levels(output: Output) -> dict[str, Any]:
    level = output.level
    return {"lufs": _round(level.get("lufs")), "target_lufs": level.get("target"), "limiting_db": _round(level.get("limiting_db"))}


def _round(value: Any) -> float | None:
    return round(float(value), 2) + 0.0 if isinstance(value, int | float) else None  # + 0.0: no "-0.0"


def _song_timing(song: Any, output: Output, variant: Any = None) -> dict[str, Any]:
    """Tempo, sections, arrangement and markers in samples, seconds and bars (the game syncs to these)."""
    from segan.sequence import build_timeline

    timeline = build_timeline(song, variant)
    rate = output.rate

    def where(step: int) -> dict[str, Any]:
        return {"sample": timeline.frame(step, rate), "seconds": round(timeline.seconds(step), 6), "bar": round(timeline.bar_of(step), 4)}

    sections: dict[str, Any] = {}
    arrangement = []
    for span in timeline.sections:
        part = {"section": span.name, "start": timeline.frame(span.start, rate), "end": timeline.frame(span.end, rate),
                "start_seconds": round(timeline.seconds(span.start), 6), "end_seconds": round(timeline.seconds(span.end), 6),
                "start_bar": round(timeline.bar_of(span.start), 4), "end_bar": round(timeline.bar_of(span.end), 4),
                "patterns": [p.name for p in span.patterns]}  # fmt: skip
        arrangement.append(part)
        sections.setdefault(span.name, {k: v for k, v in part.items() if k != "section"})
    tempo = variant.tempo if variant is not None and variant.tempo else song.tempo
    timing: dict[str, Any] = {
        "bpm": tempo,
        "meter": list(song.meter),
        "steps_per_beat": song.steps_per_beat,
        "key": (variant.key if variant is not None and variant.key else song.key).describe(),
        "beat_seconds": round(60.0 / tempo, 6),
        "beat_count": timeline.total // song.steps_per_beat,
        "bars": round(timeline.total / timeline.steps_per_bar, 4),
        "sections": sections,
        "arrangement": arrangement,
        "markers": {name: where(step) for name, step in timeline.markers.items()},
    }
    if output.loop is not None and timeline.loop is not None:
        offset = output.loop[0] - timeline.frame(timeline.loop[0], rate)
        timing["loop"] = {"start": output.loop[0], "end": output.loop[1], "offset": offset, "section": song.loop,
                          "start_seconds": round(output.loop[0] / rate, 6), "end_seconds": round(output.loop[1] / rate, 6)}  # fmt: skip
    return timing


def _previous_outputs(out: Path) -> set[Path]:
    """Files the previous build recorded. Only paths inside output_dir count: never delete anything else."""
    root = out.resolve()
    try:
        data = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
        names = data.get("files", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return set()
    found: set[Path] = set()
    for name in names:
        if not isinstance(name, str) or Path(name).is_absolute():
            continue
        path = (root / name).resolve()
        if path.is_relative_to(root) and path != root and path.suffix in (".wav", ".tres"):
            found.add(path)
    return found
