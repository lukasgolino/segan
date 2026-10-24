"""`segan mcp`: SEGAN as an MCP server, for agents without the Claude skill or a shell.

Adapted from PAGAN's mcp_server.py. One server serves one SEGAN project. Tools return the same JSON as the
matching CLI command with `--json` (they run the CLI handlers with stdout captured, cwd pinned, one lock), so the
CLI, the skill and MCP share one contract. Errors are results (`ok: false` + `findings`), not exceptions.
Nothing reads or writes outside the project, its output dir and its preview dir. Listen sheets come back as
images (the model can look at them); WAVs as audio content when asked (for clients and humans).

Needs the optional extra: `pip install "segan[mcp]"`.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import threading
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import date
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeVar

from mcp.server.mcpserver import Audio, Image, MCPServer
from mcp.types import ToolAnnotations
from PIL import Image as PILImage

from segan import __version__
from segan.asset import SFX_SUFFIX, SONG_SUFFIX
from segan.findings import Finding, SeganError
from segan.kit import KIT_SUFFIX, NAME_RE
from segan.lint import lint_paths
from segan.project import CONFIG_NAME, Project, find_project_root, load_project

MAX_SOURCE_BYTES = 2_000_000
MAX_IMAGE_SIDE = 1568
MAX_IMAGE_BYTES = 1_500_000
MAX_AUDIO_BYTES = 8_000_000
Kind = Literal["song", "sfx"]
KINDS: dict[Kind, tuple[str, str]] = {"song": ("music", SONG_SUFFIX), "sfx": ("sfx", SFX_SUFFIX)}
DOCS = ("BRIEF.md", "SOUND.md")

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
ONLINE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
FETCH = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
OVERWRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """\
SEGAN turns text into game audio: instrument kits, songs (step grids) and SFX (synth layers, recordings) written as YAML,
linted, previewed as listen sheets and built into WAVs + engine resources. Read segan://workflow first (notation:
segan://reference). Call `status` and `read_docs` (BRIEF.md, SOUND.md) before making anything.
Loop: `scaffold` -> `write_asset` (lints it, returns the listen sheet) -> fix findings -> `preview` and LOOK at the
sheet and numbers -> report. You can't hear: a human approves every sound (status stays draft until then).
Never invent instruments: songs use the project's kits. `build` writes the game's files; only after approval.
"""

P = ParamSpec("P")
R = TypeVar("R")


def _failure(findings: list[Finding]) -> dict[str, Any]:
    return {"ok": False, "findings": [f.to_dict() for f in findings]}


def _error(message: str, path: Path | None = None) -> SeganError:
    return SeganError([Finding("E000", message, path)])


def _results(fn: Callable[P, R]) -> Callable[P, R | dict[str, Any]]:
    """Turn a SeganError into an `ok: false` result with findings."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except SeganError as exc:
            return _failure(exc.findings)

    return wrapper


class Segan:
    """The project a server is bound to, and safe access to it."""

    def __init__(self, root: Path, allow_godot: bool = False) -> None:
        self.root = root.resolve()
        self.allow_godot = allow_godot
        self._lock = threading.Lock()  # the CLI uses the cwd and stdout, which are per process

    def project(self) -> Project:
        return load_project(self.root)  # fresh: files change between calls

    def cli(self, *argv: str) -> dict[str, Any]:
        """Run `segan --json <argv>` in the project and return its JSON result."""
        from segan.cli import main

        buffer = io.StringIO()
        with self._lock:
            previous = os.getcwd()
            os.chdir(self.root)
            try:
                with redirect_stdout(buffer):
                    code = main(["--json", *argv])
            except SystemExit as exc:  # argparse rejected the arguments
                return _failure([Finding("E000", f"invalid arguments for `segan {' '.join(argv)}` (exit {exc.code})")])
            finally:
                os.chdir(previous)
        text = buffer.getvalue().strip()
        try:
            data = json.loads(text) if text else {"ok": code == 0}
        except ValueError:
            data = {"ok": code == 0, "output": text}
        if not isinstance(data, dict):
            data = {"ok": code == 0, "result": data}
        return data

    def allowed_roots(self) -> list[Path]:
        project = self.project()
        return [self.root, project.output_dir.resolve(), project.preview_dir.resolve()]

    def inside(self, path: str | Path) -> Path:
        resolved = (self.root / path).resolve()
        if not any(resolved == r or resolved.is_relative_to(r) for r in self.allowed_roots()):
            raise _error(f"{path} is outside the SEGAN project")
        return resolved

    def source_path(self, kind: Kind, name: str) -> Path:
        _check_name(name)
        folder, suffix = KINDS[kind]
        return self.root / folder / f"{name}{suffix}"

    def find_asset(self, name: str) -> Path:
        _check_name(name)
        for folder, suffix in KINDS.values():
            path = self.root / folder / f"{name}{suffix}"
            if path.is_file():
                return path
        raise _error(f"no asset {name!r} (music/ or sfx/); `status` lists them")

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix() if path.resolve().is_relative_to(self.root) else str(path)


