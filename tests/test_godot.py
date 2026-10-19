"""End-to-end Godot checks. Skipped unless a Godot 4 binary is available (GODOT env var or `godot` on PATH).

CI downloads Godot 4.7.2, so these run there on every push.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from segan.build import build
from segan.exporters.godot import find_godot_binary, verify_with_godot
from segan.project import load_project

ROOT = Path(__file__).parent.parent
GODOT = find_godot_binary()
pytestmark = pytest.mark.skipif(GODOT is None, reason="no Godot binary (set GODOT=/path/to/godot)")


@pytest.fixture
def copies(tmp_path: Path) -> tuple[Path, Path]:
    """The demo project and Godot project, copied so the test can build without touching the repo."""
    shutil.copytree(ROOT / "examples" / "demo", tmp_path / "demo", ignore=shutil.ignore_patterns("previews", ".segan-cache"))
    shutil.copytree(ROOT / "examples" / "godot", tmp_path / "godot", ignore=shutil.ignore_patterns(".godot"))
    return tmp_path / "demo", tmp_path / "godot"


def run_script(godot_root: Path, script: Path) -> str:
    assert GODOT is not None
    subprocess.run([GODOT, "--headless", "--path", str(godot_root), "--import"], capture_output=True, timeout=300)
    run = subprocess.run([GODOT, "--headless", "--path", str(godot_root), "-s", str(script)], capture_output=True, text=True, timeout=300)
    return run.stdout + run.stderr


def test_generated_audio_loads_and_plays_in_godot(copies: tuple[Path, Path]) -> None:
    demo, godot_root = copies
    result = build(load_project(demo))
    assert not result.errors and result.godot_root == godot_root.resolve()
    assert GODOT is not None
    check = verify_with_godot(GODOT, godot_root, "res://assets/generated/audio/manifest.json")
    assert check.ok and check.streams > 20, check.output


def test_demo_scene_lists_every_asset(copies: tuple[Path, Path]) -> None:
    demo, godot_root = copies
    build(load_project(demo))
    output = run_script(godot_root, godot_root / "tests" / "check_scene.gd")
    assert "CHECK_OK" in output and "SCRIPT ERROR" not in output, output


LOOP_CHECK = """\
extends SceneTree
func _init():
	var manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/generated/audio/manifest.json"))
	var entry = manifest["assets"]["overworld"]
	var wav: AudioStreamWAV = load(entry["file"])
	var start: int = entry["loop"]["start"]
	var end: int = entry["loop"]["end"]
	var playback = wav.instantiate_playback()
	playback.start(float(end - 2000) / wav.mix_rate)
	var mixed: PackedVector2Array = playback.mix_audio(1.0, 4000)
	var reference = wav.instantiate_playback()
	reference.start(float(start - 2000) / wav.mix_rate)
	var expected: PackedVector2Array = reference.mix_audio(1.0, 4000)
	var worst := 0.0
	for i in range(200, 3800):
		worst = max(worst, abs(mixed[i].x - expected[i].x))
	print("LOOP_DIFF ", worst)
	var randomizer: AudioStreamRandomizer = load(manifest["assets"]["step"]["godot_randomizer"])
	var signatures := []
	for v in manifest["assets"]["step"]["variations"]:
		var p = load(v["file"]).instantiate_playback()
		p.start(0.0)
		signatures.append(p.mix_audio(1.0, 600))
	var picks := []
	for n in range(8):
		var p = randomizer.instantiate_playback()
		p.start(0.0)
		var frames: PackedVector2Array = p.mix_audio(1.0, 600)
		var best := -1
		var best_error := 1e9
		for s in range(signatures.size()):
			var error := 0.0
			for i in range(100, 600):
				error += abs(frames[i].x - signatures[s][i].x)
			if error < best_error:
				best_error = error
				best = s
		picks.append(best)
	print("PICKS ", picks)
	quit()
"""


def test_loops_are_seamless_and_the_randomizer_cycles(copies: tuple[Path, Path], tmp_path: Path) -> None:
    demo, godot_root = copies
    (demo / "segan.toml").write_text((demo / "segan.toml").read_text().replace('compress = "qoa"', 'compress = "none"'))
    assert not build(load_project(demo)).errors
    script = tmp_path / "loop_check.gd"
    script.write_text(LOOP_CHECK)
    output = run_script(godot_root, script)
    diff = float(output.split("LOOP_DIFF ")[1].split()[0])
    assert diff < 1e-3, output  # playing across the loop point = playing the loop's start
    picks = json.loads(output.split("PICKS ")[1].split("\n")[0])
    assert len(set(picks)) >= 2 and all(a != b for a, b in zip(picks, picks[1:]))  # random, no repeats
