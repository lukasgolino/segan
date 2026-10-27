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
from segan.notes import note_name
from segan.patch import Instrument
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
    "orchestral": ("orchestra", "orchestral: sampled strings, brass, woodwinds, harp and timpani (VSCO 2 CE samples, CC0)"),
}


def _pagan_outputs(root: Path, godot_root: Path | None) -> list[tuple[Path, Path]]:
    """(pagan.toml, its output dir) for PAGAN projects at or above `root`, and anywhere in the Godot project
    (art often lives next to the sound folder, e.g. game/art/pagan.toml)."""
    import tomllib

    configs: list[Path] = []
    for directory in (root.resolve(), *root.resolve().parents):
        if (directory / "pagan.toml").is_file():
            configs.append(directory / "pagan.toml")
            break
    if godot_root is not None:
        top = godot_root.resolve()
        for config in sorted(top.glob("**/pagan.toml")):
            depth = len(config.relative_to(top).parts)
            if depth <= 4 and not any(part.startswith(".") for part in config.relative_to(top).parts) and config not in configs:
                configs.append(config)
    found = []
    for config in configs:
        try:
            theirs = tomllib.loads(config.read_text(encoding="utf-8")).get("output_dir", "build")
        except (OSError, ValueError):
            continue
        if isinstance(theirs, str):
            found.append((config, (config.parent / theirs).resolve()))
    return found


