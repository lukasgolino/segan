from __future__ import annotations

import json
from pathlib import Path

from segan.build import build
from segan.exporters.godot import edit_import, import_params, randomizer_tres, synchronized_tres
from segan.project import load_project
from segan.wavio import read_wav

from conftest import CONFIG, make_project, write
from test_song import SONG


def setup(root: Path, config: str = CONFIG) -> Path:
    project = make_project(root, config)
    write(project, "song", "tune", SONG)
    write(project, "sfx", "coin", "name: coin\npreset: coin\nvariations: { count: 3, seed: 1, pitch: 1 }\n")
    write(project, "sfx", "hum", "name: hum\nlayers:\n  - { osc: sine, pitch: A3 }\nphases:\n  idle: { duration: 0.5, loop: true }\n")
    write(project, "sfx", "base", "name: base\ntemplate: true\nlayers:\n  - { osc: sine }\n")
    return root


def test_build_writes_wavs_and_manifest(tmp_path: Path) -> None:
    root = setup(tmp_path)
    result = build(load_project(root))
    assert not result.errors, result.errors
    out = root / "build" / "audio"
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["generator"].startswith("segan ")
    assert sorted(manifest["assets"]) == ["coin", "hum", "tune"]  # templates aren't built
    coin = manifest["assets"]["coin"]
    assert coin["file"] == "sfx/coin.wav" and coin["category"] == "pickup" and coin["loop"] is None
    assert [v["file"] for v in coin["variations"]] == ["sfx/coin.1.wav", "sfx/coin.2.wav", "sfx/coin.3.wav"]
    # #13: the sound without its room tail (what a voice pool should count busy); loops have none
    assert 0 < coin["dry_seconds"] <= coin["seconds"] and coin["variations"][0]["dry_seconds"] == coin["dry_seconds"]
    assert manifest["assets"]["hum"]["dry_seconds"] < manifest["assets"]["hum"]["seconds"]  # a room tail follows the sound
    assert "dry_seconds" not in manifest["assets"]["hum"]["phases"]["idle"] and "dry_seconds" not in manifest["assets"]["tune"]
    hum = manifest["assets"]["hum"]
    assert hum["phases"]["idle"]["loop"] == {"start": 1, "end": hum["phases"]["idle"]["samples"]}
    tune = manifest["assets"]["tune"]
    assert tune["bpm"] == 120 and tune["beat_count"] == 6 and tune["sections"]["main"]["start"] == 22050
    assert tune["loop"]["section"] == "main" and tune["loop"]["end"] == tune["samples"]
    assert tune["markers"]["top"] == {"sample": 22050, "seconds": 1.0, "bar": 1.5}
    assert set(tune["variants"]) == {"fast", "other", "minor"} and tune["variants"]["fast"]["bpm"] == 150
    wav = read_wav((out / "music" / "tune.wav").read_bytes())
    assert wav.loop == (tune["loop"]["start"], tune["loop"]["end"]) and wav.cues == [("top", 22050)]
    assert sorted(manifest["files"]) == manifest["files"] and "music/tune.fast.wav" in manifest["files"]


def test_build_is_deterministic_and_only_writes_changes(tmp_path: Path) -> None:
    root = setup(tmp_path)
    first = build(load_project(root))
    out = root / "build" / "audio"
    snapshot = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    second = build(load_project(root))
    assert second.written == [] and len(second.unchanged) == len(first.written)
    assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == snapshot
    # fresh caches, same bytes
    for cached in (root / ".segan-cache").rglob("*.npz"):
        cached.unlink()
    build(load_project(root))
    assert {p: p.read_bytes() for p in out.rglob("*") if p.is_file()} == snapshot


def test_stale_outputs_are_removed(tmp_path: Path) -> None:
    root = setup(tmp_path)
    build(load_project(root))
    out = root / "build" / "audio"
    (out / "sfx" / "coin.3.wav.import").write_text("x")
    write(load_project(root), "sfx", "coin", "name: coin\npreset: coin\nvariations: { count: 2, seed: 1, pitch: 1 }\n")
    (root / "sfx" / "hum.sfx.yaml").unlink()
    result = build(load_project(root))
    removed = sorted(p.name for p in result.removed)
    assert removed == ["coin.3.wav", "hum.idle.wav", "hum.wav"]
    assert not (out / "sfx" / "coin.3.wav.import").exists()


