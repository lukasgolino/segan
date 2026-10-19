"""Command-line interface for SEGAN (same shape and conventions as PAGAN's: `--json` on every command,
non-zero exit on errors, the project found from the target path)."""

from __future__ import annotations

import argparse
import json
import os
import re
from struct import error as struct_error
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from segan import progress
from segan.buildinfo import is_editable, version_string
from segan.findings import Finding, SeganError, display_path
from segan.asset import SFX_SUFFIX, SONG_SUFFIX, load_asset_or_raise
from segan.kit import KIT_SUFFIX, NAME_RE, Kit, load_kit_file
from segan.lint import lint_paths
from segan.project import CONFIG_NAME, Project, discover_project, find_project_root, load_project
from segan.settings import Change, describe, lookup, set_in_toml, set_setting, unset_setting
from segan.sfx import PRESETS, preset_data


class Output:
    """Human-readable output by default; one JSON object on stdout with --json."""

    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def say(self, text: str) -> None:
        if not self.as_json:
            print(text)

    def result(self, data: dict[str, Any]) -> None:
        if self.as_json:
            print(json.dumps({"ok": True, **data}, indent=2))

    def failure(self, findings: list[Finding], data: dict[str, Any] | None = None) -> None:
        if self.as_json:
            print(json.dumps({"ok": False, **(data or {}), "findings": [f.to_dict() for f in findings]}, indent=2))
        else:
            for finding in findings:
                print(finding.format())


def usage_error(message: str, path: Path | None = None) -> SeganError:
    return SeganError([Finding("E000", message, path)])


def template(name: str) -> str:
    return files("segan").joinpath("templates", name).read_text(encoding="utf-8")


def require_project() -> Project:
    root = find_project_root(Path.cwd())
    if root is None:
        raise usage_error(f"no {CONFIG_NAME} found here or in any parent directory; run `segan init` first")
    return load_project(root)


def project_for(targets: list[str]) -> Project:
    """The project containing the first target that is an existing path; else the one at the cwd."""
    for target in targets:
        path = Path(target)
        if path.exists():
            return discover_project(path if path.is_dir() else path.parent)
    return discover_project()


# --- segan init -------------------------------------------------------------------------------

STYLES = {
    "chiptune": ("chip", "chiptune: pulse/triangle/noise voices, mono channels, NES/Game Boy era"),
    "synth": ("synth", "synth: filtered saws, square bass, arpeggios, punchy drums (80s arcade)"),
}


def _pagan_clash(root: Path, output_dir: str) -> Path | None:
    """A pagan.toml at or above `root` whose output_dir is the same directory as ours (both write manifest.json)."""
    import tomllib

    ours = (root / output_dir).resolve()
    for directory in (root.resolve(), *root.resolve().parents):
        config = directory / "pagan.toml"
        if config.is_file():
            try:
                theirs = tomllib.loads(config.read_text(encoding="utf-8")).get("output_dir", "build")
            except (OSError, ValueError):
                return None
            return config if isinstance(theirs, str) and (directory / theirs).resolve() == ours else None
    return None


def cmd_init(args: argparse.Namespace, out: Output) -> int:
    root = Path(args.dir)
    config_path = root / CONFIG_NAME
    if config_path.exists():
        raise usage_error("a SEGAN project already exists here", config_path)
    godot_root: Path | None = None
    if args.godot is not None:
        godot_root = Path(args.godot)
        if not (godot_root / "project.godot").is_file():
            raise usage_error(f"--godot: no project.godot in {godot_root}")
    root.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    skipped: list[Path] = []
    mode = "open" if args.open else "strict"
    style = args.style or "chiptune"
    kit_name, style_text = STYLES[style]
    config_text = Template(template("segan.toml")).substitute(mode=mode, default_kit=f'default_kit = "{kit_name}"')
    output_dir = "build/audio"
    if godot_root is not None:
        output_dir = Path(os.path.relpath((godot_root / "assets" / "generated" / "audio").resolve(), root.resolve())).as_posix()
        config_text = set_in_toml(config_text, "output_dir", output_dir)
        config_text = set_in_toml(config_text, "export", ["wav", "godot"])
    config_path.write_text(config_text, encoding="utf-8")
    created.append(config_path)

    from segan.exporters.godot import find_godot_project

    if find_godot_project(root) is not None and not (root / ".gdignore").exists():
        (root / ".gdignore").write_text("", encoding="utf-8")  # keep Godot from importing sources and previews
        created.append(root / ".gdignore")
    for name, content in (
        ("SOUND.md", Template(template("SOUND.md")).safe_substitute(kit=kit_name)),
        ("BRIEF.md", Template(template("BRIEF.md")).safe_substitute(style=style_text)),
        (".gitignore", "previews/\n.segan-cache/\n"),
    ):
        path = root / name
        if path.exists():
            skipped.append(path)
        else:
            path.write_text(content, encoding="utf-8")
            created.append(path)
    for name in ("kits", "music", "sfx"):
        path = root / name
        if path.is_dir():
            skipped.append(path)
        else:
            path.mkdir()
            created.append(path)
    kit_path = root / "kits" / f"{kit_name}{KIT_SUFFIX}"
    if not kit_path.exists():
        kit_path.write_text(template(f"{kit_name}{KIT_SUFFIX}"), encoding="utf-8")
        created.append(kit_path)
    clash = _pagan_clash(root, output_dir)

    out.say(f"Initialized SEGAN project in {display_path(root)} ({mode} mode, {style} starter kit '{kit_name}')")
    for path in created:
        out.say(f"  created {display_path(path)}")
    for path in skipped:
        out.say(f"  kept existing {display_path(path)}")
    if clash is not None:
        out.say(f"  warning: {display_path(clash)} writes to the same output_dir; both tools write manifest.json there. "
                "Point one of them at its own folder (e.g. .../generated/audio).")  # fmt: skip
    out.say(f"Next: `segan kit show {kit_name}` and look at previews/kits/{kit_name}.listen.png; fill in BRIEF.md and SOUND.md.")
    out.result(
        {
            "project": display_path(root),
            "mode": mode,
            "style": style,
            "default_kit": kit_name,
            "godot_project": display_path(godot_root) if godot_root is not None else None,
            "output_dir": output_dir,
            "pagan_clash": display_path(clash) if clash is not None else None,
            "created": [display_path(p) for p in created],
            "skipped": [display_path(p) for p in skipped],
        }
    )
    return 0