def _check_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise _error(f"invalid name {name!r}: lowercase letters, digits, '_' or '-'")


def _check_text(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise _error(f"source text is over {MAX_SOURCE_BYTES // 1_000_000} MB")


def _image(path: Path | None = None, image: PILImage.Image | None = None) -> Image | None:
    """A PNG for the model to look at, scaled down to MAX_IMAGE_SIDE; None if it's still too big."""
    if image is None:
        if path is None or not path.is_file():
            return None
        image = PILImage.open(path)
        image.load()
    longest = max(image.size)
    if longest > MAX_IMAGE_SIDE:
        factor = MAX_IMAGE_SIDE / longest
        image = image.resize((max(1, round(image.width * factor)), max(1, round(image.height * factor))), PILImage.Resampling.LANCZOS)
    data = io.BytesIO()
    image.convert("RGB").save(data, format="PNG")
    if data.tell() > MAX_IMAGE_BYTES:
        return None
    return Image(data=data.getvalue(), format="png")


def _with_media(result: dict[str, Any], picture: Image | None, path: str | None = None, audio: Path | None = None) -> list[Any]:
    out: list[Any] = []
    if picture is None and path is not None:
        result = {**result, "image_note": f"image too large to inline; open {path}"}
    if audio is not None and audio.is_file() and audio.stat().st_size > MAX_AUDIO_BYTES:
        result = {**result, "audio_note": f"WAV too large to inline; it's at {audio}"}
        audio = None
    out.append(result)
    if picture is not None:
        out.append(picture)
    if audio is not None and audio.is_file():
        out.append(Audio(data=audio.read_bytes(), format="wav"))
    return out


def create_server(root: Path, allow_godot: bool = False) -> MCPServer:
    """The MCP server for the SEGAN project at `root`."""
    segan = Segan(root, allow_godot)
    server = MCPServer(name="segan", title="SEGAN", version=__version__, instructions=INSTRUCTIONS)

    # --- project ---------------------------------------------------------------------------

    @server.tool(annotations=READ)
    def status() -> dict[str, Any]:
        """Every song and SFX (kind, category, length, status, style version, errors/warnings, what needs
        attention), the style version, kits and default kit. Call this first."""
        return segan.cli("status")

    @server.tool(annotations=READ)
    def read_docs() -> dict[str, Any]:
        """BRIEF.md (what the game needs, decisions log) and SOUND.md (how it must sound). Read both before making
        or changing anything: they are the project's memory between sessions."""
        return {"ok": True, **{name: (segan.root / name).read_text(encoding="utf-8") if (segan.root / name).is_file() else None for name in DOCS}}

    @server.tool(annotations=OVERWRITE)
    @_results
    def write_doc(doc: Literal["BRIEF.md", "SOUND.md"], text: str) -> dict[str, Any]:
        """Replace BRIEF.md or SOUND.md with `text` (read it first and keep what's there)."""
        _check_text(text)
        (segan.root / doc).write_text(text, encoding="utf-8")
        return {"ok": True, "written": doc}

    @server.tool(annotations=WRITE)
    @_results
    def log_feedback(note: str) -> dict[str, Any]:
        """Add a dated line to BRIEF.md's "Decisions and feedback log" (what the owner asked or decided)."""
        brief = segan.root / "BRIEF.md"
        if not brief.is_file():
            raise _error("no BRIEF.md in the project")
        line = f"- {date.today().isoformat()}: {' '.join(note.split())}"
        text = brief.read_text(encoding="utf-8").rstrip("\n")
        if "## Decisions and feedback log" not in text:
            text += "\n\n## Decisions and feedback log\n"
        brief.write_text(f"{text}\n{line}\n", encoding="utf-8")
        return {"ok": True, "logged": line}

    @server.tool(annotations=READ)
    def config_show() -> dict[str, Any]:
        """Every segan.toml setting ([mix] room/oversample/crush..., [loudness] targets, kit, export): value, default, meaning."""
        return segan.cli("config", "show")

    @server.tool(annotations=WRITE)
    def config_set(key: str, value: str) -> dict[str, Any]:
        """Change a setting (validated; nothing is written if invalid). `value` is TOML: 0.3, true, "nes",
        ["wav", "godot"]. [mix] changes re-render every song and SFX."""
        return segan.cli("config", "set", key, value)

    @server.tool(annotations=WRITE)
    def config_unset(key: str) -> dict[str, Any]:
        """Return a setting to its default."""
        return segan.cli("config", "unset", key)

    # --- kits ------------------------------------------------------------------------------

    @server.tool(annotations=READ)
    @_results
    def kit_list() -> dict[str, Any]:
        """Every kit: instruments (key -> name, source, range, voices) and groups."""
        project = segan.project()
        kits: dict[str, Any] = {}
        findings: list[Finding] = []
        for name in project.kit_names():
            try:
                kit = project.load_kit(name)
            except SeganError as exc:
                findings.extend(exc.findings)
                continue
            kits[name] = {
                "description": kit.description,
                "instruments": {k: {"name": i.name, "source": i.describe(), "range": list(i.range) if i.range else None, "voices": i.voices}
                                for k, i in kit.instruments.items()},  # fmt: skip
                "groups": {g: list(keys) for g, keys in kit.groups.items()},
            }
        return {"ok": not findings, "default_kit": project.config.default_kit, "kits": kits,
                **({"findings": [f.to_dict() for f in findings]} if findings else {})}  # fmt: skip

    @server.tool(annotations=READ, structured_output=False)
    @_results
    def kit_show(name: str, audio: bool = False) -> list[Any]:
        """Every instrument of a kit playing a test phrase: the kit's listen sheet (look at it) and, with `audio`,
        the WAV for a human to hear."""
        _check_name(name)
        result = segan.cli("kit", "show", name)
        out = (result.get("outputs") or [{}])[0] if result.get("ok") else {}
        sheet = out.get("sheet")
        wav = segan.root / out["wavs"][0] if audio and out.get("wavs") else None
        return _with_media(result, _image(segan.root / sheet) if sheet else None, sheet, wav)

    @server.tool(annotations=OVERWRITE)
    @_results
    def kit_write(name: str, text: str) -> dict[str, Any]:
        """Write kits/<name>.kit.yaml (creates or replaces) and validate it. See segan://reference."""
        from segan.kit import load_kit_file

        _check_name(name)
        _check_text(text)
        path = segan.root / "kits" / f"{name}{KIT_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        try:
            load_kit_file(path)
        except SeganError as exc:
            return {"ok": False, "written": segan.rel(path), "findings": [f.to_dict() for f in exc.findings]}
        return {"ok": True, "written": segan.rel(path)}

    @server.tool(annotations=WRITE)
    def mix_adjust(brightness: float = 0.0, warmth: float = 0.0, room: float = 0.0, crush: int | None = None, loudness: float = 0.0,
                   dry_run: bool = True) -> dict[str, Any]:  # fmt: skip
        """Change the whole project's sound at once ("brighter": brightness 2; "warmer": warmth 2; "wetter": room 0.1;
        "lo-fi": crush 8 (0 = off); "quieter overall": loudness -2). Dry run by default: check, then dry_run false."""
        argv = ["mix", "adjust", f"--brightness={brightness}", f"--warmth={warmth}", f"--room={room}", f"--loudness={loudness}"]
        if crush is not None:
            argv.append(f"--crush={crush}")
        if dry_run:
            argv.append("--dry-run")
        return segan.cli(*argv)

    # --- assets ------------------------------------------------------------------------------

    @server.tool(annotations=WRITE)
    @_results
    def scaffold(kind: Kind, name: str, description: str | None = None, kit: str | None = None, preset: str | None = None,
                 key: str = "A minor", tempo: int = 120, bars: int = 2) -> dict[str, Any]:  # fmt: skip
        """Create a starter file and return its text: a song (tracks with labelled empty rows, a loop) or an SFX
        (from a `preset`: coin, jump, laser, explosion, hit, hurt, powerup, blip, select, door, step).
        Always give a `description` (what it is, when it plays, how it should sound)."""
        _check_name(name)
        argv = ["new", kind, name]
        if description:
            argv.append(f"--description={description}")
        if kit:
            argv.append(f"--kit={kit}")
        if kind == "song":
            argv += [f"--key={key}", f"--tempo={tempo}", f"--bars={bars}"]
        elif preset:
            argv.append(f"--preset={preset}")
        result = segan.cli(*argv)
        path = segan.source_path(kind, name)
        if result.get("ok") and path.is_file():
            result["text"] = path.read_text(encoding="utf-8")
        return result

    @server.tool(annotations=READ)
    @_results
    def read_asset(name: str) -> dict[str, Any]:
        """An asset's source text (song or SFX) by name."""
        path = segan.find_asset(name)
        return {"ok": True, "path": segan.rel(path), "text": path.read_text(encoding="utf-8")}

    @server.tool(annotations=OVERWRITE, structured_output=False)
    @_results
    def write_asset(kind: Kind, name: str, text: str, preview: bool = True) -> list[Any]:
        """Write an asset's source (creates or replaces music/<name>.song.yaml or sfx/<name>.sfx.yaml) and lint it
        (format and rendered-audio checks) in the same call. Fix every error in `findings`; read the warnings.
        When it parses, its listen sheet comes back: look at it."""
        _check_name(name)
        _check_text(text)
        path = segan.source_path(kind, name)
        others = [p for k in KINDS if k != kind and (p := segan.source_path(k, name)).is_file()]
        if others:
            raise _error(f"{segan.rel(others[0])} already uses the name {name!r}: asset names are unique across songs and SFX")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        linted = lint_paths(segan.project(), [path])
        result: dict[str, Any] = {"ok": not linted.errors, "written": segan.rel(path), "errors": len(linted.errors),
                                  "warnings": len(linted.warnings), "findings": [f.to_dict() for f in linted.findings]}  # fmt: skip
        picture = None
        if preview and linted.assets and not linted.errors:
            shown = segan.cli("preview", segan.rel(path), "--output", "main")
            outputs = (shown.get("outputs") or [{}])[0].get("outputs") or [{}]
            sheet = outputs[0].get("sheet")
            if sheet:
                result["sheet"] = sheet
                result["analysis"] = outputs[0].get("analysis")
                picture = _image(segan.root / sheet)
        return _with_media(result, picture)

    # --- recorded sounds -------------------------------------------------------------------

    @server.tool(annotations=ONLINE)
    def sounds_search(query: str, max_seconds: float | None = None, licence: Literal["cc0", "cc-by"] | None = None, limit: int = 15) -> dict[str, Any]:
        """Search Freesound for recordings (needs FREESOUND_API_KEY on the server). Only CC0 and CC BY sounds come
        back. Each result: ref (freesound:<id>), name, author, licence, duration, rating, tags. Compare candidates with
        `sounds_inspect`, keep one with `sounds_add`, then use it in an SFX layer as `sample: freesound:<id>`."""
        argv = ["sounds", "search", query, "--limit", str(limit)]
        if max_seconds is not None:
            argv += ["--max-seconds", str(max_seconds)]
        if licence is not None:
            argv += ["--licence", licence]
        return segan.cli(*argv)

    @server.tool(annotations=FETCH)
    def sounds_add(ref: str, licence: str | None = None, source: str | None = None, author: str | None = None, name: str | None = None) -> dict[str, Any]:
        """Record a sound in the project's sounds.lock: `freesound:<id>` (licence checked, HQ preview fetched into the
        user cache), or a sound file in the project with its licence (CC0 / CC-BY-4.0), source (URL) and author."""
        argv = ["sounds", "add", ref]
        for flag, value in (("--licence", licence), ("--source", source), ("--author", author), ("--name", name)):
            if value is not None:
                argv += [flag, value]
        return segan.cli(*argv)

    @server.tool(annotations=ONLINE)
    def sounds_inspect(refs: list[str]) -> dict[str, Any]:
        """Length, loudness, peak, brightness (spectral centroid), pitch and onsets of recordings (freesound:<id> or
        project files), so candidates can be compared without hearing them."""
        return segan.cli("sounds", "inspect", *refs)

    @server.tool(annotations=WRITE)
    def sounds_credits() -> dict[str, Any]:
        """Write SOUND_CREDITS.md (the attribution CC BY requires) from sounds.lock and the SFX's recorded layers."""
        return segan.cli("sounds", "credits")

    @server.tool(annotations=READ)
    def lint(assets: list[str] | None = None) -> dict[str, Any]:
        """Errors and warnings for named assets (default: the whole project). Rule ids are explained in
        segan://reference; a warning that's wrong by design goes in the asset's `lint: { disable: [...] }`."""
        paths: list[str] = []
        for name in assets or []:
            try:
                paths.append(segan.rel(segan.find_asset(name)))
            except SeganError as exc:
                return _failure(exc.findings)
        return segan.cli("lint", *paths)

    @server.tool(annotations=READ)
    def similarity(songs: list[str] | None = None, shipped: bool = False) -> dict[str, Any]:
        """How alike the project's songs are: pairs scored 0-1 overall and by harmony, rhythm, timbre, register and
        tempo, the closest song for each, and whether two open on the same notes. `shipped` also compares with
        SEGAN's own examples. Run it before calling a soundtrack done: no two songs should open alike."""
        return segan.cli("similarity", *(songs or []), *(["--shipped"] if shipped else []))

    @server.tool(annotations=READ, structured_output=False)
    @_results
    def preview(asset: str, output: str | None = None, start: str | None = None, end: str | None = None, which: Literal["sheet", "seam"] = "sheet",
                audio: bool = False) -> list[Any]:  # fmt: skip
        """Render previews (WAV + listen sheet + seam view for loops + analysis numbers) and return one listen sheet
        as an image: LOOK at it before reporting. `output`: main (default), variant:<name>, variation:<n>,
        phase:<name>, stem:<track>. `start`/`end`: bar numbers (songs) or seconds like 2.5s. `which`: the sheet or
        the loop seam view. `audio`: also return the WAV (for a human; you can't hear it)."""
        _check_name(asset)
        argv = ["preview", asset, f"--output={output or 'main'}"]
        if start:
            argv.append(f"--from={start}")
        if end:
            argv.append(f"--to={end}")
        result = segan.cli(*argv)
        outputs = (result.get("outputs") or [{}])[0].get("outputs") or [{}]
        chosen = outputs[0].get("seam" if which == "seam" else "sheet")
        if result.get("ok") and chosen is None:
            result["image_note"] = f"no {which} for this output (seam views exist for loops only)"
        wav = segan.root / outputs[0]["wav"] if audio and outputs[0].get("wav") else None
        return _with_media(result, _image(segan.root / chosen) if chosen else None, chosen, wav)

    @server.tool(annotations=READ, structured_output=False)
    @_results
    def gallery() -> list[Any]:
        """Every asset's waveform and spectrum side by side plus loudness by category: check the set belongs together."""
        result = segan.cli("gallery")
        path = result.get("gallery")
        return _with_media(result, _image(segan.root / path) if path else None, path)

    @server.tool(annotations=WRITE)
    def mark(assets: list[str] | None = None, status: Literal["draft", "approved"] | None = None, current: bool = False,
             outdated: bool = False) -> dict[str, Any]:  # fmt: skip
        """Record reviews: status approved (only after a HUMAN listened) / draft, and/or `current` = made under the
        current style version. `outdated` applies to every asset made under an older style."""
        argv = ["mark"]
        for name in assets or []:
            try:
                argv.append(segan.rel(segan.find_asset(name)))
            except SeganError as exc:
                return _failure(exc.findings)
        if status is not None:
            argv.append(f"--status={status}")
        argv += [*(["--current"] if current else []), *(["--outdated"] if outdated else [])]
        return segan.cli(*argv)

    @server.tool(annotations=WRITE)
    def style_bump(note: str) -> dict[str, Any]:
        """Record a sound-style change that means existing assets must be revisited: bumps style_version, logs the
        note in SOUND.md, flags older assets (W006) until they're updated and marked current."""
        return segan.cli("style", "bump", note)

    @server.tool(annotations=WRITE)
    @_results
    def import_midi(path: str | None = None, midi_base64: str | None = None, name: str | None = None, kit: str | None = None,
                    key: str | None = None, quantize: int = 16, force: bool = False) -> dict[str, Any]:  # fmt: skip
        """Convert a standard MIDI file into a song source (quantized to the grid, notes snapped to the key, GM
        programs mapped to kit instruments) with a report of what changed. Give a `path` inside the project, or the
        file as `midi_base64` (with a `name`)."""
        if (path is None) == (midi_base64 is None):
            raise _error("give exactly one of path or midi_base64")
        if midi_base64 is not None:
            if name is None:
                raise _error("midi_base64 needs a name")
            _check_name(name)
            try:
                data = base64.b64decode(midi_base64, validate=True)
            except (binascii.Error, ValueError):
                raise _error("midi_base64 isn't valid base64") from None
            source = segan.project().preview_dir / "imports" / f"{name}.mid"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(data)
        else:
            assert path is not None
            source = segan.inside(path)
        argv = ["import", "midi", str(source), f"--quantize={quantize}"]
        if name is not None:
            _check_name(name)
            argv.append(f"--name={name}")
        if kit is not None:
            argv.append(f"--kit={kit}")
        if key is not None:
            argv.append(f"--key={key}")
        if force:
            argv.append("--force")
        return segan.cli(*argv)

    # --- output ------------------------------------------------------------------------------

    @server.tool(annotations=WRITE)
    def build(verify_godot: bool = False) -> dict[str, Any]:
        """Lint, then write final WAVs, manifest.json and engine resources into the project's output dir (usually the
        game). Do this after a human approved the sounds. `verify_godot` loads and plays everything in headless Godot
        (only if the server was started with --allow-godot)."""
        if verify_godot and not segan.allow_godot:
            return _failure([Finding("E000", "verify_godot runs a Godot binary; start the server with `segan mcp --allow-godot`")])
        return segan.cli("build", *(["--verify-godot"] if verify_godot else []))

    @server.tool(annotations=READ)
    @_results
    def manifest(asset: str | None = None) -> dict[str, Any]:
        """The build's manifest.json (the contract with the game): per asset its files, length, loop points (samples),
        bpm, sections, markers, variants, variations, phases, stems and loudness. Optionally one asset."""
        path = segan.project().output_dir / "manifest.json"
        if not path.is_file():
            raise _error("no manifest.json yet: run `build`")
        data = json.loads(path.read_text(encoding="utf-8"))
        if asset is not None:
            entry = data.get("assets", {}).get(asset)
            if entry is None:
                raise _error(f"{asset!r} isn't in the manifest (built assets: {', '.join(data.get('assets', {}))})")
            return {"ok": True, "generator": data.get("generator"), "asset": asset, "entry": entry}
        return {"ok": True, **data}

    # --- resources and prompts ---------------------------------------------------------------

    def skill_text(name: str) -> str:
        text = files("segan").joinpath("skill", name).read_text(encoding="utf-8")
        if text.startswith("---"):
            text = text.split("---", 2)[2].lstrip("\n")  # drop the skill frontmatter
        return text

    @server.resource("segan://workflow", mime_type="text/markdown", description="How to make and maintain game audio with SEGAN")
    def workflow() -> str:
        return skill_text("SKILL.md")

    @server.resource("segan://reference", mime_type="text/markdown", description="The SEGAN notation, settings and lint rules")
    def reference() -> str:
        return skill_text("reference.md")

    @server.resource("segan://brief", mime_type="text/markdown", description="BRIEF.md: what the game needs, decisions log")
    def brief() -> str:
        path = segan.root / "BRIEF.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    @server.resource("segan://sound", mime_type="text/markdown", description="SOUND.md: how the game must sound")
    def sound() -> str:
        path = segan.root / "SOUND.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    @server.resource("segan://manifest", mime_type="application/json", description="The last build's manifest.json")
    def manifest_resource() -> str:
        path = segan.project().output_dir / "manifest.json"
        return path.read_text(encoding="utf-8") if path.is_file() else "{}"

    @server.resource("segan://kit/{name}", mime_type="text/yaml", description="A kit's source")
    def kit_resource(name: str) -> str:
        _check_name(name)
        return (segan.root / "kits" / f"{name}{KIT_SUFFIX}").read_text(encoding="utf-8")

    @server.resource("segan://asset/{name}", mime_type="text/yaml", description="A song's or SFX's source")
    def asset_resource(name: str) -> str:
        return segan.find_asset(name).read_text(encoding="utf-8")

    @server.resource("segan://audio/{name}", mime_type="audio/wav", description="An asset's main preview WAV (after `preview`)")
    def audio_resource(name: str) -> bytes:
        _check_name(name)
        return (segan.project().preview_dir / name / f"{name}.wav").read_bytes()

    @server.prompt(description="Set up the audio for a new game (asks the owner a few questions first)")
    def setup_new_game(game: str = "") -> str:
        return (
            f"Set up SEGAN audio for this game: {game or '(ask me about it)'}.\n"
            "Follow section 1 of segan://workflow: ask ONE message of questions with defaults (style, mood/references, "
            "engine, loudness), shape 1-2 kits with `kit_write` and look at them with `kit_show`, then fill in BRIEF.md and "
            "SOUND.md (`read_docs` / `write_doc`)."
        )

    @server.prompt(description="Make one sound or song: scaffold, write, lint, preview, look, report")
    def make_sound(request: str) -> str:
        return (
            f"Make this with SEGAN: {request}\n"
            "1. `status` and `read_docs`. 2. SFX or song (segan://workflow section 2). 3. `scaffold` with a description "
            "(SFX: start from the closest preset). 4. `write_asset` until there are no errors. 5. `preview` and look at the "
            "listen sheet and numbers (pitch, loudness, lead-in, seam); fix and repeat (at most ~4 rounds). 6. Report the "
            "sheet path, a one-line summary and the WAV path for a human to listen to; leave it draft."
        )

    @server.prompt(description="Change the sound of the whole game (brighter, warmer, wetter, lo-fi, quieter...)")
    def change_the_sound(request: str) -> str:
        return (
            f"Change the sound: {request}\n"
            "Use segan://workflow section 4: prefer `mix_adjust` (dry run first) and `config_set`, which re-render every "
            "asset at once; kit edits change every song using the kit. If assets must be rewritten, `style_bump` and go "
            "through the flagged ones. Check with `gallery`, then `log_feedback`."
        )

    @server.prompt(description="Review an asset against the sound bible")
    def review_asset(name: str) -> str:
        return (
            f"Review {name}: `read_asset`, `lint`, `preview` (and the seam view if it loops), compare with SOUND.md and the "
            "other assets in `gallery`. List concrete problems (pitch off, wrong loudness, late start, clicks, clashes, "
            "too dense) and fix them with `write_asset` if asked. Say clearly that a human must still listen."
        )

    return server


def serve(project: str | None = None, allow_godot: bool = False) -> int:
    """Run the stdio server (`segan mcp`)."""
    start = Path(project) if project else Path.cwd()
    root = find_project_root(start)
    if root is None:
        raise _error(f"no {CONFIG_NAME} found at or above {start}; run `segan init` first or pass --project")
    create_server(root, allow_godot).run("stdio")
    return 0
