from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from segan.findings import Finding
from segan.project import Project
from segan.render import render_asset
from segan.sfx import PRESETS
from segan.wavio import read_wav

from conftest import load, rules, write

BASIC = """\
name: zap
category: sfx
duration: 0.2
layers:
  - id: tone
    osc: pulse
    pitch: [[0, C6], [0.15, C4]]
    slide: true
    env: [0.001, 0.05, 0.5, 0.05]
    length: 0.1
"""


def test_basic_sfx_renders_to_target(project: Project) -> None:
    sfx, findings = load(project, "sfx", "zap", BASIC)
    assert findings == [] and sfx is not None
    render = render_asset(sfx, project)
    main = render.main
    assert main.rate == 22050 and main.channels == 1 and main.loop is None
    assert abs(float(main.level["lufs"]) + 14.0) < 0.3  # type: ignore[arg-type]
    assert read_wav(main.wav()).frames == main.frames


def test_render_is_cached_and_deterministic(project: Project) -> None:
    sfx, _ = load(project, "sfx", "zap", BASIC)
    first = render_asset(sfx, project, use_cache=False).main.wav()
    assert first == render_asset(sfx, project).main.wav() == render_asset(sfx, project).main.wav()
    assert list((project.cache_dir / "renders").glob("*.npz"))


@pytest.mark.parametrize("preset", PRESETS)
def test_every_preset_loads_and_sounds(project: Project, preset: str) -> None:
    sfx, findings = load(project, "sfx", preset, f"name: {preset}\npreset: {preset}\n")
    assert sfx is not None, findings
    main = render_asset(sfx, project).main
    assert float(main.level["measured"]) > -60  # type: ignore[arg-type]


def test_preset_layers_merge_by_id(project: Project) -> None:
    sfx, findings = load(project, "sfx", "c", "name: c\npreset: coin\nduration: 0.5\nlayers:\n  - { id: tone, duty: 0.25 }\n")
    assert sfx is not None, findings
    tone = next(layer for layer in sfx.layers if layer.id == "tone")
    assert tone.inst.duty == 0.25 and tone.pitch is not None and sfx.duration == 0.5 and len(sfx.layers) == 2


def test_variations_and_phases(project: Project) -> None:
    text = BASIC + "variations: { count: 3, seed: 2, pitch: 2, timbre: 0.5 }\nphases:\n  hold: { duration: 0.5, loop: true, crossfade: 0.05 }\n"
    sfx, findings = load(project, "sfx", "zap", text)
    assert sfx is not None, findings
    render = render_asset(sfx, project)
    ids = [o.id for o in render.outputs]
    assert ids == ["", "variation:1", "variation:2", "variation:3", "phase:hold"]
    assert [o.stem for o in render.outputs][1:] == ["zap.1", "zap.2", "zap.3", "zap.hold"]
    waves = [o.pcm for o in render.outputs[:4]]
    assert not np.array_equal(waves[0][:500], waves[1][:500])
    hold = render.output("phase:hold")
    assert hold.loop == (1, hold.frames) and hold.frames == round(0.5 * 22050) + 1
    assert np.array_equal(hold.pcm[0], hold.pcm[-1])  # the lead-in frame is the loop's last frame


def test_kit_instruments_in_layers(project: Project) -> None:
    sfx, findings = load(project, "sfx", "x", "name: x\nkit: t\nlayers:\n  - { instrument: p, pitch: E5 }\n  - { instrument: k }\n")
    assert sfx is not None, findings
    assert sfx.layers[0].inst.duty == 0.25 and sfx.layers[1].inst.is_drum