def test_lint_errors_stop_the_build(tmp_path: Path) -> None:
    root = setup(tmp_path)
    write(load_project(root), "sfx", "bad", "name: bad\nlayers: []\n")
    result = build(load_project(root))
    assert result.errors and not (root / "build" / "audio" / "manifest.json").exists()


def test_godot_export(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "src").mkdir()
    root = setup(tmp_path / "src", CONFIG.replace('default_kit = "t"', 'default_kit = "t"\noutput_dir = "../game/audio"\nexport = ["wav", "godot", "stems"]'))
    result = build(load_project(root))
    assert not result.errors, result.errors
    audio = tmp_path / "game" / "audio"
    manifest = json.loads((audio / "manifest.json").read_text())
    coin = manifest["assets"]["coin"]
    assert coin["file"] == "res://audio/sfx/coin.wav" and coin["godot_randomizer"] == "res://audio/sfx/coin.tres"
    tres = (audio / "sfx" / "coin.tres").read_text()
    assert tres.startswith('[gd_resource type="AudioStreamRandomizer" format=3]') and "streams_count = 3" in tres
    tune = manifest["assets"]["tune"]
    assert set(tune["stems"]) == {"lead", "bass", "drums"} and tune["godot_stems"] == "res://audio/stems/tune.tres"
    assert "stream_count = 3" in (audio / "stems" / "tune.tres").read_text()
    imported = (audio / "music" / "tune.wav.import").read_text()
    start, end = tune["loop"]["start"], tune["loop"]["end"]
    assert f"edit/loop_begin={start - 1}" in imported and f"edit/loop_end={end - 1}" in imported and "compress/mode=2" in imported
    assert "edit/loop_mode=1" in (audio / "sfx" / "coin.wav.import").read_text()


def test_edit_import_keeps_godots_lines(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    sidecar = tmp_path / "a.wav.import"
    sidecar.write_text('[remap]\n\nimporter="wav"\nuid="uid://x"\n\n[params]\n\nforce/mono=false\nedit/loop_mode=0\nedit/loop_begin=0\nedit/loop_end=-1\ncompress/mode=2\n')
    assert edit_import(wav, import_params((10, 100), "ima")) == sidecar
    text = sidecar.read_text()
    assert 'uid="uid://x"' in text and "force/mono=false" in text
    assert "edit/loop_mode=2\nedit/loop_begin=9\nedit/loop_end=99\ncompress/mode=1" in text
    assert edit_import(wav, import_params((10, 100), "ima")) is None  # unchanged: not rewritten


def test_tres_text() -> None:
    assert randomizer_tres(["res://a.1.wav", "res://a.2.wav"]) == (
        '[gd_resource type="AudioStreamRandomizer" format=3]\n\n'
        '[ext_resource type="AudioStream" path="res://a.1.wav" id="1_a_1"]\n'
        '[ext_resource type="AudioStream" path="res://a.2.wav" id="2_a_2"]\n\n'
        "[resource]\nstreams_count = 2\n"
        'stream_0/stream = ExtResource("1_a_1")\nstream_1/stream = ExtResource("2_a_2")\n'
    )
    assert 'stream_1/volume = 0.0' in synchronized_tres(["res://x.wav", "res://y.wav"])


def test_stems_only_and_variations_only(tmp_path: Path) -> None:
    from test_song import GROUPED

    project = make_project(tmp_path)
    write(project, "song", "tune", GROUPED.replace("mixes:", "main_mix: false\n  mixes:"))
    write(project, "sfx", "coin", "name: coin\npreset: coin\nvariations: { count: 2, seed: 1, pitch: 1, include_main: false }\n")
    result = build(load_project(tmp_path))
    assert not result.errors, result.errors
    manifest = json.loads((tmp_path / "build" / "audio" / "manifest.json").read_text())
    coin, tune = manifest["assets"]["coin"], manifest["assets"]["tune"]
    assert "file" not in coin and len(coin["variations"]) == 2
    assert "file" not in tune and tune["loop"]["end"] == tune["samples"]
    assert tune["stems"]["base"]["tracks"] == ["bass", "drums"] and tune["stems"]["base"]["file"] == "stems/tune/base.wav"
    assert tune["stem_mixes"]["calm"]["stems"] == ["base"] and tune["stems_normalised_over"] == "full"
    assert "sfx/coin.wav" not in manifest["files"] and "music/tune.wav" not in manifest["files"]
    assert not any("mix." in f for f in manifest["files"])