# --- segan new kit ----------------------------------------------------------------------------

_KIT_STARTER = """\
name: $name
description: "TODO: what this kit sounds like"
# Each key is ONE letter or digit used in song grids. Reserved: "." rest, "-" hold, "|" bar line.
# Sources: osc (sine, triangle, saw, pulse, noise, bitnoise, fm) or drum (kick, snare, hat, clap, tom, cymbal).
# env: [attack s, decay s, sustain 0-1, release s]; gain in dB; range limits the notes it may play.
instruments:
  p: { name: lead, osc: pulse, duty: 0.25, env: [0.005, 0.1, 0.6, 0.1], gain: -8, range: [C4, C7] }
  b: { name: bass, osc: triangle, env: [0.002, 0.05, 0.9, 0.05], gain: -3, range: [E1, C4] }
  k: { name: kick, drum: kick }
  s: { name: snare, drum: snare, gain: -5 }
  h: { name: hat, drum: hat, gain: -13 }
groups:
  leads: [p]
  drums: [k, s, h]
"""


def cmd_new_kit(args: argparse.Namespace, out: Output) -> int:
    name: str = args.name
    if not NAME_RE.match(name):
        raise usage_error(f"invalid kit name {name!r}: use lowercase letters, digits, '_' or '-'")
    project = require_project()
    path = project.kit_path(name)
    if path.exists():
        raise usage_error("kit already exists", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(Template(_KIT_STARTER).substitute(name=name), encoding="utf-8")
    out.say(f"created {display_path(path)}")
    if project.config.default_kit is None:
        out.say(f"Set it as the default with `segan config set default_kit {name}`.")
    out.result({"created": display_path(path), "kit": name})
    return 0


# --- segan kit show ---------------------------------------------------------------------------


def _resolve_kit(target: str, project: Project) -> Kit:
    path = Path(target)
    if path.is_file():
        return load_kit_file(path)
    if target.endswith(KIT_SUFFIX) or "/" in target:
        raise usage_error(f"no such file: {target}")
    if project.config_path is None:
        raise usage_error(f"{target!r} isn't a file, and there's no {CONFIG_NAME} to look up kit names in")
    return project.load_kit(target)


def cmd_kit_show(args: argparse.Namespace, out: Output) -> int:
    from segan.kitshow import render_kit_show, write_kit_show

    project = project_for(args.kits)
    targets: list[str] = args.kits or project.kit_names()
    if not targets:
        raise usage_error(f"no kits found in {display_path(project.kits_dir)}")
    outputs: list[dict[str, Any]] = []
    findings: list[Finding] = []
    threshold = project.config.lint.max_aliasing_db
    for target in targets:
        try:
            kit = _resolve_kit(target, project)
        except SeganError as exc:
            findings.extend(exc.findings)
            continue
        progress.note(f"rendering kit {kit.name}")
        show = render_kit_show(kit, project)
        sheet, wavs = write_kit_show(show, project.preview_dir / "kits", threshold)
        over = {k: round(v, 1) for k, v in show.aliasing.items() if v is not None and v > threshold}
        out.say(f"kit {kit.name}: {display_path(sheet)}  ({len(kit.instruments)} instruments, {len(show.audio) / show.rate:.1f}s)")
        out.say(f"  listen: {display_path(wavs[0])} (one WAV per instrument next to it)")
        if over:
            out.say(f"  W010 aliasing over {threshold:g} dB: {over} - raise [mix] oversample or lower the range")
        instruments = {
            k: {"name": i.name, "source": i.describe(), "aliasing_db": None if (a := show.aliasing.get(k)) is None else round(a, 1)}
            for k, i in kit.instruments.items()
        }
        outputs.append({"kit": kit.name, "sheet": display_path(sheet), "wavs": [display_path(w) for w in wavs],
                        "instruments": instruments, "lufs": round(show.lufs, 2)})  # fmt: skip
    if findings:
        out.failure(findings, {"outputs": outputs})
        return 1
    out.result({"outputs": outputs})
    return 0


# --- assets: resolve, new song/sfx ----------------------------------------------------------


def resolve_asset_path(target: str, project: Project) -> Path:
    """A path to an asset file, or a bare asset name looked up in music/ and sfx/."""
    path = Path(target)
    if path.is_file():
        return path
    if NAME_RE.match(target):
        for candidate in (project.music_dir / f"{target}{SONG_SUFFIX}", project.sfx_dir / f"{target}{SFX_SUFFIX}"):
            if candidate.is_file():
                return candidate
    raise usage_error(f"no such asset: {target} (give a path, or the name of a file in music/ or sfx/)")


def load_targets(targets: list[str], project: Project) -> tuple[list[Any], list[Finding]]:
    assets: list[Any] = []
    findings: list[Finding] = []
    for target in targets:
        try:
            assets.append(load_asset_or_raise(resolve_asset_path(target, project), project))
        except SeganError as exc:
            findings.extend(exc.findings)
    return assets, findings


def _kit_line(project: Project, kit: str | None) -> tuple[str, Kit | None]:
    if kit is not None:
        return f"kit: {kit}\n", project.load_kit(kit)
    if project.config.default_kit is not None:
        return f"# kit: {project.config.default_kit}   (project default)\n", project.load_kit(project.config.default_kit)
    if project.config.mode == "open":
        return _INLINE_KIT, None
    raise usage_error("no --kit given and segan.toml has no default_kit")


_INLINE_KIT = """\
instruments:              # inline instruments (open mode); or name a kit file with `kit:`
  p: { name: lead, osc: pulse, duty: 0.25, env: [0.005, 0.1, 0.6, 0.1], gain: -8 }
  b: { name: bass, osc: triangle, env: [0.002, 0.05, 0.9, 0.05], gain: -3 }
  k: { name: kick, drum: kick }
  s: { name: snare, drum: snare, gain: -5 }
  h: { name: hat, drum: hat, gain: -13 }
"""


def _song_scaffold(name: str, description: str, kit_line: str, kit: Kit | None, key_text: str, tempo: int, bars: int, style: int) -> str:
    from segan.notes import parse_key

    key = parse_key(key_text)
    if key is None:
        raise usage_error(f"invalid --key {key_text!r}: a root and a scale, e.g. 'A minor', 'C major', 'D dorian'")
    length = bars * 16
    melodic = [k for k, i in (kit.instruments.items() if kit else []) if not i.is_drum]
    drums = [k for k, i in (kit.instruments.items() if kit else []) if i.is_drum][:3] or ["k", "s", "h"]
    lead = melodic[0] if melodic else "p"
    keys_line = ", ".join(f"{k}={i.name or i.describe()}" for k, i in kit.instruments.items()) if kit else "see the kit"
    root = key.root
    lead_low = 60 + root if 60 + root <= 64 else 48 + root + 12
    bass_low = 36 + root if 36 + root <= 40 else 24 + root + 12

    def rows(low: int) -> list[str]:
        return [key.name(m) for m in key.notes_between(low, low + 12)]

    def grid(labels: list[str]) -> str:
        cells = "|".join(["...."] * (length // 4))
        return "".join(f"      {cells}  {label}\n" for label in labels)

    return f"""name: {name}
description: {json.dumps(description)}
{kit_line.rstrip()}
tempo: {tempo}
meter: [4, 4]
steps_per_beat: 4             # 16th-note grid; `|` (ignored) marks each beat
key: {key.describe()}
status: draft
style_version: {style}
tags: []

# Rows are the scale notes in each roll range, highest first; drum rows are kit keys. Keep the labels:
# lint checks them (E011), so a missing or extra row can't shift the grid.
# Roll cells: a kit key starts a note, - holds it, . rests. Drum cells: x hit, X accent, o ghost.
tracks:
  lead:  {{ roll: [{key.name(lead_low)}, {key.name(lead_low + 12)}] }}      # kit keys: {keys_line}
  bass:  {{ roll: [{key.name(bass_low)}, {key.name(bass_low + 12)}] }}
  drums: {{ drums: [{', '.join(drums)}] }}

patterns:
  a:
    length: {length}
    lead: |
{grid(rows(lead_low))}    bass: |
{grid(rows(bass_low))}    drums: |
{grid(drums)}
sections:
  main: [a]
arrangement: [main]
loop: main
# variants:
#   danger: {{ tempo: {tempo + 20} }}
"""


def _sfx_scaffold(name: str, description: str, kit_line: str, preset: str | None, style: int) -> str:
    head = f"name: {name}\ndescription: {json.dumps(description)}\n"
    if preset is not None:
        return head + f"""preset: {preset}             # starting point; `segan bake sfx {name} --in-place` writes out every field to tune
category: {preset_data(preset).get('category', 'sfx')}
status: draft
style_version: {style}
tags: []
# Override any preset field here, e.g. a different length:
# duration: 0.5
# The preset's layers (ids): {', '.join(f"{layer.get('id')} ({layer.get('osc') or 'drum ' + str(layer.get('drum'))})" for layer in preset_data(preset).get('layers', []))}
# Change one by its id (only the fields you give change), add new ones, or drop some with `remove: [id, ...]`:
# layers:
#   - {{ id: {next((layer.get('id') for layer in preset_data(preset).get('layers', []) if layer.get('id')), 'tone')}, gain: -9 }}
"""
    return head + f"""{kit_line.rstrip() if kit_line.startswith('kit') else '# kit: (layers can use `instrument: <key>` from the kit)'}
category: sfx                 # picks the loudness target ([loudness] in segan.toml)
duration: 0.3                 # seconds of dry sound; the room tail is added after
status: draft
style_version: {style}
tags: []
layers:
  - id: tone
    osc: pulse                # sine, triangle, saw, pulse, noise, bitnoise, fm; or drum: kick|snare|hat|clap|tom|cymbal
    duty: 0.5
    pitch: [[0, C5], [0.1, G5]]   # keyframes [seconds, note or Hz]
    slide: true               # glide between keyframes (false: step)
    env: [0.002, 0.08, 0.5, 0.1]  # attack, decay, sustain (0-1), release
    length: 0.15              # seconds held before the release
    gain: -6
# variations: {{ count: 4, seed: 1, pitch: 1.0, timbre: 0.2 }}   # for sounds that repeat a lot
"""


def cmd_new_asset(args: argparse.Namespace, out: Output) -> int:
    kind: str = args.kind
    name: str = args.name
    if not NAME_RE.match(name):
        raise usage_error(f"invalid name {name!r}: use lowercase letters, digits, '_' or '-'")
    project = require_project()
    description = args.description or "TODO: what this is, when it plays and how it should sound"
    style = project.config.style_version
    if kind == "song":
        if not 1 <= args.bars <= 8:
            raise usage_error("--bars must be 1-8 (make longer songs from several patterns)")
        kit_line, kit = _kit_line(project, args.kit)
        text = _song_scaffold(name, description, kit_line, kit, args.key, args.tempo, args.bars, style)
        path = project.music_dir / f"{name}{SONG_SUFFIX}"
    else:
        if args.preset is not None and args.preset not in PRESETS:
            raise usage_error(f"unknown --preset {args.preset!r}; presets: {', '.join(PRESETS)}")
        kit_line = f"kit: {args.kit}\n" if args.kit else ""
        if args.kit:
            project.load_kit(args.kit)
        text = _sfx_scaffold(name, description, kit_line, args.preset, style)
        path = project.sfx_dir / f"{name}{SFX_SUFFIX}"
    other = (project.sfx_dir / f"{name}{SFX_SUFFIX}") if kind == "song" else (project.music_dir / f"{name}{SONG_SUFFIX}")
    if path.exists():
        raise usage_error("file already exists", path)
    if other.exists():
        raise usage_error(f"{display_path(other)} already uses the name {name!r}: names are unique across songs and SFX", other)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    out.say(f"created {display_path(path)}")
    out.result({"created": display_path(path), "kind": kind, "name": name})
    return 0


# --- segan render / preview / gallery / bake ----------------------------------------------------


def cmd_render(args: argparse.Namespace, out: Output) -> int:
    from segan.render import render_asset

    project = project_for(args.assets)
    assets, findings = load_targets(args.assets, project)
    outputs: list[dict[str, Any]] = []
    for asset in assets:
        render = render_asset(asset, project)
        folder = project.preview_dir / asset.name
        written = []
        for output in render.outputs:
            path = folder / f"{output.stem.replace('/', '.')}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(output.wav())
            written.append(display_path(path))
        out.say(f"{asset.name}: wrote {len(written)} WAVs to {display_path(folder)}")
        outputs.append({"asset": asset.name, "files": written})
    if findings:
        out.failure(findings, {"outputs": outputs})
        return 1
    out.result({"outputs": outputs})
    return 0


def _position(text: str | None, asset: Any) -> float | None:
    """--from/--to: seconds ("2.5s" or a plain number for SFX) or a bar number for songs ("5")."""
    if text is None:
        return None
    try:
        if text.endswith("s"):
            return float(text[:-1])
        value = float(text)
    except ValueError:
        raise usage_error(f"invalid position {text!r}: a bar number (songs) or seconds like 2.5s") from None
    if asset.kind == "song":
        from segan.sequence import build_timeline

        timeline = build_timeline(asset)
        return timeline.seconds(round((value - 1) * timeline.steps_per_bar))
    return value


def cmd_preview(args: argparse.Namespace, out: Output) -> int:
    from segan.preview import write_preview
    from segan.render import render_asset

    project = project_for(args.assets)
    assets, findings = load_targets(args.assets, project)
    outputs: list[dict[str, Any]] = []
    for asset in assets:
        render = render_asset(asset, project)
        result = write_preview(asset, render, project, _position(args.start, asset), _position(args.end, asset), args.output)
        if not result.files:
            raise usage_error(f"{asset.name} has no output {args.output!r} (outputs: {', '.join(o.id or 'main' for o in render.outputs)})")
        for entry in result.files:
            a = entry["analysis"]
            target = f" (target {a['target_lufs']:g})" if a.get("target_lufs") is not None else ""
            out.say(f"{entry['output']:>16}: {display_path(entry['sheet'])}  {a['seconds']:.2f}s, {a['lufs']:.1f} LUFS{target}, peak {a['true_peak_dbtp']:.1f} dBTP")
            out.say(f"{'':>16}  listen: {display_path(entry['wav'])}" + (f"  seam: {display_path(entry['seam'])} (click {a['seam_click']:.4f})" if "seam" in entry else ""))
        outputs.append({"asset": asset.name, "kind": asset.kind, "outputs": [
            {"output": e["output"], "wav": display_path(e["wav"]), "sheet": display_path(e["sheet"]),
             **({"seam": display_path(e["seam"])} if "seam" in e else {}), "analysis": e["analysis"]} for e in result.files]})  # fmt: skip
    if findings:
        out.failure(findings, {"outputs": outputs})
        return 1
    if not out.as_json:
        print("Open the .listen.png sheets to check them; a human has to listen to the WAVs before approving.")
    out.result({"outputs": outputs})
    return 0


def cmd_gallery(args: argparse.Namespace, out: Output) -> int:
    from segan.listen import GalleryItem, gallery_image
    from segan.render import render_asset

    project = discover_project()
    result = lint_paths(project, render=False)
    items = []
    for asset in sorted((a for a in result.assets if not a.meta.template), key=lambda a: (a.kind != "sfx", a.name)):
        render = render_asset(asset, project)
        main = render.main
        category = getattr(asset, "category", "music")
        items.append(GalleryItem(main.stem, category, main.audio, main.rate, float(main.level.get("lufs") or -100.0),
                                 main.level.get("target"), float(main.level.get("measured") or -100.0)))  # fmt: skip
    path = Path(args.out) if args.out else project.preview_dir / "gallery.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    gallery_image(items, f"{project.root.name} gallery").save(path)
    out.say(f"wrote {display_path(path)} ({len(items)} assets)")
    if result.errors:
        out.say(f"{len(result.errors)} errors: assets with errors are missing; run `segan lint`")
    out.result({"gallery": display_path(path), "assets": len(items), "errors": len(result.errors)})
    return 0


def cmd_bake_sfx(args: argparse.Namespace, out: Output) -> int:
    from segan.yamlwrite import dump_mapping

    project = project_for([args.sfx])
    path = resolve_asset_path(args.sfx, project)
    sfx = load_asset_or_raise(path, project)
    if sfx.kind != "sfx":
        raise usage_error(f"{sfx.name} is a song; `segan bake sfx` expands SFX presets and templates")
    fields = {k: v for k, v in sfx.effective.items() if k not in ("preset", "extends", "remove", "template")}
    name = sfx.name if args.in_place else (args.name or f"{sfx.name}_baked")
    if not NAME_RE.match(name):
        raise usage_error(f"invalid name {name!r}")
    fields["name"] = name
    target = path if args.in_place else (Path(args.out) if args.out else project.sfx_dir / f"{name}{SFX_SUFFIX}")
    if target.exists() and not (args.force or args.in_place):
        raise usage_error("file already exists (pass --force to overwrite)", target)
    header = f"# Baked from {path.name}" + (f" (preset {sfx.preset})" if sfx.preset else "") + ": every field written out for hand-tuning.\n"
    order = ["name", "description", "category", "kit", "duration", "loop", "crossfade", "normalize", "status", "style_version", "tags", "lint", "layers", "variations", "phases"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(header + dump_mapping(fields, order), encoding="utf-8")
    out.say(f"baked {sfx.name} -> {display_path(target)}")
    if not args.in_place:
        out.say("Asset names are unique: when you keep the bake, delete or rename the original.")
    out.result({"created": display_path(target), "name": name})
    return 0


# --- segan lint -------------------------------------------------------------------------------


def _rule_counts(findings: list[Finding]) -> str:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.rule] = counts.get(f.rule, 0) + 1
    return ", ".join(f"{rule}x{n}" for rule, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def cmd_lint(args: argparse.Namespace, out: Output) -> int:
    project = project_for(args.paths)
    paths = [Path(p) for p in args.paths] or None
    missing = [p for p in paths or [] if not p.exists()]
    if missing:
        raise usage_error(f"no such file or directory: {', '.join(map(str, missing))}")
    result = lint_paths(project, paths, render=not args.no_render)
    failed = bool(result.errors) or (args.warnings_as_errors and bool(result.warnings))
    if out.as_json:
        print(json.dumps({"ok": not failed, "files": [display_path(f) for f in result.files], "errors": len(result.errors),
                          "warnings": len(result.warnings), "findings": [f.to_dict() for f in result.findings]}, indent=2))  # fmt: skip
    else:
        for finding in result.findings:
            print(finding.format())
        summary = f"{len(result.files)} files: {len(result.errors)} errors, {len(result.warnings)} warnings"
        print(summary + (f" ({_rule_counts(result.warnings)})" if result.warnings else ""))
    return 1 if failed else 0


# --- segan build ------------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace, out: Output) -> int:
    from segan.build import build
    from segan.exporters.godot import find_godot_binary, res_path, verify_with_godot

    project = project_for([args.project] if args.project else [])
    if project.config_path is None:
        raise usage_error(f"no {CONFIG_NAME} found; `segan build` needs a project (run `segan init`)")
    result = build(project)
    if result.errors:
        out.failure(result.errors)
        if not out.as_json:
            print("build failed: fix the errors above (`segan lint` shows warnings too)")
        return 1
    warnings = result.lint.warnings
    out.say(f"built {result.assets} assets into {display_path(project.output_dir)}")
    out.say(f"  {len(result.written)} files written, {len(result.unchanged)} unchanged, {len(result.removed)} stale removed")
    if result.imports:
        out.say(f"  {len(result.imports)} Godot .import files updated (loop points, compression)")
    if warnings:
        out.say(f"  {len(warnings)} lint warnings: {_rule_counts(warnings)} (run `segan lint` to see them)")
    verified: bool | None = None
    if args.verify_godot:
        godot = find_godot_binary()
        if result.godot_root is None or result.manifest is None:
            raise usage_error('--verify-godot needs export = ["wav", "godot"] in segan.toml')
        if godot is None:
            raise usage_error("--verify-godot: no Godot binary found; set GODOT=/path/to/godot or put godot on PATH")
        check = verify_with_godot(godot, result.godot_root, res_path(result.manifest, result.godot_root))
        verified = check.ok
        if not check.ok:
            if out.as_json:
                out.failure([Finding("E000", "Godot failed to load or play generated audio:\n" + check.output[-3000:])])
            else:
                print(check.output[-3000:])
                print("Godot verification FAILED")
            return 1
        out.say(f"  Godot: all {check.streams} streams load, loop where they should and play")
    out.result(
        {
            "output_dir": display_path(project.output_dir),
            "assets": result.assets,
            "written": [display_path(p) for p in result.written],
            "unchanged": len(result.unchanged),
            "removed": [display_path(p) for p in result.removed],
            "imports": [display_path(p) for p in result.imports],
            "manifest": display_path(result.manifest) if result.manifest else None,
            "warnings": len(warnings),
            "warnings_by_rule": {r: sum(f.rule == r for f in warnings) for r in sorted({f.rule for f in warnings})},
            "godot_verified": verified,
        }
    )
    return 0


# --- segan status / mark / style bump / mix adjust -------------------------------------------


def missing_docs(project: Project) -> list[str]:
    return [doc for doc in ("BRIEF.md", "SOUND.md") if not (project.root / doc).is_file()]


def cmd_status(args: argparse.Namespace, out: Output) -> int:
    from segan.manage import catalogue

    project = project_for([args.project] if args.project else [])
    if project.config_path is None:
        raise usage_error(f"no {CONFIG_NAME} found here or in any parent directory: this isn't a SEGAN project yet "
                          "(run `segan init <dir>`, or cd into the audio folder)")  # fmt: skip
    entries = catalogue(project, render=not args.fast)
    current = project.config.style_version
    if out.as_json:
        kits: dict[str, Any] = {}
        for name in project.kit_names():
            try:
                kits[name] = {k: i.name or i.describe() for k, i in project.load_kit(name).instruments.items()}
            except SeganError:
                kits[name] = None
        print(json.dumps({"ok": True, "project": display_path(project.root), "style_version": current, "default_kit": project.config.default_kit,
                          "kits": kits, "missing_docs": missing_docs(project), "segan": version_string(),
                          "assets": [{"name": e.name, "kind": e.kind, "path": display_path(e.path), "description": e.description, "status": e.status,
                                      "style_version": e.style_version, "category": e.category, "seconds": e.seconds, "outputs": e.outputs,
                                      "errors": e.errors, "warnings": e.warnings, "tags": list(e.tags), "template": e.template,
                                      "needs": e.needs(current)} for e in entries]}, indent=2))  # fmt: skip
        return 0
    kit = project.config.default_kit or ("open mode" if project.config.mode == "open" else "none")
    print(f"{display_path(project.root)}: {len(entries)} assets, default kit {kit}, style v{current}  [{version_string()}]")
    for name in project.kit_names():
        try:
            loaded = project.load_kit(name)
        except SeganError:
            print(f"  kit {name}: has errors (`segan lint kits/`)")
            continue
        listing = ", ".join(f"{k}={i.name or i.describe()}" for k, i in loaded.instruments.items())
        print(f"  kit {name}: {listing}")
    for doc in missing_docs(project):
        print(f"  missing {doc}: write one (`segan init` templates: what the game needs / how it must sound) and ask the owner to fill the gaps")
    if is_editable():
        print("  note: SEGAN is an editable dev checkout; if this project pins a release, install that instead")
    for e in entries:
        length = f"{e.seconds:.2f}s" if e.seconds is not None else "?"
        flags = ", ".join(e.needs(current)) or "ok"
        print(f"  {e.name:<20} {e.kind:<5} {e.category:<8} {length:>8}  {e.status:<8} v{e.style_version}  [{flags}]")
        if e.description:
            description = e.description.replace("\n", " ")
            print(f"      {description[:100]}{'...' if len(description) > 100 else ''}")
    stale = [e for e in entries if e.style_version < current]
    if stale:
        print(f"{len(stale)} assets predate style v{current}: see SOUND.md's changelog, update them, then `segan mark --current <asset>`")
    return 0


def cmd_mark(args: argparse.Namespace, out: Output) -> int:
    from segan.manage import mark, outdated

    project = project_for(args.assets if not args.outdated else [])
    if args.outdated:
        paths = outdated(project)
    else:
        if not args.assets:
            raise usage_error("name the assets to mark (or pass --outdated)")
        paths = [resolve_asset_path(a, project) for a in args.assets]
    if args.status is None and not args.current:
        raise usage_error("nothing to do: pass --status approved|draft and/or --current")
    mark(paths, args.status, project.config.style_version if args.current else None)
    for path in paths:
        out.say(f"marked {display_path(path)}")
    out.result({"marked": [display_path(p) for p in paths]})
    return 0


def cmd_style_bump(args: argparse.Namespace, out: Output) -> int:
    from segan.manage import bump_style, outdated

    project = require_project()
    version = bump_style(project, args.note)
    stale = len(outdated(load_project(project.root)))
    out.say(f"style is now v{version}; logged in SOUND.md. {stale} assets are flagged for review (lint W006, `segan status`).")
    out.result({"style_version": version, "outdated": stale})
    return 0


def cmd_mix_adjust(args: argparse.Namespace, out: Output) -> int:
    from segan.manage import MixAdjustment, adjust_mix

    project = require_project()
    adjustment = MixAdjustment(args.brightness, args.warmth, args.room, args.crush, args.loudness)
    if adjustment.is_identity():
        raise usage_error("nothing to change: pass --brightness, --warmth, --room, --crush and/or --loudness")
    changes = adjust_mix(project, adjustment, args.dry_run)
    for key, (old, new) in changes.items():
        out.say(f"  {key}: {json.dumps(old)} -> {json.dumps(new)}")
    if not changes:
        out.say("nothing changed (already at the limits?)")
    elif args.dry_run:
        out.say(f"dry run: {len(changes)} settings would change")
    else:
        out.say(f"saved in {CONFIG_NAME}: every song and SFX re-renders with this on the next `segan build` / `segan preview`; "
                "check with `segan gallery`, and log it in BRIEF.md's feedback log.")  # fmt: skip
    out.result({"changes": {k: {"from": a, "to": b} for k, (a, b) in changes.items()}, "written": bool(changes) and not args.dry_run})
    return 0


# --- segan mcp / skill install ----------------------------------------------------------------


def cmd_mcp(args: argparse.Namespace, out: Output) -> int:
    try:
        from segan.mcp_server import serve
    except ImportError:
        raise usage_error('the MCP server needs the "mcp" extra: pip install "segan[mcp]"') from None
    return serve(args.project, args.allow_godot)


SKILL_FILES = ("SKILL.md", "reference.md")


def _git_root(start: Path) -> Path | None:
    for directory in (start.resolve(), *start.resolve().parents):
        if (directory / ".git").exists():
            return directory
    return None


def cmd_skill_install(args: argparse.Namespace, out: Output) -> int:
    base = Path(args.dir) if args.dir else (_git_root(Path.cwd()) or Path.cwd())
    target = base / ".claude" / "skills" / "segan"
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in SKILL_FILES:
        text = files("segan").joinpath("skill", name).read_text(encoding="utf-8")
        path = target / name
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue
        path.write_text(text, encoding="utf-8")
        written.append(display_path(path))
    out.say(f"SEGAN skill {'installed' if written else 'already up to date'} in {display_path(target)}")
    out.result({"skill_dir": display_path(target), "written": written})
    return 0


# --- segan import midi ------------------------------------------------------------------------


def cmd_import_midi(args: argparse.Namespace, out: Output) -> int:
    from segan.midi import MidiError, import_midi, read_midi

    source = Path(args.file)
    project = discover_project()
    try:
        midi = read_midi(source.read_bytes())
    except OSError as exc:
        raise usage_error(f"can't read {source}: {exc.strerror}", source) from None
    except (MidiError, IndexError, struct_error) as exc:
        raise usage_error(f"can't read MIDI: {exc}", source) from None
    kit_name = args.kit or project.config.default_kit
    if kit_name is None:
        raise usage_error("no --kit given and segan.toml has no default_kit (the importer maps MIDI parts onto a kit)")
    kit = project.load_kit(kit_name)
    name = args.name or re.sub(r"[^a-z0-9_]", "_", source.stem.lower()).strip("_") or "imported"
    if not NAME_RE.match(name):
        raise usage_error(f"invalid name {name!r}; pass --name")
    if args.quantize not in (4, 8, 12, 16, 24, 32):
        raise usage_error("--quantize must be 4, 8, 12, 16, 24 or 32 (grid notes per whole note)")
    try:
        text, report = import_midi(midi, kit, kit_name, name, args.quantize, args.key, args.bars_per_pattern, not args.no_loop)
    except (MidiError, ValueError) as exc:
        raise usage_error(str(exc), source) from None
    path = Path(args.out) if args.out else project.music_dir / f"{name}{SONG_SUFFIX}"
    if path.exists() and not args.force:
        raise usage_error("file already exists (pass --force to overwrite)", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    r = report
    out.say(f"imported {display_path(source)} -> {display_path(path)}: {r.notes_out} of {r.notes_in} notes, {r.bars} bars, {r.patterns} patterns")
    out.say(f"  {r.tempo:g} bpm, {r.meter[0]}/{r.meter[1]}, key {r.key} ({r.key_source})" + (f"; {r.tempo_changes_ignored} tempo changes ignored" if r.tempo_changes_ignored else ""))
    out.say(f"  changes: {r.quantized} quantized, {r.snapped} snapped to the key, {r.octave_moved} moved by an octave, {r.merged} merged")
    for reason, count in sorted(r.dropped.items()):
        out.say(f"  dropped {count}: {reason}")
    for track in r.tracks:
        what = f"drums {' '.join(track['drums'])}" if "drums" in track else f"program {track['program']} -> {track['instrument']} ({track['instrument_name'] or '-'})"
        out.say(f"  track {track['track']}: MIDI track {track['midi_track']} channel {track['channel']}, {what}")
    out.say("Lint and preview it, then check the listen sheet against the original.")
    out.result({"created": display_path(path), "report": report.as_dict()})
    return 0


# --- segan config -----------------------------------------------------------------------------


def cmd_config_show(args: argparse.Namespace, out: Output) -> int:
    project = require_project()
    rows = describe(project.config)
    if out.as_json:
        print(json.dumps({"ok": True, "config": display_path(project.config_path or project.root), "settings": rows}, indent=2))
        return 0
    print(f"{display_path(project.config_path or project.root)}  (change with `segan config set <key> <value>`)")
    for row in rows:
        marker = " " if row["is_default"] else "*"
        print(f"{marker} {row['key']:<28} = {json.dumps(row['value']):<16} {row['meaning']}")
    print("* = changed from the default. 'all' settings re-render every song and SFX on the next build/preview.")
    return 0


def cmd_config_get(args: argparse.Namespace, out: Output) -> int:
    project = require_project()
    if lookup(args.key) is None:
        raise usage_error(f"unknown setting {args.key!r}; see `segan config show`")
    rows = [r for r in describe(project.config) if r["key"] == args.key]
    row = rows[0] if rows else {"key": args.key, "value": None}
    out.say(json.dumps(row["value"]))
    out.result(row)
    return 0


def cmd_config_set(args: argparse.Namespace, out: Output) -> int:
    project = require_project()
    return report_change(set_setting(project, args.key, args.value), project, out)


def cmd_config_unset(args: argparse.Namespace, out: Output) -> int:
    project = require_project()
    return report_change(unset_setting(project, args.key), project, out)


def report_change(change: Change, project: Project, out: Output) -> int:
    from segan.manage import catalogue

    updated = load_project(project.root)
    entries = catalogue(updated, render=False)
    names = [e.name for e in entries]
    errors = sum(e.errors for e in entries)
    out.say(f"{change.key}: {json.dumps(change.old)} -> {json.dumps(change.new)}  (saved in {CONFIG_NAME})")
    if change.refresh == "all":
        out.say(f"  every song and SFX ({len(names)}) re-renders with this on the next `segan build` / `segan preview`.")
    elif change.refresh == "build":
        out.say("  takes effect on the next `segan build`.")
    if errors:
        out.say(f"  {errors} lint errors now: run `segan lint` to see them.")
    out.result({"key": change.key, "old": change.old, "new": change.new, "refreshes": change.refresh, "assets": names, "errors": errors})
    return 0


# --- parser -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS: a subcommand's --json doesn't reset a --json given before the subcommand.
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable JSON output")

    parser = argparse.ArgumentParser(
        prog="segan", description="SEGAN (Sound Effect Grammar And Notation): game sound effects and music as text."
    )
    parser.add_argument("--version", action="version", version=version_string())
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output (any command)")
    parser.add_argument("--quiet", action="store_true", help="no progress lines on stderr")
    commands = parser.add_subparsers(title="commands", metavar="<command>")

    init = commands.add_parser("init", parents=[common], help="create a SEGAN project")
    init.add_argument("dir", nargs="?", default=".", help="project directory (default: current)")
    init.add_argument("--open", action="store_true", help="open mode: songs and SFX may define instruments inline")
    init.add_argument("--style", choices=list(STYLES), help="starter kit: chiptune (default) or synth")
    init.add_argument("--godot", metavar="DIR", help="Godot project dir: build into DIR/assets/generated/audio with Godot resources")
    init.set_defaults(handler=cmd_init)

    new = commands.add_parser("new", help="scaffold a new source file")
    new_kinds = new.add_subparsers(title="kinds", metavar="<kind>")
    new_kit = new_kinds.add_parser("kit", parents=[common], help="scaffold a kit file")
    new_kit.add_argument("name", help="kit name, e.g. nes")
    new_kit.set_defaults(handler=cmd_new_kit)
    new_song = new_kinds.add_parser("song", parents=[common], help="scaffold a song (tracks, an empty pattern, a loop)")
    new_song.add_argument("name", help="song name, e.g. overworld")
    new_song.add_argument("--kit", help="kit name (default: the project's default_kit)")
    new_song.add_argument("--key", default="A minor", help='key, e.g. "A minor" (default), "C major", "D dorian"')
    new_song.add_argument("--tempo", type=int, default=120, help="bpm (default 120)")
    new_song.add_argument("--bars", type=int, default=2, help="bars in the first pattern (default 2)")
    new_song.add_argument("--description", help="what it is and how it should sound; kept in the file")
    new_song.set_defaults(handler=cmd_new_asset, kind="song")
    new_sfx = new_kinds.add_parser("sfx", parents=[common], help="scaffold a sound effect (optionally from a preset)")
    new_sfx.add_argument("name", help="SFX name, e.g. coin")
    new_sfx.add_argument("--preset", help=f"starting point: {', '.join(PRESETS)}")
    new_sfx.add_argument("--kit", help="kit whose instruments layers may use (instrument: <key>)")
    new_sfx.add_argument("--description", help="what it is and how it should sound; kept in the file")
    new_sfx.set_defaults(handler=cmd_new_asset, kind="sfx")

    render = commands.add_parser("render", parents=[common], help="render songs/SFX to WAVs in the previews folder")
    render.add_argument("assets", nargs="+", help="asset files or names")
    render.set_defaults(handler=cmd_render)

    preview = commands.add_parser("preview", parents=[common], help="WAVs + listen sheets (+ seam views for loops) and the numbers to check")
    preview.add_argument("assets", nargs="+", help="asset files or names")
    preview.add_argument("--from", dest="start", help="start of the shown window: bar number (songs) or seconds (2.5s)")
    preview.add_argument("--to", dest="end", help="end of the shown window")
    preview.add_argument("--output", help="only this output: main, variant:<name>, variation:<n>, phase:<name>, stem:<track>")
    preview.set_defaults(handler=cmd_preview)

    gallery = commands.add_parser("gallery", parents=[common], help="every asset side by side + loudness by category")
    gallery.add_argument("--out", help="output PNG (default: <previews>/gallery.png)")
    gallery.set_defaults(handler=cmd_gallery)

    bake = commands.add_parser("bake", help="write an expanded source for hand-tuning")
    bake_kinds = bake.add_subparsers(title="kinds", metavar="<kind>")
    bake_sfx = bake_kinds.add_parser("sfx", parents=[common], help="an SFX with its preset/template expanded into every field")
    bake_sfx.add_argument("sfx", help="SFX file or name")
    bake_sfx.add_argument("--in-place", action="store_true", help="replace the SFX's own file (drops preset/extends)")
    bake_sfx.add_argument("--name", help="name of the baked SFX (default: <sfx>_baked)")
    bake_sfx.add_argument("--out", help="output path")
    bake_sfx.add_argument("--force", action="store_true", help="overwrite an existing file")
    bake_sfx.set_defaults(handler=cmd_bake_sfx)

    lint = commands.add_parser("lint", parents=[common], help="check sources (and their rendered audio) for errors and warnings")
    lint.add_argument("paths", nargs="*", help="files or directories (default: the whole project)")
    lint.add_argument("--warnings-as-errors", action="store_true", help="exit non-zero on warnings too")
    lint.add_argument("--no-render", action="store_true", help="format checks only (skip the audio warnings)")
    lint.set_defaults(handler=cmd_lint)

    build_cmd = commands.add_parser("build", parents=[common], help="lint, then write WAVs, manifest.json and engine files to output_dir")
    build_cmd.add_argument("project", nargs="?", help="project directory (default: the one containing the cwd)")
    build_cmd.add_argument("--verify-godot", action="store_true", help="load and play every generated stream in headless Godot")
    build_cmd.set_defaults(handler=cmd_build)

    status = commands.add_parser("status", parents=[common], help="catalogue of every song and SFX and what needs attention")
    status.add_argument("project", nargs="?", help="project directory (default: the one containing the cwd)")
    status.add_argument("--fast", action="store_true", help="don't render (no lengths, no audio warnings)")
    status.set_defaults(handler=cmd_status)

    mark_cmd = commands.add_parser("mark", parents=[common], help="set assets' status and/or stamp the current style version")
    mark_cmd.add_argument("assets", nargs="*", help="asset files or names")
    mark_cmd.add_argument("--status", choices=["draft", "approved"], help="set status (approved = a human listened and agreed)")
    mark_cmd.add_argument("--current", action="store_true", help="set style_version to the project's current one")
    mark_cmd.add_argument("--outdated", action="store_true", help="apply to every asset made under an older style")
    mark_cmd.set_defaults(handler=cmd_mark)

    style = commands.add_parser("style", help="sound style versioning")
    style_cmds = style.add_subparsers(title="style commands", metavar="<command>")
    bump_cmd = style_cmds.add_parser("bump", parents=[common], help="record a style change; flags older assets for review")
    bump_cmd.add_argument("note", help='what changed, e.g. "drums punchier: kick decay 0.2 -> 0.3"')
    bump_cmd.set_defaults(handler=cmd_style_bump)

    mix = commands.add_parser("mix", help="the shared mix ([mix] in segan.toml)")
    mix_cmds = mix.add_subparsers(title="mix commands", metavar="<command>")
    adjust = mix_cmds.add_parser("adjust", parents=[common], help="change the whole project's sound at once (relative changes)")
    adjust.add_argument("--brightness", type=float, default=0.0, help="dB of tilt to add: + brighter, - darker (e.g. 2)")
    adjust.add_argument("--warmth", type=float, default=0.0, help="dB of low-mid body to add (e.g. 2 warmer, -2 thinner)")
    adjust.add_argument("--room", type=float, default=0.0, help="reverb amount to add (e.g. 0.1 wetter, -0.1 drier)")
    adjust.add_argument("--crush", type=int, help="bit depth for a lo-fi sound (e.g. 8); 0 turns crushing off")
    adjust.add_argument("--loudness", type=float, default=0.0, help="LU to add to every loudness target (e.g. -2 quieter)")
    adjust.add_argument("--dry-run", action="store_true", help="show the changes without writing")
    adjust.set_defaults(handler=cmd_mix_adjust)

    mcp_cmd = commands.add_parser("mcp", help="run SEGAN as an MCP server over stdio (needs segan[mcp])")
    mcp_cmd.add_argument("--project", help="SEGAN project directory (default: the one containing the cwd)")
    mcp_cmd.add_argument("--allow-godot", action="store_true", help="let the build tool run a Godot binary (verify_godot)")
    mcp_cmd.set_defaults(handler=cmd_mcp)

    skill = commands.add_parser("skill", help="the Claude skill that teaches agents to use SEGAN")
    skill_cmds = skill.add_subparsers(title="skill commands", metavar="<command>")
    skill_install = skill_cmds.add_parser("install", parents=[common], help="install into <repo>/.claude/skills/segan/")
    skill_install.add_argument("dir", nargs="?", help="repo root (default: the git root containing the cwd)")
    skill_install.set_defaults(handler=cmd_skill_install)

    imp = commands.add_parser("import", help="convert other formats into SEGAN sources")
    imp_kinds = imp.add_subparsers(title="formats", metavar="<format>")
    imp_midi = imp_kinds.add_parser("midi", parents=[common], help="a standard MIDI file -> a song (quantized, snapped to the key and kit)")
    imp_midi.add_argument("file", help=".mid file")
    imp_midi.add_argument("--kit", help="kit to map the parts onto (default: the project's default_kit)")
    imp_midi.add_argument("--key", help='key, e.g. "A minor" (default: the key signature, else estimated from the notes)')
    imp_midi.add_argument("--quantize", type=int, default=16, help="grid: notes per whole note (default 16 = sixteenths)")
    imp_midi.add_argument("--bars-per-pattern", type=int, default=2, help="pattern length in bars (default 2)")
    imp_midi.add_argument("--no-loop", action="store_true", help="don't loop the song")
    imp_midi.add_argument("--name", help="song name (default: from the file name)")
    imp_midi.add_argument("--out", help="output path (default: music/<name>.song.yaml)")
    imp_midi.add_argument("--force", action="store_true", help="overwrite an existing file")
    imp_midi.set_defaults(handler=cmd_import_midi)

    kit = commands.add_parser("kit", help="kit tools")
    kit_cmds = kit.add_subparsers(title="kit commands", metavar="<command>")
    show = kit_cmds.add_parser("show", parents=[common], help="every instrument playing a test phrase: listen sheet + WAVs")
    show.add_argument("kits", nargs="*", help="kit names or .kit.yaml paths (default: all in the project)")
    show.set_defaults(handler=cmd_kit_show)

    config = commands.add_parser("config", help="project settings (mix, loudness, kit, ...): show, get, set")
    config_cmds = config.add_subparsers(title="config commands", metavar="<command>")
    config_show = config_cmds.add_parser("show", parents=[common], help="every setting: value, default, meaning")
    config_show.set_defaults(handler=cmd_config_show)
    config_get = config_cmds.add_parser("get", parents=[common], help="one setting's value")
    config_get.add_argument("key", help="e.g. mix.room")
    config_get.set_defaults(handler=cmd_config_get)
    config_set = config_cmds.add_parser("set", parents=[common], help="change a setting (validated, saved in segan.toml)")
    config_set.add_argument("key", help="e.g. mix.room")
    config_set.add_argument("value", help='TOML value, e.g. 0.3, true, "nes", ["wav", "godot"]')
    config_set.set_defaults(handler=cmd_config_set)
    config_unset = config_cmds.add_parser("unset", parents=[common], help="return a setting to its default")
    config_unset.add_argument("key", help="e.g. mix.room")
    config_unset.set_defaults(handler=cmd_config_unset)
    return parser


Handler = Callable[[argparse.Namespace, Output], int]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    out = Output(as_json=getattr(args, "json", False))
    progress.enabled = argv is None and not args.quiet and not os.environ.get("SEGAN_QUIET")
    try:
        return handler(args, out)
    except SeganError as exc:
        out.failure(exc.findings)
        return 1