def test_extends_template(project: Project) -> None:
    write(project, "sfx", "gun_base", "name: gun_base\ntemplate: true\nduration: 0.3\ncategory: weapon\nlayers:\n  - { id: shot, osc: noise, env: [0, 0.1, 0, 0.05] }\n  - { id: body, osc: sine, pitch: C3 }\n")
    sfx, findings = load(project, "sfx", "rifle", "name: rifle\nextends: gun_base\nremove: [body]\nlayers:\n  - { id: shot, gain: -3 }\n  - { id: click, osc: pulse, pitch: C6, env: [0, 0.02, 0, 0.01] }\n")
    assert sfx is not None, findings
    assert sfx.category == "weapon" and [layer.id for layer in sfx.layers] == ["shot", "click"]
    assert sfx.layers[0].inst.gain == -3 and sfx.layers[0].inst.wave == "noise"


@pytest.mark.parametrize(
    ("text", "rule", "where"),
    [
        ("name: x\npreset: boing\n", "E013", "preset"),
        ("name: x\nlayers: []\n", "E013", "layers"),
        ("name: x\nlayers:\n  - { osc: sine, pitch: [[0.1, C4], [0, C5]] }\n", "E013", "layers.0.pitch.1"),
        ("name: x\nlayers:\n  - { osc: sine, pitch: H9 }\n", "E013", "layers.0.pitch"),
        ("name: x\nduration: 0\nlayers:\n  - { osc: sine }\n", "E013", "duration"),
        ("name: x\nlayers:\n  - { osc: sine, instrument: z }\n", "E013", "layers.0.instrument"),
        ("name: x\nlayers:\n  - { osc: sine }\nvariations: { count: 99 }\n", "E013", "variations.count"),
        ("name: x\nlayers:\n  - { osc: sine }\nphases:\n  go: { duration: 0.2, loop: true, crossfade: 0.15 }\n", "E008", "phases.go"),
        ("name: x\nlayers:\n  - { osc: sine }\ninstruments:\n  p: { osc: sine }\n", "E009", "instruments"),
        ("name: x\nextends: nothing\nlayers:\n  - { osc: sine }\n", "E001", "extends"),
        ("name: y\nlayers:\n  - { osc: sine }\n", "E001", "name"),
        ("name: x\nwobble: 1\nlayers:\n  - { osc: sine }\n", "E013", "wobble"),
    ],
)
def test_sfx_errors(project: Project, text: str, rule: str, where: str) -> None:
    sfx, findings = load(project, "sfx", "x", text)
    assert sfx is None
    assert any(f.rule == rule and f.where == where for f in findings), [(f.rule, f.where, f.message) for f in findings]


def test_errors_carry_line_numbers(project: Project) -> None:
    _, findings = load(project, "sfx", "x", "name: x\nduration: 0.2\nlayers:\n  - osc: sine\n    env: [1, 2]\n")
    found: list[Finding] = [f for f in findings if f.rule == "E013"]
    assert found and found[0].line == 5  # the env line


def test_open_mode_inline_instruments(tmp_path: Path) -> None:
    from conftest import make_project

    project = make_project(tmp_path, 'mode = "open"\n')
    sfx, findings = load(project, "sfx", "x", "name: x\ninstruments:\n  z: { osc: saw }\nlayers:\n  - { instrument: z, pitch: A4 }\n")
    assert sfx is not None, findings
    assert rules(findings) == []


def test_room_send_and_tail_trim(tmp_path: Path) -> None:
    from conftest import CONFIG, make_project

    text = "name: tick\ncategory: ui\nduration: 0.05\nlayers:\n  - { osc: pulse, pitch: C6, env: [0.001, 0.02, 0.0, 0.01] }\n"
    lengths = {}
    for label, extra in [("wet", ""), ("trim", "tail_trim_db = -45\n"), ("dry", "\n[room]\nui = 0\n")]:
        config = CONFIG.replace("room_decay = 0.2\n", "room_decay = 0.2\n" + extra) if label == "trim" else CONFIG + extra
        (tmp_path / label).mkdir()
        project = make_project(tmp_path / label, config)
        sfx, findings = load(project, "sfx", "tick", text)
        assert sfx is not None, findings
        lengths[label] = render_asset(sfx, project).main.frames
    assert lengths["dry"] == round(0.05 * 22050) < lengths["trim"] < lengths["wet"]
    (tmp_path / "field").mkdir()
    project = make_project(tmp_path / "field")
    sfx, _ = load(project, "sfx", "tick", text + "room: 0\n")
    assert sfx is not None and render_asset(sfx, project).main.frames == lengths["dry"]


