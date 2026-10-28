"""#88: `bandwidth` (octaves) on band-pass and notch filters, overriding `resonance`."""

import math
from typing import Any

import numpy as np
import pytest
from scipy.signal import sosfreqz

from segan.dsp import bandwidth_to_q, biquad
from segan.fx import apply_fx
from segan.patch import Instrument, Report, parse_patch
from segan.synth import Context, render_note

CTX = Context(rate=22050, oversample=2)
RATE = 48000.0


def patch(data: dict[str, Any]) -> Instrument:
    report = Report(None)
    inst = parse_patch(data, report, "E005", "x")
    assert inst is not None, [f.message for f in report.findings]
    return inst


def errors(data: dict[str, Any]) -> list[str]:
    report = Report(None)
    assert parse_patch(data, report, "E005", "x") is None
    return [f.message for f in report.findings]


def width_octaves(kind: str, octaves: float, stages: int, centre: float = 1000.0) -> float:
    """Octaves between the -3 dB points: of the pass band (bp) or of the notch."""
    sos = np.vstack([biquad(kind, centre, bandwidth_to_q(octaves, kind, stages), RATE)] * stages)
    freqs = np.geomspace(centre / 16, centre * 16, 200001)
    _, h = sosfreqz(sos, worN=freqs, fs=RATE)
    db = 20 * np.log10(np.maximum(np.abs(h), 1e-12))
    inside = np.where(db >= -3.0103)[0] if kind == "bp" else np.where(db <= -3.0103)[0]
    return math.log2(freqs[inside[-1]] / freqs[inside[0]])


@pytest.mark.parametrize("kind", ["bp", "notch"])
@pytest.mark.parametrize("stages", [1, 2])
@pytest.mark.parametrize("octaves", [0.1, 0.3, 1.0, 2.0])
def test_bandwidth_is_the_width_between_the_3db_points(kind: str, stages: int, octaves: float) -> None:
    assert abs(width_octaves(kind, octaves, stages) - octaves) < 0.01 * octaves + 0.002


def test_one_octave_is_q_sqrt2() -> None:
    assert abs(bandwidth_to_q(1.0, "bp") - math.sqrt(2)) < 1e-12


def band_energy(x: np.ndarray, rate: int, lo: float, hi: float) -> float:
    spectrum = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1 / rate)
    return float(spectrum[(freqs >= lo) & (freqs <= hi)].sum() / spectrum.sum())


def test_narrow_band_keeps_noise_near_the_centre() -> None:
    """The space-io zip: resonance 0.75 (Q 5.2, about 0.28 octaves) still leaves half the noise power in its 6 dB/oct
    skirts outside +/- 0.1 octave; bandwidth 0.1 at 24 dB/oct keeps nine tenths inside."""
    wide = render_note(patch({"osc": "noise", "filter": {"type": "bp", "cutoff": 2000, "resonance": 0.75}}), CTX, 60.0, 0.5)
    narrow = render_note(patch({"osc": "noise", "filter": {"type": "bp", "cutoff": 2000, "bandwidth": 0.1, "slope": 24}}), CTX, 60.0, 0.5)
    lo, hi = 2000 * 2**-0.1, 2000 * 2**0.1
    assert band_energy(narrow, CTX.rate, lo, hi) > 0.85
    assert band_energy(wide, CTX.rate, lo, hi) < 0.5


def test_bandwidth_overrides_resonance() -> None:
    a = render_note(patch({"osc": "noise", "filter": {"type": "bp", "cutoff": 2000, "bandwidth": 0.5}}), CTX, 60.0, 0.2)
    b = render_note(patch({"osc": "noise", "filter": {"type": "bp", "cutoff": 2000, "bandwidth": 0.5, "resonance": 0.9}}), CTX, 60.0, 0.2)
    assert np.array_equal(a, b)


def test_without_bandwidth_nothing_changes() -> None:
    inst = patch({"osc": "noise", "filter": {"type": "bp", "cutoff": 2000, "resonance": 0.6, "slope": 24}})
    assert inst.filter is not None and inst.filter.bandwidth is None
    assert "bandwidth" not in inst.to_yaml_fields()["filter"]


def test_bandwidth_errors() -> None:
    assert "bp or notch only" in errors({"osc": "noise", "filter": {"type": "lp", "bandwidth": 1}})[0]
    assert "0.05-4 octaves" in errors({"osc": "noise", "filter": {"type": "bp", "bandwidth": 0}})[0]
    assert "0.05-4 octaves" in errors({"osc": "noise", "filter": {"type": "notch", "bandwidth": "wide"}})[0]
    assert "bp or notch only" in errors({"osc": "noise", "fx": [{"filter": {"type": "hp", "bandwidth": 1}}]})[0]
    assert "filter.bandwidth must be" in errors({"osc": "noise", "fx": [{"filter": {"type": "bp", "bandwidth": 9}}]})[0]


def test_fx_filter_takes_bandwidth() -> None:
    x = render_note(patch({"osc": "noise"}), CTX, 60.0, 0.5)
    plain = apply_fx(x, patch({"osc": "noise", "fx": [{"filter": {"type": "bp", "cutoff": 2000}}]}).fx, CTX.rate, 0.5, 1, 60.0)
    narrow = apply_fx(x, patch({"osc": "noise", "fx": [{"filter": {"type": "bp", "cutoff": 2000, "bandwidth": 0.2}}]}).fx, CTX.rate, 0.5, 1, 60.0)
    lo, hi = 2000 * 2**-0.25, 2000 * 2**0.25
    assert band_energy(narrow, CTX.rate, lo, hi) > band_energy(plain, CTX.rate, lo, hi) + 0.2
