"""Godot 4 exporter: `.import` edits (loop points, compression) for every WAV, an AudioStreamRandomizer `.tres`
per SFX with variations and an AudioStreamSynchronized `.tres` per song with stems; plus headless verification.

Adapted from PAGAN's exporters/godot.py. Formats were checked against what Godot 4.7.2 writes itself
(ResourceSaver output and its `.import` files): the `.tres` text matches Godot's (format=3, no uid/load_steps),
resource ids are derived from names (never random), so output is byte-stable.

Loop points: Godot 4.7.2 plays a forward loop as the frames after `loop_begin` up to and including `loop_end`
(checked by mixing a ramp), so a loop [start, end) in SEGAN's terms is `loop_begin = start - 1`, `loop_end = end - 1`.
SEGAN's loops always start at frame 1 or later for that reason.

Ogg Vorbis (export "ogg", music only): Godot loops an AudioStreamOggVorbis from the end of the file back to
frame floor(loop_offset * rate) (measured), so `loop_offset` is written a quarter frame past the loop start
and the file must end where the loop does (SEGAN's looping songs do).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

COMPRESS_MODES = {"none": 0, "ima": 1, "qoa": 2}
LOOP_DISABLED, LOOP_FORWARD = 1, 2


def find_godot_project(start: Path) -> Path | None:
    """The nearest directory at or above `start` that contains project.godot."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / "project.godot").is_file():
            return directory
    return None


def res_path(path: Path, godot_root: Path) -> str:
    return "res://" + path.resolve().relative_to(godot_root.resolve()).as_posix()


def _string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def import_params(loop: tuple[int, int] | None, compress: str) -> dict[str, str]:
    """The `.import` [params] lines SEGAN owns for a WAV."""
    if loop is None:
        mode, begin, end = LOOP_DISABLED, 0, -1
    else:
        mode, begin, end = LOOP_FORWARD, loop[0] - 1, loop[1] - 1
    return {
        "edit/loop_mode": str(mode),
        "edit/loop_begin": str(begin),
        "edit/loop_end": str(end),
        "compress/mode": str(COMPRESS_MODES[compress]),
    }


def ogg_import_params(loop: tuple[int, int] | None, rate: int) -> dict[str, str]:
    """The `.import` [params] lines SEGAN owns for an Ogg Vorbis file."""
    if loop is None:
        return {"loop": "false", "loop_offset": "0"}
    return {"loop": "true", "loop_offset": repr((loop[0] + 0.25) / rate)}


IMPORTERS = {".wav": ("wav", "AudioStreamWAV"), ".ogg": ("oggvorbisstr", "AudioStreamOggVorbis")}


def edit_import(audio: Path, params: dict[str, str]) -> Path | None:
    """Set SEGAN's [params] lines in `audio`'s `.import` sidecar (Godot re-imports when it changes and keeps
    every other line). Without a sidecar, a minimal one is written and Godot fills in the rest. Returns the
    sidecar if it changed."""
    sidecar = audio.with_name(audio.name + ".import")
    if not sidecar.is_file():
        importer, kind = IMPORTERS[audio.suffix]
        body = "\n".join(f"{k}={v}" for k, v in params.items())
        sidecar.write_text(f'[remap]\n\nimporter="{importer}"\ntype="{kind}"\n\n[params]\n\n{body}\n', encoding="utf-8")
        return sidecar
    text = sidecar.read_text(encoding="utf-8")
    lines = text.split("\n")
    missing = dict(params)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in missing:
            lines[i] = f"{key}={missing.pop(key)}"
    if missing:
        if "[params]" in lines:
            at = lines.index("[params]") + 1
            if at < len(lines) and lines[at] == "":
                at += 1
            for offset, (k, v) in enumerate(missing.items()):
                lines.insert(at + offset, f"{k}={v}")
        else:
            lines += ["[params]", "", *(f"{k}={v}" for k, v in missing.items()), ""]
    updated = "\n".join(lines)
    if updated == text:
        return None
    sidecar.write_text(updated, encoding="utf-8")
    return sidecar


def _ids(paths: list[str]) -> list[str]:
    return [f"{i + 1}_{re.sub(r'[^A-Za-z0-9_]', '_', Path(p).stem)}" for i, p in enumerate(paths)]