def test_preview_lists_each_layers_levels(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#1: per-layer peak / loudness / crest in `segan preview --json`, to find what makes a sound peaky (W001)."""
    from conftest import run_json

    text = BASIC.replace("length: 0.1\n", "length: 0.1\n  - { id: crack, osc: noise, env: [0, 0.01, 0, 0.01], start: 0.004 }\n")
    text += "variations: { count: 2, pitch: 1 }\n"
    write(project, "sfx", "zap", text)
    monkeypatch.chdir(project.root)
    code, data = run_json(["preview", "zap"], capsys)
    assert code == 0, data
    outputs = data["outputs"][0]["outputs"]
    layers = outputs[0]["analysis"]["layers"]
    assert [entry["layer"] for entry in layers] == ["tone", "crack", "(dry mix)"]
    assert layers[1]["start_s"] == 0.004 and set(layers[0]) == {"layer", "start_s", "peak_db", "lufs", "crest_db"}
    assert layers[1]["crest_db"] > layers[0]["crest_db"]  # a 10 ms noise click is far peakier than the tone
    assert layers[2]["peak_db"] >= max(layers[0]["peak_db"], layers[1]["peak_db"]) - 6.1
    assert outputs[1]["output"] == "variation:1" and outputs[1]["analysis"]["layers"][0]["layer"] == "tone"


def test_variation_timing_moves_layer_starts(project: Project) -> None:
    """#3: `variations.timing` jitters each layer's start per variation (seeded; the main sound stays put)."""
    from segan.sfxrender import variation_layers

    text = BASIC + "  - { id: pop, osc: noise, env: [0, 0.01, 0, 0.01], start: 0.05 }\nvariations: { count: 3, timing: 0.02 }\n"
    sfx, findings = load(project, "sfx", "zap", text)
    assert sfx is not None, findings
    assert sfx.variations.timing == 0.02
    starts = [[layer.start for layer in variation_layers("zap", sfx.layers, sfx.variations, i)] for i in (1, 2, 3)]
    assert all(s[0] >= 0 and 0.03 <= s[1] <= 0.07 for s in starts)
    assert len({tuple(s) for s in starts}) == 3  # each variation lands differently
    assert starts == [[layer.start for layer in variation_layers("zap", sfx.layers, sfx.variations, i)] for i in (1, 2, 3)]
    render = render_asset(sfx, project, use_cache=False)
    assert not np.array_equal(render.output("variation:1").pcm, render.output("variation:2").pcm)
    plain, _ = load(project, "sfx", "zap", text.replace(", timing: 0.02", ""))
    assert plain is not None and variation_layers("zap", plain.layers, plain.variations, 1) == plain.layers
    _, findings = load(project, "sfx", "zap", text.replace("timing: 0.02", "timing: 1"))
    assert rules(findings) == ["E013"]


def test_pitch_cents_offsets(project: Project) -> None:
    """#6: a note with a cents offset ("A4+15c") in `pitch:` and its keyframes, e.g. for detuned copies of a layer."""
    text = "name: d\nduration: 0.2\nlayers:\n  - { id: a, osc: saw, pitch: A4 }\n  - { id: b, osc: saw, pitch: A4+15c }\n  - { id: c, osc: saw, pitch: [[0, C6-30c], [0.1, C6+0.5c]] }\n"
    sfx, findings = load(project, "sfx", "d", text)
    assert sfx is not None, findings
    assert sfx.layers[1].pitch == ((0.0, 69.15),)
    assert sfx.layers[2].pitch == ((0.0, 83.7), (0.1, 84.005))
    for bad in ("A4+15", "A4+1300c", "H4+10c"):
        _, findings = load(project, "sfx", "d", text.replace("A4+15c", bad))
        assert rules(findings) == ["E013"], bad
