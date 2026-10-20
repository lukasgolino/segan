"""End-to-end Godot checks. Skipped unless a Godot 4 binary is available (GODOT env var or `godot` on PATH).

CI downloads Godot 4.7.2, so these run there on every push.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from segan import oggio
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


DIRECTOR_RENDER = """\
extends SceneTree
func _init():
	var script = load("res://audio/segan_music.gd")
	if script == null:
		quit(1)
		return
	var music = script.new()
	music.offline = true
	music.load_manifest("res://audio/manifest.json")
	music.rng.seed = 7
	music.play_song("f")
	for s in ["verse", "up", "verse", "verse"]:
		music.queue_section(s)
	var f := FileAccess.open(OS.get_cmdline_user_args()[0], FileAccess.WRITE)
	var total := 0
	while total < 44100 * 20:
		var chunk: PackedVector2Array = music.render(4096)
		for v in chunk:
			f.store_float(v.x)
			f.store_float(v.y)
		total += chunk.size()
	f.close()
	print("MIXRATE ", AudioServer.get_mix_rate())
	music.free()
	quit()
"""

DIRECTOR_LIVE = """\
extends SceneTree
func _init():
	var music = load("res://audio/segan_music.gd").new()
	music.random_seed = 3
	root.add_child(music)
	var t0 := Time.get_ticks_msec()
	music.state_changed.connect(func(s): print("EVENT state ", s))
	music.song_started.connect(func(s, v): print("EVENT song ", s))
	music.section_started.connect(func(s, sec): print("EVENT section ", s, " ", sec))
	music.play_soundtrack("main")
	for step in [[1.5, "tense"], [3.0, "stop"], [4.0, "end"]]:
		while (Time.get_ticks_msec() - t0) / 1000.0 < step[0]:
			await process_frame
		if step[1] == "stop":
			music.stop(0.5)
		elif step[1] == "tense":
			music.set_state("tense")
	print("LIVE_OK")
	quit()
"""


DIRECTOR_CROSSFADE = """\
extends SceneTree
func _init():
	var music = load("res://audio/segan_music.gd").new()
	music.random_seed = 5
	root.add_child(music)
	var t0 := Time.get_ticks_msec()
	music.song_started.connect(func(s, v): print("EVENT song %s %.2f" % [s, (Time.get_ticks_msec() - t0) / 1000.0]))
	music.song_finished.connect(func(s): print("EVENT finished %s %.2f" % [s, (Time.get_ticks_msec() - t0) / 1000.0]))
	music.play_soundtrack("pool")
	while (Time.get_ticks_msec() - t0) / 1000.0 < 6.0:
		await process_frame
	print("LIVE_OK")
	quit()
"""

POOL = """\
name: pool
states:
  calm: { songs: [f, g], play: 2, gap: 30, crossfade: 1 }
families:
  a_minor: [f, g]
"""


def make_flow_game(tmp_path: Path, ogg: bool = False) -> Path:
    """A Godot project with a flow song, a looping song, a stinger SFX and a soundtrack built into res://audio."""
    from test_flow import FLOW_SONG, G_SONG, SOUNDTRACK

    from conftest import CONFIG, make_project, write

    game = tmp_path / "game"
    game.mkdir()
    (game / "project.godot").write_text('config_version=5\n\n[application]\n\nconfig/name="flow"\n')
    config = CONFIG.replace("sample_rate = 22050", "sample_rate = 44100").replace(
        'mode = "strict"', 'mode = "strict"\noutput_dir = "../game/audio"\nexport = ["wav", "godot"' + (', "ogg"' if ogg else "") + "]"
    )
    (tmp_path / "src").mkdir()
    project = make_project(tmp_path / "src", config + '\n[godot]\ncompress = "none"\n')
    write(project, "song", "f", FLOW_SONG + "variants:\n  night: { semitones: -2 }\n")
    write(project, "song", "g", G_SONG)
    write(project, "sfx", "hit", "name: hit\npreset: hit\n")
    (project.music_dir / "main.soundtrack.yaml").write_text(SOUNDTRACK)
    (project.music_dir / "pool.soundtrack.yaml").write_text(POOL)
    result = build(project)
    assert not result.errors, result.errors
    assert GODOT is not None
    check = verify_with_godot(GODOT, game, "res://audio/manifest.json")
    assert check.ok, check.output
    return game