def randomizer_tres(streams: list[str], random_pitch: float = 1.0, random_volume_db: float = 0.0) -> str:
    """AudioStreamRandomizer over the variation WAVs (Godot's default playback mode: random, no repeats)."""
    ids = _ids(streams)
    lines = ['[gd_resource type="AudioStreamRandomizer" format=3]', ""]
    lines += [f'[ext_resource type="AudioStream" path={_string(p)} id="{i}"]' for p, i in zip(streams, ids, strict=True)]
    lines += ["", "[resource]"]
    if random_pitch != 1.0:
        lines.append(f"random_pitch = {random_pitch!r}")
    if random_volume_db != 0.0:
        lines.append(f"random_volume_offset_db = {random_volume_db!r}")
    lines.append(f"streams_count = {len(streams)}")
    lines += [f'stream_{n}/stream = ExtResource("{i}")' for n, i in enumerate(ids)]
    return "\n".join(lines) + "\n"


def synchronized_tres(streams: list[str]) -> str:
    """AudioStreamSynchronized over a song's stems (all at 0 dB: they add up to the mix)."""
    ids = _ids(streams)
    lines = ['[gd_resource type="AudioStreamSynchronized" format=3]', ""]
    lines += [f'[ext_resource type="AudioStream" path={_string(p)} id="{i}"]' for p, i in zip(streams, ids, strict=True)]
    lines += ["", "[resource]", f"stream_count = {len(streams)}"]
    for n, i in enumerate(ids):
        lines += [f'stream_{n}/stream = ExtResource("{i}")', f"stream_{n}/volume = 0.0"]
    return "\n".join(lines) + "\n"


# --- headless verification --------------------------------------------------------------------


@dataclass
class GodotCheck:
    ok: bool
    output: str
    streams: int = 0


def find_godot_binary() -> str | None:
    candidate = os.environ.get("GODOT")
    if candidate:
        return candidate
    for name in ("godot", "godot4"):
        found = shutil.which(name)
        if found:
            return found
    return None


def verify_with_godot(godot: str, godot_root: Path, manifest_res: str, timeout: int = 300) -> GodotCheck:
    """Import the project, then load and briefly play every generated stream in a headless Godot.

    The check script runs from a temp folder (by absolute path), so nothing is written into the game.
    """
    script = files("segan").joinpath("templates", "godot_verify.gd").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="segan-verify-") as scratch:
        script_path = Path(scratch) / "segan_verify.gd"
        script_path.write_text(script, encoding="utf-8")
        stage = "import"
        try:
            imported = subprocess.run(
                [godot, "--headless", "--path", str(godot_root), "--import"], capture_output=True, text=True, timeout=timeout
            )
            import_output = (imported.stdout + imported.stderr).strip()
            import_errors = [line for line in import_output.splitlines() if "ERROR" in line]
            if imported.returncode != 0 or import_errors:
                detail = "\n".join(import_errors[-20:]) or import_output[-2000:]
                return GodotCheck(ok=False, output=f"Godot's import step failed (exit {imported.returncode}):\n{detail}")
            stage = "check"
            result = subprocess.run(
                [godot, "--headless", "--path", str(godot_root), "-s", str(script_path), "--", manifest_res],
                capture_output=True, text=True, timeout=timeout,
            )  # fmt: skip
        except FileNotFoundError:
            return GodotCheck(ok=False, output=f"Godot binary not found: {godot} (set GODOT=/path/to/godot)")
        except PermissionError:
            return GodotCheck(ok=False, output=f"can't run {godot}: not executable")
        except subprocess.TimeoutExpired:
            what = "import step" if stage == "import" else "check script (it takes seconds: this is a hang)"
            return GodotCheck(ok=False, output=f"Godot's {what} didn't finish within {timeout}s")
    output = (result.stdout + result.stderr).strip()
    ok = result.returncode == 0 and "SEGAN_VERIFY_OK" in result.stdout and "SCRIPT ERROR" not in output
    match = re.search(r"SEGAN_VERIFY_OK (\d+) streams", result.stdout)
    return GodotCheck(ok=ok, output=output, streams=int(match.group(1)) if match else 0)
