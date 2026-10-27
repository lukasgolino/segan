"""#15 / #18: SFX `takes:` (structural variations under one asset, one manifest entry, one randomizer)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from segan.build import build
from segan.project import Project, load_project
from segan.render import render_asset

from conftest import CONFIG, load, make_project, rules, run_json, write

HIT = """\
name: hit
duration: 0.3
layers:
  - { id: crack, osc: noise, env: [0.001, 0.05, 0, 0.02], gain: -6 }
  - { id: thud, osc: sine, pitch: C3, env: [0.001, 0.1, 0, 0.05] }
"""
TAKES = """\
takes:
  - duration: 0.4
    layers:
      - { id: crack, gain: -9 }
      - { id: thud, remove: true }
      - { id: ping, osc: triangle, pitch: A5, env: [0.001, 0.1, 0, 0.05] }
  - { variations: { count: 1 } }
"""


def test_takes_merge_layers_by_id(project: Project) -> None:
    sfx, findings = load(project, "sfx", "hit", HIT + TAKES)
    assert sfx is not None, findings
    two, three = sfx.takes
    assert (two.number, two.duration, three.number, three.duration) == (2, 0.4, 3, 0.3)
    assert [layer.id for layer in two.layers] == ["crack", "ping"]
    assert two.layers[0].inst.gain == -9 and two.layers[0].inst.wave == "noise"  # only the given field changes
    assert [layer.id for layer in three.layers] == ["crack", "thud"] and three.variations is not None and three.variations.count == 1


@pytest.mark.parametrize(
    "takes",
    [
        "takes: []\n",
        "takes: [{ layers: [{ id: nope, remove: true }] }]\n",
        "takes: [{ layers: [{ id: crack, remove: true, gain: 1 }] }]\n",
        "takes: [{ layers: [{ id: crack, remove: true }, { id: thud, remove: true }] }]\n",
        "takes: [{ pitch: 3 }]\n",
        "takes: [{ duration: 99 }]\n",
        "takes: [{ layers: [{ id: crack, gain: x }] }]\n",
        "takes: [{ variations: { count: 0 } }]\n",
    ],
)
def test_bad_takes(project: Project, takes: str) -> None:
    sfx, findings = load(project, "sfx", "hit", HIT + takes)
    assert sfx is None and "E013" in rules(findings), findings


def test_take_and_phase_names_clash(project: Project) -> None:
    sfx, findings = load(project, "sfx", "hit", HIT + TAKES + "phases:\n  t2: { duration: 0.2 }\n")
    assert sfx is None and "E008" in rules(findings)


def test_take_one_is_the_sfx_as_written(project: Project) -> None:
    source = HIT.replace("name: hit", "name: a") + "variations: { count: 2, seed: 3, pitch: 1 }\n"
    plain, _ = load(project, "sfx", "a", source)
    assert plain is not None
    before = render_asset(plain, project, use_cache=False)
    taken, findings = load(project, "sfx", "a", source + TAKES)
    assert taken is not None, findings
    after = render_asset(taken, project, use_cache=False)
    assert [o.id for o in after.outputs] == ["", "variation:1", "variation:2", "take:2", "take:2:variation:1", "take:2:variation:2", "take:3", "take:3:variation:1"]
    assert [o.stem for o in after.outputs][3:] == ["a.t2", "a.t2.1", "a.t2.2", "a.t3", "a.t3.1"]
    for old in before.outputs:  # take 1 and its variations: the same samples as without takes
        assert np.array_equal(old.pcm, after.output(old.id).pcm)
    assert not np.array_equal(after.output("take:3").pcm, after.output("").pcm)  # take 3 = take 1's layers, own seeds
    assert after.output("take:2").info["take"] == 2


def test_build_manifest_and_randomizer(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "src").mkdir()
    project = make_project(tmp_path / "src", CONFIG.replace('default_kit = "t"', 'default_kit = "t"\noutput_dir = "../game/audio"\nexport = ["wav", "godot"]'))
    write(project, "sfx", "hit", HIT + "variations: { count: 2, seed: 1, pitch: 1, include_main: false }\n" + TAKES
          + "  - { variations: null }\n")  # fmt: skip
    result = build(load_project(project.root))
    assert not result.errors, result.errors
    audio = tmp_path / "game" / "audio"
    entry = json.loads((audio / "manifest.json").read_text())["assets"]["hit"]
    assert "file" not in entry and [v["file"] for v in entry["variations"]] == ["res://audio/sfx/hit.1.wav", "res://audio/sfx/hit.2.wav"]
    two, three, four = entry["takes"]
    assert two["take"] == 2 and "file" not in two and [v["file"] for v in two["variations"]] == ["res://audio/sfx/hit.t2.1.wav", "res://audio/sfx/hit.t2.2.wav"]
    assert "file" not in three and len(three["variations"]) == 1  # count over the SFX's, include_main false still holds
    assert four["file"] == "res://audio/sfx/hit.t4.wav" and "variations" not in four and four["lufs"] is not None
    tres = (audio / "sfx" / "hit.tres").read_text()
    assert "streams_count = 6" in tres and "hit.t2.2.wav" in tres and "hit.t4.wav" in tres
    assert not (audio / "sfx" / "hit.t2.wav").exists()
    # dropping a take removes its files
    write(project, "sfx", "hit", HIT + "variations: { count: 2, seed: 1, pitch: 1, include_main: false }\n" + TAKES)
    removed = sorted(p.name for p in build(load_project(project.root)).removed)
    assert removed == ["hit.t4.wav"]


def test_takes_without_variations_get_a_randomizer(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "src").mkdir()
    project = make_project(tmp_path / "src", CONFIG.replace('default_kit = "t"', 'default_kit = "t"\noutput_dir = "../game/audio"\nexport = ["wav", "godot"]'))
    write(project, "sfx", "hit", HIT + "takes: [{ duration: 0.2 }]\n")
    assert not build(load_project(project.root)).errors
    audio = tmp_path / "game" / "audio"
    entry = json.loads((audio / "manifest.json").read_text())["assets"]["hit"]
    assert entry["file"] == "res://audio/sfx/hit.wav" and entry["takes"][0]["file"] == "res://audio/sfx/hit.t2.wav"
    tres = (audio / "sfx" / "hit.tres").read_text()
    assert "streams_count = 2" in tres and "hit.wav" in tres


def test_preview_reel_and_take_output(project: Project, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    write(project, "sfx", "hit", HIT + TAKES)
    monkeypatch.chdir(project.root)
    code, data = run_json(["preview", "hit", "--output", "take:2", "--output", "reel"], capsys)
    assert code == 0, data
    files = data["outputs"][0]["outputs"]
    assert [f["output"] for f in files] == ["take:2", "reel"]
    assert [layer["layer"] for layer in files[0]["analysis"]["layers"]] == ["crack", "ping", "(dry mix)"]
    assert [t["output"] for t in files[1]["analysis"]["takes"]] == ["main", "take:2", "take:3", "take:3:variation:1"]


def test_lint_checks_every_take(project: Project) -> None:
    from segan.lint import lint_asset

    sfx, _ = load(project, "sfx", "hit", HIT + "takes: [{ duration: 0.05, layers: [{ id: thud, env: [0.001, 0.4, 0.5, 0.3] }] }]\n")
    assert sfx is not None
    cut = [f for f in lint_asset(sfx, project) if f.rule == "W011"]
    assert cut and all("hit.t2" in f.message for f in cut)


def test_takes_build_loads_in_godot(tmp_path: Path) -> None:
    from segan.exporters.godot import find_godot_binary, verify_with_godot

    godot = find_godot_binary()
    if godot is None:
        pytest.skip("no Godot binary (set GODOT=/path/to/godot)")
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "src").mkdir()
    project = make_project(tmp_path / "src", CONFIG.replace('default_kit = "t"', 'default_kit = "t"\noutput_dir = "../game/audio"\nexport = ["wav", "godot"]'))
    write(project, "sfx", "hit", HIT + "variations: { count: 2, seed: 1, pitch: 1 }\n" + TAKES + "  - { variations: null }\n")
    assert not build(load_project(project.root)).errors
    check = verify_with_godot(godot, tmp_path / "game", "res://audio/manifest.json")
    assert check.ok and check.streams >= 1, check.output
