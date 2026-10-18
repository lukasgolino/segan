"""Command-line interface for SEGAN (same shape and conventions as PAGAN's: `--json` on every command,
non-zero exit on errors, the project found from the target path)."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from segan import progress
from segan.buildinfo import version_string
from segan.findings import Finding, SeganError, display_path
from segan.kit import KIT_SUFFIX, NAME_RE, Kit, load_kit_file
from segan.project import CONFIG_NAME, Project, discover_project, find_project_root, load_project
from segan.settings import Change, describe, lookup, set_in_toml, set_setting, unset_setting


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