def _pagan_clash(root: Path, output_dir: str, godot_root: Path | None = None) -> Path | None:
    """A pagan.toml whose output_dir is ours, contains ours or sits inside ours: PAGAN and SEGAN would mix their files
    (both write manifest.json, and each build cleans up files it doesn't know)."""
    ours = (root / output_dir).resolve()
    for config, theirs in _pagan_outputs(root, godot_root):
        if ours == theirs or ours.is_relative_to(theirs) or theirs.is_relative_to(ours):
            return config
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
    rolled = style not in STYLES  # words: a kit rolled from the project seed
    kit_name, style_text = ("core", f"rolled from {style!r}") if rolled else STYLES[style]
    seed = int.from_bytes(os.urandom(7), "little") % (1 << 53)  # the project seed: suggestions and rolled kits branch from it
    config_text = Template(template("segan.toml")).substitute(mode=mode, default_kit=f'default_kit = "{kit_name}"')
    config_text = set_in_toml(config_text, "seed", seed)
    output_dir = "build/audio"
    moved_from_pagan: Path | None = None
    if godot_root is not None:
        target = godot_root / "assets" / "generated" / "audio"
        if (moved_from_pagan := _pagan_clash(root, os.path.relpath(target.resolve(), root.resolve()), godot_root)) is not None:
            target = godot_root / "assets" / "audio"  # PAGAN's output folder holds assets/generated: stay out of it
        output_dir = Path(os.path.relpath(target.resolve(), root.resolve())).as_posix()
        config_text = set_in_toml(config_text, "output_dir", output_dir)
        config_text = set_in_toml(config_text, "export", ["wav", "godot"])
    if style in ("chiptune", "synth"):  # a synthesised game: "auto" would use recordings for weapons and impacts
        config_text = set_in_toml(config_text, "sfx.source", "synth")
    if style == "orchestral":  # a hall, and an orchestra's worth of instruments per song
        config_text = set_in_toml(config_text, "mix.room", 0.3)
        config_text = set_in_toml(config_text, "mix.room_decay", 1.6)
        config_text = set_in_toml(config_text, "lint.max_instruments", 16)
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
        if rolled:
            from segan.suggest import roll_kit

            kit_path.write_text(roll_kit(kit_name, style, seed).yaml(), encoding="utf-8")
        else:
            kit_path.write_text(template(f"{kit_name}{KIT_SUFFIX}"), encoding="utf-8")
        created.append(kit_path)
    clash = _pagan_clash(root, output_dir, godot_root)

    out.say(f"Initialized SEGAN project in {display_path(root)} ({mode} mode, {'a kit rolled from ' + repr(style) if rolled else style + ' starter kit'} "
            f"'{kit_name}', project seed {seed})")  # fmt: skip
    for path in created:
        out.say(f"  created {display_path(path)}")
    for path in skipped:
        out.say(f"  kept existing {display_path(path)}")
    if moved_from_pagan is not None:
        out.say(f"  output_dir = {output_dir}: {display_path(moved_from_pagan)} builds into assets/generated, so the audio goes next to it, not inside it")
    if clash is not None:
        out.say(f"  warning: {display_path(clash)} writes to the same output_dir, or one inside the other; both tools write manifest.json "
                "and clean up files they don't know. Give each its own folder (e.g. assets/art and assets/audio).")  # fmt: skip
    from segan.kitshow import all_library_needs

    for library_name, needs in all_library_needs(kit_path).items():
        out.say(f"The kit plays sampled instruments: `segan samples fetch {library_name} {' '.join(needs)}` downloads them first.")
    out.say(f"Next: `segan kit show {kit_name}` and look at previews/kits/{kit_name}.listen.png; fill in BRIEF.md and SOUND.md.")
    out.result(
        {
            "project": display_path(root),
            "mode": mode,
            "style": style,
            "default_kit": kit_name,
            "seed": seed,
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


def cmd_samples_list(args: argparse.Namespace, out: Output) -> int:
    from segan import libraries
    from segan.samples import SampleError, sf2_presets

    target = args.target
    if target and target.lower().endswith(".sf2"):
        try:
            presets = sf2_presets(Path(target))
        except SampleError as exc:
            raise usage_error(str(exc)) from None
        for bank, program, name in presets:
            out.say(f"  bank {bank:3d} preset {program:3d}  {name}")
        out.result({"sf2": target, "presets": [{"bank": b, "preset": p, "name": n} for b, p, n in presets]})
        return 0
    result: list[dict[str, Any]] = []
    for name in [target] if target else libraries.names():
        try:
            lib = libraries.library(name)
        except libraries.LibraryError as exc:
            raise usage_error(str(exc)) from None
        out.say(f"{lib.name}: {lib.title} ({lib.license}; {lib.url}), cache {display_path(lib.cache)}")
        rows = []
        for inst, info in sorted(lib.instruments.items()):
            fetched = not lib.missing(inst)
            keys = lib.key_range(inst)
            span = [note_name(keys[0]), note_name(keys[1])] if keys is not None else None
            rows.append({"instrument": inst, "sample": f"{lib.name}/{inst}", "description": info["description"], "kind": info["kind"],
                         "range": span, "mb": round(lib.size(inst) / 1e6, 1), "fetched": fetched})  # fmt: skip
            shown = f"{span[0]}-{span[1]}" if span is not None else "unpitched"
            out.say(f"  {'*' if fetched else ' '} {inst:<15} {lib.size(inst) / 1e6:6.1f} MB  {shown:<9}  {info['description']}")
        out.say("  (* = downloaded; `segan samples fetch " + lib.name + " <instrument...>` gets the rest)")
        result.append({"library": lib.name, "title": lib.title, "license": lib.license, "url": lib.url, "cache": str(lib.cache), "instruments": rows})
    out.result({"libraries": result})
    return 0


def cmd_samples_fetch(args: argparse.Namespace, out: Output) -> int:
    from segan import libraries

    try:
        lib = libraries.library(args.library)
        wanted = sorted(lib.instruments) if args.all or not args.instruments else args.instruments
        if not args.all and not args.instruments:
            raise usage_error(f"name the instruments to fetch, or --all ({sum(lib.size(i) for i in wanted) / 1e6:.0f} MB): {', '.join(wanted)}")
        size = sum(lib.files[f][0] for f in {f for i in wanted if i in lib.instruments for f in lib.missing(i)})
        out.say(f"fetching {', '.join(wanted)} from {lib.repo}@{lib.pin} ({size / 1e6:.0f} MB to download, {lib.license}) into {display_path(lib.cache)}")
        count, fetched = libraries.fetch(lib, wanted, progress=lambda p: progress.note(f"got {p}"))
    except libraries.LibraryError as exc:
        raise usage_error(str(exc)) from None
    out.say(f"fetched {count} files ({fetched / 1e6:.0f} MB); use them as sample: {lib.name}/<instrument>")
    out.result({"library": lib.name, "instruments": wanted, "files": count, "bytes": fetched, "cache": str(lib.cache)})
    return 0


# --- segan sounds ------------------------------------------------------------------------------


def _sounds_error(exc: Exception) -> SeganError:
    return usage_error(str(exc))


def cmd_sounds_remove(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds

    project = require_project()
    try:
        entries = dict(sounds.read_lock(project.root))
    except sounds.SoundsError as exc:
        raise _sounds_error(exc) from None
    keys = [sounds.lock_key(ref, project.root) for ref in args.refs]
    if missing := [ref for ref, key in zip(args.refs, keys, strict=True) if key not in entries]:
        raise usage_error(f"not in sounds.lock: {', '.join(missing)} (entries: {', '.join(sorted(entries)) or 'none'})")
    used, _ = used_sounds(project)
    if (busy := {k: used[k] for k in keys if k in used}) and not args.force:
        raise usage_error("still played by " + "; ".join(f"{k}: {', '.join(v)}" for k, v in busy.items()) + " (change those SFX first, or --force)")
    for key in keys:
        entries.pop(key)
    sounds.write_lock(project.root, entries)
    out.say(f"removed {len(keys)} sounds from sounds.lock ({len(entries)} left); cached files stay in {display_path(sounds.cache_root())}")
    out.result({"removed": keys, "left": len(entries)})
    return 0


def cmd_sounds_prune(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds

    project = require_project()
    try:
        entries = dict(sounds.read_lock(project.root))
    except sounds.SoundsError as exc:
        raise _sounds_error(exc) from None
    if broken := broken_sfx(project):
        raise usage_error(f"{len(broken)} SFX don't parse ({', '.join(broken[:5])}): fix them first, or prune could drop sounds they play")
    used, _ = used_sounds(project)
    unused = sorted(k for k in entries if k not in used)
    if not args.dry_run and unused:
        sounds.write_lock(project.root, {k: v for k, v in entries.items() if k not in unused})
    out.say(("would drop " if args.dry_run else "dropped ") + (", ".join(unused) if unused else "nothing: every sound in sounds.lock is played"))
    out.result({"unused": unused, "dry_run": args.dry_run})
    return 0


def broken_sfx(project: Project) -> list[str]:
    """SFX files that don't parse (their recorded layers are unknown)."""
    from segan.asset import load_asset
    from segan.lint import source_files

    return [path.name for path in source_files(project, [project.sfx_dir]) if path.name.endswith(SFX_SUFFIX) and load_asset(path, project)[0] is None]


def used_sounds(project: Project) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """Recorded sounds the project's SFX play: {lock key: [sfx names]}, and what their layers say about the ones
    not in sounds.lock (licence, source, author)."""
    from segan.asset import load_asset
    from segan.lint import source_files
    from segan.sounds import lock_key

    used: dict[str, list[str]] = {}
    declared: dict[str, dict[str, Any]] = {}
    for path in source_files(project, [project.sfx_dir]):
        if not path.name.endswith(SFX_SUFFIX):
            continue
        asset, _ = load_asset(path, project)
        if asset is None:
            continue
        layers = [*asset.layers, *(layer for phase in asset.phases.values() for layer in phase.layers)]
        for layer in layers:
            for sound in layer.recorded:
                key = lock_key(sound.ref, project.root)
                names = used.setdefault(key, [])
                if asset.name not in names:
                    names.append(asset.name)
                declared.setdefault(key, {k: v for k, v in (("name", sound.name or Path(sound.ref).stem), ("author", sound.author),
                                                            ("licence", sound.licence), ("source", sound.source)) if v})  # fmt: skip
    return used, declared


def cmd_sounds_search(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds

    licences = tuple(dict.fromkeys(args.licence or ["cc0", "cc-by"]))
    try:
        found = sounds.search(args.query, args.max_seconds, licences, args.limit, args.sort)
    except sounds.SoundsError as exc:
        raise _sounds_error(exc) from None
    rows = [{k: v for k, v in row.items() if k not in ("previews", "licence_given")} for row in found["results"]]
    out.say(f"{found['count']} matches on Freesound ({', '.join(licences)}); showing {len(rows)}" + (f", {found['refused']} refused (licence)" if found["refused"] else ""))
    for row in rows:
        out.say(f"  {row['ref']:<17} {row['duration']:6.2f}s  {row['licence']:<10} {row['rating']:.1f}*({row['ratings']:>3})  {row['author']}: {row['name']}")
        if row["tags"]:
            out.say(f"  {'':<17} tags: {' '.join(row['tags'][:12])}")
    if rows:
        out.say("Compare with `segan sounds inspect <ref>`; keep one with `segan sounds add <ref>`.")
    out.result({"query": args.query, "count": found["count"], "refused": found["refused"], "results": rows})
    return 0


def cmd_sounds_add(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds

    project = require_project()
    try:
        key, entry = sounds.add(args.ref, project.root, args.format, args.licence, args.source, args.author, args.name)
    except sounds.SoundsError as exc:
        raise _sounds_error(exc) from None
    out.say(f"added {key}: {entry['name']!r}" + (f" by {entry['author']}" if entry.get("author") else "") + f", {entry['licence']} -> {sounds.LOCK_NAME}")
    out.say(f"use it in an SFX layer as sample: {key}" + ("  (CC BY: `segan sounds credits` writes the attribution)" if entry["licence"].startswith("CC-BY") else ""))
    out.result({"ref": key, "entry": entry, "lock": str(project.root / sounds.LOCK_NAME)})
    return 0


def _sound_file(ref: str, root: Path) -> tuple[Path, dict[str, Any] | None]:
    """The file to inspect: a locked or local sound, or a Freesound sound fetched into the cache (not locked)."""
    from segan import sounds

    sound_id = sounds.freesound_id(ref)
    entry = sounds.lock_entry(root, ref)
    if sound_id is not None and entry is None:
        path, row, _ = sounds.fetch_freesound(sound_id)
        return path, {k: row[k] for k in ("name", "author", "licence", "url")}
    if sound_id is None and not (root / ref).is_file() and Path(ref).is_file():
        return Path(ref).resolve(), entry
    return sounds.resolve(ref, root), entry


def cmd_sounds_inspect(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds
    from segan.recorded import inspect
    from segan.samples import SampleError

    root = find_project_root(Path.cwd()) or Path.cwd()
    results = []
    for ref in args.refs:
        try:
            path, entry = _sound_file(ref, root)
            info = inspect(str(path))
        except (sounds.SoundsError, SampleError) as exc:
            raise _sounds_error(exc) from None
        info = {"ref": ref, **info, **({"about": entry} if entry else {})}
        results.append(info)
        pitch = info["pitch"]
        pitch_text = f"{pitch['note']}{pitch['cents']:+d}c ({pitch['hz']} Hz, voiced {pitch['voiced']:.0%})" if isinstance(pitch, dict) else "none (noisy/unpitched)"
        onsets = info["onsets_s"]
        assert isinstance(onsets, list)
        out.say(f"{ref}: {info['seconds']}s @ {info['sample_rate']} Hz, peak {info['peak_dbfs']} dBFS, {info['lufs_max_momentary']} LUFS (max momentary), "
                f"centroid {info['centroid_hz']:.0f} Hz, pitch {pitch_text}, {len(onsets)} onsets" + (f" at {', '.join(f'{t:g}' for t in onsets[:8])}s" if onsets else ""))  # fmt: skip
    out.result({"sounds": results})
    return 0


def cmd_sounds_credits(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds

    project = require_project()
    try:
        entries = dict(sounds.read_lock(project.root))
    except sounds.SoundsError as exc:
        raise _sounds_error(exc) from None
    used, declared = used_sounds(project)
    for key, meta in declared.items():
        entries.setdefault(key, meta)
    target = Path(args.out) if args.out else project.root / "SOUND_CREDITS.md"
    from segan.licences import project_extras

    text = sounds.credits_text(entries, used, project_extras(project.root))
    target.write_text(text, encoding="utf-8")
    need = sorted(k for k, v in entries.items() if str(v.get("licence", "")).startswith("CC-BY"))
    out.say(f"wrote {display_path(target)}: {len(entries)} sounds, {len(need)} need attribution (CC BY): ship it with the game's credits")
    out.result({"written": display_path(target), "sounds": len(entries), "attribution_required": need, "unused": sorted(set(entries) - set(used))})
    return 0


def cmd_sounds_vendor(args: argparse.Namespace, out: Output) -> int:
    from segan import sounds

    project = require_project()
    try:
        refs = list(sounds.read_lock(project.root)) if args.all else list(used_sounds(project)[0])
        copied = sounds.vendor(project.root, refs)
    except sounds.SoundsError as exc:
        raise _sounds_error(exc) from None
    for ref, path in copied:
        out.say(f"copied {ref} -> {display_path(path)}")
    out.say(f"{len(copied)} copied into {sounds.VENDOR_DIR}/ (builds use these before the cache); commit them for offline builds")
    out.result({"copied": [{"ref": ref, "path": display_path(path)} for ref, path in copied]})
    return 0


def _instrument_range(inst: Instrument) -> list[str] | None:
    """The notes an instrument plays: its `range`, else (samples) the keys its zones map; None = any / unpitched."""
    if inst.range is not None:
        return [note_name(inst.range[0]), note_name(inst.range[1])]
    if inst.sample is not None and not inst.is_drum:
        from segan.samples import load_set

        sset = load_set(inst.sample)
        low, high = sset.key_span()
        if (low, high) != (0, 127):
            return [note_name(low), note_name(high)]
    return None


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
            k: {"name": i.name, "source": i.describe(), "range": _instrument_range(i),
                "aliasing_db": None if (a := show.aliasing.get(k)) is None else round(a, 1)}
            for k, i in kit.instruments.items()
        }  # fmt: skip
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


def _meter(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2})/(2|4|8|16)", text.strip())
    if match is None or not 1 <= int(match.group(1)) <= 16:
        raise usage_error(f"invalid --meter {text!r}: beats/unit, e.g. 4/4, 3/4, 6/8, 7/8")
    return int(match.group(1)), int(match.group(2))


def song_plan(project: Project, name: str, words: str, take: int = 0) -> dict[str, Any]:
    """`segan suggest song`'s plan for a new song in this project (seeded by the project seed)."""
    from segan import similarity
    from segan.suggest import suggest_song
    from segan.yamlio import load_yaml

    songs = project_songs(project) if project.config_path is not None else {}
    prints = [similarity.fingerprint(s, str(project.root)) for n, s in songs.items() if n != name]
    kits: dict[str, Any] = {}
    for kit_name in project.kit_names():
        try:
            data = load_yaml(project.kit_path(kit_name))
        except Exception:  # noqa: BLE001 - a broken kit just isn't offered
            continue
        if isinstance(data, dict):
            kits[kit_name] = data
    return suggest_song(name, words, project_seed(project), prints, kits, take)


def project_seed(project: Project) -> int:
    """The project seed from segan.toml, else one derived from the project folder's name (older projects)."""
    from segan.dsp import seed_of

    return project.config.seed if project.config.seed is not None else seed_of("project", project.root.name) % (1 << 62)


def _song_scaffold(name: str, description: str, kit_line: str, kit: Kit | None, key_text: str, tempo: int, bars: int, style: int,
                   meter: tuple[int, int] = (4, 4)) -> str:  # fmt: skip
    from segan.notes import parse_key

    key = parse_key(key_text)
    if key is None:
        raise usage_error(f"invalid --key {key_text!r}: a root and a scale, e.g. 'A minor', 'C major', 'D dorian'")
    steps_per_beat = 2 if meter[1] >= 8 else 4
    beat = steps_per_beat
    length = bars * meter[0] * steps_per_beat
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
        cells = "|".join(["." * beat] * (length // beat))
        return "".join(f"      {cells}  {label}\n" for label in labels)

    return f"""name: {name}
description: {json.dumps(description)}
{kit_line.rstrip()}
tempo: {tempo}
meter: [{meter[0]}, {meter[1]}]
steps_per_beat: {steps_per_beat}             # 16th-note grid; `|` (ignored) marks each beat
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
        key, tempo, meter = args.key, args.tempo, _meter(args.meter) if args.meter else None
        if key is None or tempo is None:  # not given: the seeded suggestion, away from the project's songs
            plan = song_plan(project, name, args.description or "")
            key, tempo = key or plan["key"], tempo or plan["tempo"]
            meter = meter or (int(plan["meter"][0]), int(plan["meter"][1]))
            out.say(f"{key}, {tempo} bpm, {meter[0]}/{meter[1]} (suggested away from the project's songs; `segan suggest song {name}` adds an opening, "
                    "texture and progression)")  # fmt: skip
        meter = meter or (4, 4)
        text = _song_scaffold(name, description, kit_line, kit, key, tempo, args.bars, style, meter)
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
        ids = []
        for output in render.outputs:
            if args.output and not {output.id or "main", output.stem} & set(args.output):
                continue
            path = folder / f"{output.stem.replace('/', '.')}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(output.wav())
            written.append(display_path(path))
            ids.append({"output": output.id or "main", "wav": display_path(path), "seconds": round(output.seconds, 4),
                        **({"loop": {"start": output.loop[0], "end": output.loop[1]}} if output.loop else {})})  # fmt: skip
        out.say(f"{asset.name}: wrote {len(written)} WAVs to {display_path(folder)}")
        outputs.append({"asset": asset.name, "files": written, "outputs": ids})
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
    if args.format is not None:
        from segan import oggio

        if not oggio.available() or (args.format == "mp3" and not oggio.mp3_available()):
            raise usage_error(f'--format {args.format} needs soundfile with a libsndfile that writes it: pip install "segan[ogg]"'
                              + (" (MP3 needs libsndfile 1.1 or newer)" if args.format == "mp3" else ""))
    assets, findings = load_targets(args.assets, project)
    outputs: list[dict[str, Any]] = []
    summary: list[dict[str, Any]] = []  # one flat row per output (--summary)
    for asset in assets:
        render = render_asset(asset, project)
        result = write_preview(asset, render, project, _position(args.start, asset), _position(args.end, asset), args.output, args.format)
        walks = asset.kind == "song" and asset.flow is not None
        missing = [o for o in args.output or [] if not any(o in (r.id or "main", r.stem) for r in render.outputs)
                   and not (walks and o.split(":")[0] == "walk") and not (asset.kind == "sfx" and o == "reel")]  # fmt: skip
        if missing or not result.files:
            raise usage_error(f"{asset.name} has no output {', '.join(map(repr, missing or args.output or []))} (outputs: {', '.join(o.id or 'main' for o in render.outputs)})")
        for entry in result.files:
            a = entry["analysis"]
            tail = a.get("room_tail_s")
            summary.append({"asset": asset.name, "output": entry["output"], "seconds": a["seconds"],
                            "dry_s": round(a["seconds"] - tail, 3) if tail is not None else None, "lufs": a["lufs"],
                            "target_lufs": a.get("target_lufs"), "peak_dbfs": a["peak_dbfs"], "true_peak_dbtp": a["true_peak_dbtp"]})  # fmt: skip
            if args.summary:
                continue
            target = f" (target {a['target_lufs']:g})" if a.get("target_lufs") is not None else ""
            out.say(f"{entry['output']:>16}: {display_path(entry['sheet'])}  {a['seconds']:.2f}s, {a['lufs']:.1f} LUFS{target}, peak {a['true_peak_dbtp']:.1f} dBTP")
            out.say(f"{'':>16}  listen: {display_path(entry['wav'])}" + (f"  seam: {display_path(entry['seam'])} (click {a['seam_click']:.4f})" if "seam" in entry else ""))
        outputs.append({"asset": asset.name, "kind": asset.kind, "outputs": [
            {"output": e["output"], "wav": display_path(e["wav"]), "sheet": display_path(e["sheet"]),
             **({"seam": display_path(e["seam"])} if "seam" in e else {}), **({k: display_path(e[k]) for k in ("ogg", "mp3") if k in e}),
             "analysis": e["analysis"]} for e in result.files]})  # fmt: skip
    extra: dict[str, Any] = {"summary": summary} if args.summary else {}
    if args.summary and not out.as_json:
        print(_summary_table(summary))
    if findings:
        out.failure(findings, {"outputs": outputs, **extra})
        return 1
    if not out.as_json:
        print("Open the .listen.png sheets to check them; a human has to listen to the WAVs before approving.")
    out.result({"outputs": outputs, **extra})
    return 0


def _summary_table(rows: list[dict[str, Any]]) -> str:
    """`segan preview --summary`: asset, output, seconds, dry seconds, LUFS (target), peaks as aligned columns."""

    def num(value: Any, digits: int) -> str:
        return "-" if value is None else f"{value:.{digits}f}"

    table = [("asset", "output", "seconds", "dry", "LUFS", "target", "peak", "true peak")]
    table += [(r["asset"], r["output"], num(r["seconds"], 3), num(r["dry_s"], 3), num(r["lufs"], 1), num(r["target_lufs"], 1),
               num(r["peak_dbfs"], 1), num(r["true_peak_dbtp"], 1)) for r in rows]  # fmt: skip
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    return "\n".join("  ".join(c.ljust(w) if i < 2 else c.rjust(w) for i, (c, w) in enumerate(zip(row, widths))).rstrip() for row in table)


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


# --- segan similarity -------------------------------------------------------------------------


def project_songs(project: Project) -> dict[str, Any]:
    """Every song of the project that parses, by name."""
    from segan.lint import _project_assets

    return {name: song for name, song in _project_assets(project, [], "song").items() if not song.meta.template}


def cmd_similarity(args: argparse.Namespace, out: Output) -> int:
    from segan import similarity as sim

    project = project_for(args.songs)
    songs = project_songs(project)
    wanted = [Path(s).name.removesuffix(SONG_SUFFIX) if s.endswith(SONG_SUFFIX) else s for s in args.songs]
    if missing := [w for w in wanted if w not in songs]:
        raise usage_error(f"no song {', '.join(map(repr, missing))} in this project (songs: {', '.join(songs) or 'none'})")
    prints = {name: sim.fingerprint(song, str(project.root)) for name, song in songs.items()}
    if project.config.similarity.local_store and project.config_path is not None:
        sim.save_local(project.root, list(prints.values()))
    focus = wanted or list(prints)
    pairs = [sim.compare(prints[a], prints[b]) for a in focus for b in prints if b != a and (b not in focus or a < b)]
    if args.shipped:
        pairs += [sim.compare(prints[a], other) for a in focus for other in sim.shipped()]
    if args.machine:
        pairs += [sim.compare(prints[a], other) for a in focus for other in sim.other_projects(project.root)]
    pairs.sort(key=lambda s: (-s.overall, s.a, s.b))
    limit = project.config.lint.max_similarity
    closest: dict[str, dict[str, Any]] = {}
    for pair in pairs:
        for me, other in ((pair.a, pair.b), (pair.b, pair.a)):
            if me in focus and me not in closest:
                closest[me] = {"song": other, "overall": round(pair.overall, 3), "opening": round(sim.opening_score(pair), 3)}
    shown = pairs[: args.top]
    if not pairs:
        out.say("fewer than two songs: nothing to compare")
    else:
        out.say(f"{'pair':<40} {'overall':>7} {'harmony':>7} {'rhythm':>6} {'timbre':>6} {'register':>8} {'tempo':>5}  notes")
        for p in shown:
            notes = ", ".join(n for n, flag in (("same opening", p.same_opening), ("same pitch set", p.same_pitch_set),
                                                (f"first bars over {limit:g}", sim.opening_score(p) >= limit)) if flag)  # fmt: skip
            parts = p.parts
            out.say(f"{p.a + ' ~ ' + p.b:<40} {p.overall:7.2f} {parts['harmony']:7.2f} {parts['rhythm']:6.2f} {parts['timbre']:6.2f} "
                    f"{parts['register']:8.2f} {parts['tempo']:5.2f}  {notes}")  # fmt: skip
        out.say("1 = the same; lint warns (W024) when two songs' first bars score over lint.max_similarity")
    out.result({"songs": list(prints), "pairs": [p.to_dict() | {"opening_score": round(sim.opening_score(p), 3)} for p in shown],
                "closest": closest, "max_similarity": limit})  # fmt: skip
    return 0


# --- segan suggest / kit roll -----------------------------------------------------------------


def cmd_suggest_song(args: argparse.Namespace, out: Output) -> int:
    project = require_project()
    if not NAME_RE.match(args.name):
        raise usage_error(f"invalid name {args.name!r}: use lowercase letters, digits, '_' or '-'")
    plan = song_plan(project, args.name, args.mood or "", args.take)
    opening = plan["opening"]
    out.say(f"{plan['name']}: {plan['key']}, {plan['tempo']} bpm, {plan['meter'][0]}/{plan['meter'][1]}" + (f" ({plan['mood']})" if plan["mood"] else ""))
    out.say(f"  texture:     {plan['texture']} - {plan['texture_hint']}")
    out.say(f"  progression: {plan['progression']}")
    out.say(f"  opening:     {' '.join(opening['notes'])} ({opening['degree']}, {opening['inversion']}, {opening['spread']}, {opening['register']} register)")
    inst = plan["instruments"]
    if inst:
        out.say(f"  kit {inst['kit']}: identity {', '.join(inst['identity']) or '(no identity group)'}; extras {', '.join(inst['extras']) or 'none'}")
        if "new_instrument" in inst:
            out.say(f"  try a new instrument: {inst['new_instrument']['name']}: {json.dumps(inst['new_instrument']['patch'])}")
    for reason in plan["why"]:
        out.say(f"  ({reason})")
    out.say(f"  seed: {plan['seed']} (the song's own; another take: --take {args.take + 1})")
    out.say(f"next: {plan['command']}")
    out.result({"plan": plan})
    return 0


def cmd_kit_roll(args: argparse.Namespace, out: Output) -> int:
    from segan.suggest import roll_kit
    from segan.yamlio import load_yaml

    project = require_project()
    if not NAME_RE.match(args.name):
        raise usage_error(f"invalid kit name {args.name!r}: use lowercase letters, digits, '_' or '-'")
    around = None
    if args.around:
        if not project.kit_path(args.around).is_file():
            raise usage_error(f"--around: no kit {args.around!r} (kits: {', '.join(project.kit_names()) or 'none'})")
        data = load_yaml(project.kit_path(args.around))
        around = data if isinstance(data, dict) else None
    rolled = roll_kit(args.name, args.style, project_seed(project), around, args.samples, args.take)
    text = rolled.yaml()
    path = project.kit_path(args.name)
    if not args.dry_run:
        if path.exists() and not args.force:
            raise usage_error("kit already exists (--force replaces it, --dry-run only prints)", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        load_kit_file(path)  # what was written must be a valid kit
        out.say(f"wrote {display_path(path)}")
    if not out.as_json:
        print(text, end="")
    for library_name in sorted({entry.split("/")[0] for entry in rolled.libraries}):
        wanted = [entry.split("/")[1] for entry in rolled.libraries if entry.startswith(library_name + "/")]
        out.say(f"it plays sampled instruments: `segan samples fetch {library_name} {' '.join(wanted)}` first")
    out.say(f"next: `segan kit show {args.name}`; another take: --take {args.take + 1}")
    out.result({"kit": args.name, "path": None if args.dry_run else display_path(path), "text": text, "identity": rolled.identity,
                "libraries": rolled.libraries, "seed": rolled.seed})  # fmt: skip
    return 0


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
    common.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS, help="no progress lines on stderr")

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
    init.add_argument("--style", help='starter kit: chiptune (default), synth or orchestral (sampled; needs `segan samples fetch`), or words for the '
                      'game\'s sound ("cold ship, warm crew") to roll a kit `core` from the project seed')  # fmt: skip
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
    new_song.add_argument("--key", help='key, e.g. "A minor", "C major", "D dorian" (default: suggested away from the project\'s songs)')
    new_song.add_argument("--tempo", type=int, help="bpm (default: suggested away from the project's songs)")
    new_song.add_argument("--meter", help="beats/unit, e.g. 4/4, 3/4, 6/8 (default: suggested)")
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
    render.add_argument("--output", action="append", help="only these outputs (main, stem:T, mix:M, variant:X...); renders are cached, no analysis")
    render.set_defaults(handler=cmd_render)

    preview = commands.add_parser("preview", parents=[common], help="WAVs + listen sheets (+ seam views for loops) and the numbers to check")
    preview.add_argument("assets", nargs="+", help="asset files or names")
    preview.add_argument("--from", dest="start", help="start of the shown window: bar number (songs) or seconds (2.5s)")
    preview.add_argument("--to", dest="end", help="end of the shown window")
    preview.add_argument("--format", choices=("ogg", "mp3"), help="also write each preview as .ogg or .mp3 (to share; needs segan[ogg])")
    preview.add_argument("--output", action="append", help="only this output (repeat for several; one render): main, variant:<name>, variation:<n>, "
                         "phase:<name>, stem:<name>, mix:<name>, flow:<clip>, walk (a flow song: a seeded walk through its sections; walk:<seed>), "
                         "reel (an SFX: the main sound and every variation back to back)")  # fmt: skip
    preview.add_argument("--summary", action="store_true", help="one flat table row per output: asset, output, seconds, dry, LUFS, target, "
                         "peak, true peak (--json: a flat `summary` list next to `outputs`)")  # fmt: skip
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
    lint.add_argument("-j", "--jobs", type=int, help="render songs/SFX in N processes (default: SEGAN_JOBS, else the CPU count up to 8)")
    lint.set_defaults(handler=cmd_lint)

    build_cmd = commands.add_parser("build", parents=[common], help="lint, then write WAVs, manifest.json and engine files to output_dir")
    build_cmd.add_argument("project", nargs="?", help="project directory (default: the one containing the cwd)")
    build_cmd.add_argument("--verify-godot", action="store_true", help="load and play every generated stream in headless Godot")
    build_cmd.add_argument("-j", "--jobs", type=int, help="render songs/SFX in N processes (default: SEGAN_JOBS, else the CPU count up to 8)")
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

    samples = commands.add_parser("samples", help="sample libraries (orchestral instruments) and SoundFonts")
    samples_cmds = samples.add_subparsers(title="samples commands", metavar="<command>")
    samples_list = samples_cmds.add_parser("list", parents=[common], help="library instruments (and what's downloaded), or a .sf2's presets")
    samples_list.add_argument("target", nargs="?", help="a library name (default: all) or a .sf2 file")
    samples_list.set_defaults(handler=cmd_samples_list)
    samples_fetch = samples_cmds.add_parser("fetch", parents=[common], help="download library instruments (pinned, checked) into the user cache")
    samples_fetch.add_argument("library", help="library name, e.g. vsco2")
    samples_fetch.add_argument("instruments", nargs="*", help="instrument names (see `segan samples list`)")
    samples_fetch.add_argument("--all", action="store_true", help="every instrument in the library")
    samples_fetch.set_defaults(handler=cmd_samples_fetch)

    snd = commands.add_parser("sounds", help="recorded sounds for SFX: Freesound search, sounds.lock, credits")
    snd_cmds = snd.add_subparsers(title="sounds commands", metavar="<command>")
    snd_search = snd_cmds.add_parser("search", parents=[common], help="search Freesound (needs FREESOUND_API_KEY); only CC0 / CC BY")
    snd_search.add_argument("query", help='what to find, e.g. "lion roar"')
    snd_search.add_argument("--max-seconds", type=float, help="only sounds up to this long")
    snd_search.add_argument("--licence", "--license", action="append", choices=["cc0", "cc-by"], help="only this licence (repeat for both; default both)")
    snd_search.add_argument("--limit", type=int, default=15, help="results to show (default 15, at most 150)")
    snd_search.add_argument("--sort", default="score", choices=["score", "rating_desc", "downloads_desc", "duration_asc", "duration_desc", "created_desc"],
                            help="order (default: relevance)")  # fmt: skip
    snd_search.set_defaults(handler=cmd_sounds_search)
    snd_add = snd_cmds.add_parser("add", parents=[common], help="record a sound in sounds.lock (freesound:<id> is fetched into the user cache)")
    snd_add.add_argument("ref", help="freesound:<id>, or a sound file in the project")
    snd_add.add_argument("--format", choices=["ogg", "mp3"], default="ogg", help="Freesound preview to fetch (default: HQ ogg)")
    snd_add.add_argument("--licence", "--license", help="a local file's licence: CC0 or CC-BY-4.0 (or its creativecommons.org URL)")
    snd_add.add_argument("--source", help='a local file\'s origin: the page it came from, or "own recording"')
    snd_add.add_argument("--author", help="a local file's author (required for CC BY)")
    snd_add.add_argument("--name", help="title for the credits (default: Freesound's name or the file name)")
    snd_add.set_defaults(handler=cmd_sounds_add)
    snd_inspect = snd_cmds.add_parser("inspect", parents=[common], help="length, loudness, peak, brightness, pitch and onsets of sounds")
    snd_inspect.add_argument("refs", nargs="+", help="freesound:<id> (fetched into the cache if needed) or sound files")
    snd_inspect.set_defaults(handler=cmd_sounds_inspect)
    snd_credits = snd_cmds.add_parser("credits", parents=[common], help="write the attribution file (CC BY needs it) from sounds.lock")
    snd_credits.add_argument("--out", help="output file (default: SOUND_CREDITS.md in the project)")
    snd_credits.set_defaults(handler=cmd_sounds_credits)
    snd_remove = snd_cmds.add_parser("remove", parents=[common], help="drop sounds from sounds.lock (refused while an SFX still plays them)")
    snd_remove.add_argument("refs", nargs="+", help="freesound:<id> or the local file, as in sounds.lock")
    snd_remove.add_argument("--force", action="store_true", help="drop them even if an SFX plays them (lint then reports E019/E020)")
    snd_remove.set_defaults(handler=cmd_sounds_remove)
    snd_prune = snd_cmds.add_parser("prune", parents=[common], help="drop every sounds.lock entry no SFX plays")
    snd_prune.add_argument("--dry-run", action="store_true", help="list them, change nothing")
    snd_prune.set_defaults(handler=cmd_sounds_prune)
    snd_vendor = snd_cmds.add_parser("vendor", parents=[common], help="copy the Freesound sounds in use into <project>/sounds/ (offline builds)")
    snd_vendor.add_argument("--all", action="store_true", help="every sound in sounds.lock, used or not")
    snd_vendor.set_defaults(handler=cmd_sounds_vendor)

    similar = commands.add_parser("similarity", parents=[common], help="how alike the project's songs are (harmony, rhythm, timbre, register, tempo)")
    similar.add_argument("songs", nargs="*", help="songs to compare with the rest (default: every pair)")
    similar.add_argument("--shipped", action="store_true", help="also compare with SEGAN's own examples and templates")
    similar.add_argument("--machine", action="store_true", help="also compare with songs from other projects on this machine ([similarity] local_store)")
    similar.add_argument("--top", type=int, default=15, help="pairs to show (default 15)")
    similar.set_defaults(handler=cmd_similarity)

    suggest = commands.add_parser("suggest", help="seeded proposals for new sources, away from what the project already uses")
    suggest_kinds = suggest.add_subparsers(title="what", metavar="<what>")
    suggest_song = suggest_kinds.add_parser("song", parents=[common], help="key, mode, tempo, meter, texture, opening voicing, progression, instruments")
    suggest_song.add_argument("name", help="the new song's name")
    suggest_song.add_argument("--mood", help='words for the song, e.g. "tense boss fight" or "quiet night town"')
    suggest_song.add_argument("--take", type=int, default=0, help="another proposal for the same song (0, 1, 2...)")
    suggest_song.set_defaults(handler=cmd_suggest_song)

    kit = commands.add_parser("kit", help="kit tools")
    kit_cmds = kit.add_subparsers(title="kit commands", metavar="<command>")
    roll = kit_cmds.add_parser("roll", parents=[common], help="a new kit from style words and the project seed (identity group + bass, harmony, colour, drums)")
    roll.add_argument("name", help="kit name")
    roll.add_argument("--style", required=True, help='words, e.g. "cold ship, warm crew" or "dusty lo-fi jazz"')
    roll.add_argument("--around", metavar="KIT", help="keep this kit's identity instruments and roll the rest around them")
    roll.add_argument("--samples", action=argparse.BooleanOptionalAction, default=None,
                      help="allow sampled library instruments (default: when the style asks for acoustic/orchestral sounds)")  # fmt: skip
    roll.add_argument("--take", type=int, default=0, help="another kit for the same words (0, 1, 2...)")
    roll.add_argument("--dry-run", action="store_true", help="print the kit, don't write it")
    roll.add_argument("--force", action="store_true", help="replace an existing kit file")
    roll.set_defaults(handler=cmd_kit_roll)
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
    import faulthandler
    import sys

    if argv is None and sys.stderr is not None:
        faulthandler.enable()  # a crash in a native library (libsndfile, numpy) prints where, instead of a silent exit 139
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    out = Output(as_json=getattr(args, "json", False))
    if getattr(args, "jobs", None) is not None:
        if args.jobs < 1:
            parser.error("--jobs must be 1 or more")
        os.environ["SEGAN_JOBS"] = str(args.jobs)  # read by the render pool (and its worker processes)
    progress.enabled = argv is None and not getattr(args, "quiet", False) and not os.environ.get("SEGAN_QUIET")
    try:
        return handler(args, out)
    except SeganError as exc:
        out.failure(exc.findings)
        return 1
