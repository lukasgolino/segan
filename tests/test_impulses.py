"""#4: `osc: impulses`, sparse random impulses (crackle, debris, bubbles)."""

from __future__ import annotations

import numpy as np
import pytest

from segan.dsp import hz_to_midi
from segan.kitshow import aliasing_of, context_for
from segan.models import Impulses
from segan.patch import Env, Instrument, Report, parse_patch
from segan.project import Project
from segan.render import render_asset
from segan.synth import Context, impulses

from conftest import load

RATE = 8000


def onsets(x: np.ndarray) -> np.ndarray:
    """Sample indices where a run of non-zero samples starts."""
    active = np.concatenate([[0], (x != 0).astype(np.int64)])
    return np.flatnonzero(np.diff(active) == 1)


def test_density_is_a_poisson_rate() -> None:
    x = impulses(Impulses(density=10.0), 100 * RATE, RATE, 440.0, 7)
    count = len(onsets(x))  # ~1000 expected; a few overlapping clicks merge
    assert 850 < count < 1100
    gaps = np.diff(onsets(x)) / RATE
    assert 0.06 < float(np.median(gaps)) < 0.08  # exponential gaps: median = ln 2 / density = 0.069


def test_deterministic_and_seeded() -> None:
    spec = Impulses(shape="bubble")
    a = impulses(spec, RATE, RATE, 440.0, 1)
    assert np.array_equal(a, impulses(spec, RATE, RATE, 440.0, 1))
    assert not np.array_equal(a, impulses(spec, RATE, RATE, 440.0, 2))
    assert np.array_equal(a[:4000], impulses(spec, 4000, RATE, 440.0, 1))  # a shorter note is a prefix


def test_click_level_range() -> None:
    x = impulses(Impulses(density=50.0, level=(0.25, 0.25)), 10 * RATE, RATE, 440.0, 3)
    starts = onsets(x)
    assert len(starts) > 300 and float(np.abs(x).max()) <= 0.5 + 1e-9
    assert float(np.mean(x != 0)) < 0.15  # 1-2 ms bursts, not a continuous noise


def test_tick_pitch_and_bubble_rise() -> None:
    rate = 44100
    one = (round(hz_to_midi(1000.0), 9), round(hz_to_midi(1000.0), 9))
    tick = impulses(Impulses(density=0.5, shape="tick", pitch=one, decay=0.5), 20 * rate, rate, 440.0, 4)
    start = int(onsets(tick)[0])
    grain = tick[start : start + rate // 2]
    spectrum = np.abs(np.fft.rfft(grain * np.hanning(len(grain))))
    assert abs(np.argmax(spectrum) * rate / len(grain) - 1000.0) < 10.0
    bubble = impulses(Impulses(density=0.5, shape="bubble", pitch=one, decay=0.5), 20 * rate, rate, 440.0, 4)
    start = int(onsets(bubble)[0])
    grain = bubble[start : start + rate // 2]

    def crossings(seg: np.ndarray) -> int:
        return int(np.count_nonzero(np.diff(np.signbit(seg))))

    first, last = crossings(grain[:4410]), crossings(grain[-4410 - 2000 : -2000])
    assert 1.2 < last / first < 1.35  # rises ~30% over the decay


def test_density_follows_the_curve() -> None:
    n = 20 * RATE
    density = np.concatenate([np.ones(n // 2), np.zeros(n // 2)])
    x = impulses(Impulses(density=40.0), n, RATE, 440.0, 5, density)
    starts = onsets(x)
    assert len(starts) > 300 and starts.max() < n // 2 + RATE // 100


def test_patch_fields_and_errors() -> None:
    report = Report(None)
    inst = parse_patch({"osc": "impulses", "impulses": {"density": 12, "shape": "tick", "pitch": ["C5", 2000], "decay": 0.05, "level": [0.2, 0.8]}},
                       report, "E013", "x")  # fmt: skip
    assert report.findings == [] and inst is not None and inst.impulses is not None
    assert inst.impulses == Impulses(12.0, "tick", (72.0, round(hz_to_midi(2000.0), 9)), 0.05, (0.2, 0.8))
    assert parse_patch({"osc": "impulses"}, report, "E013", "x") is not None and report.findings == []
    for data, where in [
        ({"osc": "sine", "impulses": {}}, "x.impulses"),
        ({"osc": "impulses", "impulses": {"shape": "pop"}}, "x.impulses.shape"),
        ({"osc": "impulses", "impulses": {"pitch": [3000, 300]}}, "x.impulses.pitch"),
        ({"osc": "impulses", "impulses": {"level": [0.5, 2]}}, "x.impulses.level"),
        ({"osc": "impulses", "impulses": {"density": 0}}, "x.impulses.density"),
        ({"osc": "impulses", "impulses": {"rate": 3}}, "x.impulses.rate"),
    ]:
        report = Report(None)
        assert parse_patch(data, report, "E013", "x") is None
        assert [f.where for f in report.findings] == [where], data


def test_osc_change_drops_the_block() -> None:
    report = Report(None)
    base = parse_patch({"osc": "impulses", "impulses": {"shape": "bubble"}}, report, "E013", "x")
    inst = parse_patch({"osc": "sine"}, report, "E013", "x", base=base)
    assert report.findings == [] and inst is not None and inst.impulses is None
    assert "impulses" not in inst.to_yaml_fields()


def test_no_aliasing_measure() -> None:
    assert aliasing_of(Instrument(wave="impulses", env=Env(0.0, 0.0, 1.0, 0.0)), 96, Context()) is None


SFX = """\
name: sink
category: sfx
duration: 1.0
layers:
  - id: bubbles
    osc: impulses
    impulses: { density: 60, shape: bubble, pitch: [400, 1600], decay: 0.03 }
    env: [0.001, 0, 1, 0.05]
    gain: {gain}
"""


@pytest.mark.parametrize("distort", [False, True])
def test_gain_keyframes_thin_the_density(project: Project, distort: bool) -> None:
    from segan.sfxrender import render_layer

    text = SFX.replace("{gain}", "[[0, 0], [0.5, 0], [0.55, -60], [1, -60]]")
    if distort:
        text += "    distort: 0.3\n"
    sfx, findings = load(project, "sfx", "sink", text)
    assert sfx is not None, findings
    ctx = context_for(project.config.mix)
    x, _ = render_layer(sfx.layers[0], ctx, 1.0, 9, 0.0, 0.0)
    flat, _ = load(project, "sfx", "sink", SFX.replace("{gain}", "0") + ("    distort: 0.3\n" if distort else ""))
    assert flat is not None
    y, _ = render_layer(flat.layers[0], ctx, 1.0, 9, 0.0, 0.0)
    half = ctx.rate // 2
    tail = slice(round(0.6 * ctx.rate), ctx.rate)
    assert np.allclose(x[: half - 2000], y[: half - 2000], atol=1e-9)  # same impulses while the gain is 0 dB
    assert float(np.abs(x[tail]).max()) < 1e-3 * float(np.abs(y[tail]).max())  # -60 dB: level x density


def test_sfx_renders(project: Project) -> None:
    sfx, findings = load(project, "sfx", "sink", SFX.replace("{gain}", "0"))
    assert findings == [] and sfx is not None
    main = render_asset(sfx, project, use_cache=False).main
    assert main.frames > 0 and abs(float(main.level["lufs"]) + 14.0) < 1.0  # type: ignore[arg-type]