@pytest.fixture
def flow_game(tmp_path: Path) -> Path:
    return make_flow_game(tmp_path)


def director_render(game: Path, tmp_path: Path) -> tuple[np.ndarray, list[tuple[str, int]]]:
    """The director's offline output for a fixed walk, and the clips (res path, frames) it should equal."""
    script = tmp_path / "director_render.gd"
    script.write_text(DIRECTOR_RENDER)
    raw = tmp_path / "out.raw"
    assert GODOT is not None
    run = subprocess.run([GODOT, "--headless", "--path", str(game), "-s", str(script), "--", str(raw)], capture_output=True, text=True, timeout=300)
    output = run.stdout + run.stderr
    assert "SCRIPT ERROR" not in output and "MIXRATE 44100" in output, output
    sections = json.loads((game / "audio" / "manifest.json").read_text())["assets"]["f"]["flow"]["sections"]
    path = ["intro", "verse", "up", "verse", "verse", "up"]
    clips = []
    for i, name in enumerate(path):
        section = sections[name]
        head = section["from"].get(path[i - 1], section["head"]) if i else section["head"]
        clips.append((head, section["head_samples"]))
        if section["rest"] is not None:
            clips.append((section["rest"], section["samples"] - section["head_samples"]))
    return np.fromfile(raw, dtype="<f4").reshape(-1, 2), clips


def test_director_chains_flow_clips_sample_exactly(flow_game: Path, tmp_path: Path) -> None:
    import wave

    def pcm(res: str, frames: int) -> np.ndarray:
        with wave.open(str(flow_game / res.removeprefix("res://"))) as w:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, w.getnchannels())
        return data[:frames] / 32767.0  # Godot decodes 16-bit PCM as x / 32767

    got, clips = director_render(flow_game, tmp_path)
    expected = np.concatenate([pcm(res, frames) for res, frames in clips])
    assert len(got) >= len(expected)
    assert np.abs(got[: len(expected)] - expected).max() < 1e-6  # every seam exact: no lost, doubled or late frames


@pytest.mark.skipif(not oggio.available(), reason="needs soundfile (segan[ogg])")
def test_director_chains_ogg_clips_sample_exactly(tmp_path: Path) -> None:
    game = make_flow_game(tmp_path, ogg=True)  # (the build's --verify-godot check passed: OGG streams load and loop)
    manifest = json.loads((game / "audio" / "manifest.json").read_text())
    assert manifest["assets"]["g"]["file"].endswith(".ogg") and manifest["assets"]["hit"]["file"].endswith(".wav")

    def pcm(res: str, frames: int) -> np.ndarray:
        audio, _ = oggio.decode_ogg((game / res.removeprefix("res://")).read_bytes())
        return audio[:frames]

    got, clips = director_render(game, tmp_path)
    assert all(res.endswith(".ogg") for res, _ in clips)
    expected = np.concatenate([pcm(res, frames) for res, frames in clips])
    assert np.abs(got[: len(expected)] - expected).max() < 1e-5  # Godot's Vorbis decoder = libvorbis's; seams exact


def test_director_plays_a_soundtrack_live(flow_game: Path, tmp_path: Path) -> None:
    script = tmp_path / "director_live.gd"
    script.write_text(DIRECTOR_LIVE)
    output = run_script(flow_game, script)
    assert "LIVE_OK" in output and "SCRIPT ERROR" not in output, output
    events = [line for line in output.splitlines() if line.startswith("EVENT")]
    assert events[:3] == ["EVENT state calm", "EVENT song f", "EVENT section f intro"], events
    assert "EVENT state tense" in events and any(e.startswith("EVENT song g") or e == "EVENT song f" for e in events[3:]), events


def test_director_cross_fades_within_a_family(flow_game: Path, tmp_path: Path) -> None:
    script = tmp_path / "director_crossfade.gd"
    script.write_text(DIRECTOR_CROSSFADE)
    output = run_script(flow_game, script)
    assert "LIVE_OK" in output and "SCRIPT ERROR" not in output, output
    starts = [float(line.split()[-1]) for line in output.splitlines() if line.startswith("EVENT song")]
    finished = [float(line.split()[-1]) for line in output.splitlines() if line.startswith("EVENT finished")]
    assert len(starts) >= 2 and starts[1] < 4.5, output  # the next song comes in on the bar after 2 s, not after the 30 s gap
    assert finished and finished[0] > starts[1], output  # the first one was still fading when the second started
