import numpy as np
import pytest

from segan.analysis import harmonic_aliasing_db, peak_db
from segan.dsp import midi_to_hz_scalar
from segan.kitshow import aliasing_of
from segan.patch import Env, Instrument
from segan.synth import Context, adsr, render_note

STEADY = Env(0.0, 0.0, 1.0, 0.0)


def test_adsr_shape() -> None:
    env = adsr(Env(0.01, 0.05, 0.5, 0.2), 1000, 3000, 10000, declick=False)
    assert env[0] == 0.0 and abs(env[100] - 1.0) < 1e-12
    assert abs(env[700] - 0.5) < 1e-12  # sustain
    assert env[999] == 0.5 and env[1500] < 0.5 and env[2999] < 1e-6 and env.min() >= 0


@pytest.mark.parametrize("wave", ["saw", "pulse"])
def test_aliasing_below_threshold_at_c7_with_2x(wave: str) -> None:
    inst = Instrument(wave=wave, duty=0.25, env=STEADY)
    assert (value := aliasing_of(inst, 96, Context(oversample=2))) is not None and value < -50.0


def test_oversampling_reduces_aliasing() -> None:
    inst = Instrument(wave="saw", env=STEADY)
    low = aliasing_of(inst, 96, Context(oversample=1))
    high = aliasing_of(inst, 96, Context(oversample=4))
    assert low is not None and high is not None and high < low - 15


def test_triangle_is_cleaner_than_saw() -> None:
    tri = aliasing_of(Instrument(wave="triangle", env=STEADY), 84, Context())
    saw = aliasing_of(Instrument(wave="saw", env=STEADY), 84, Context())
    assert tri is not None and saw is not None and tri < saw


def test_notes_have_the_right_pitch_and_length() -> None:
    ctx = Context()
    out = render_note(Instrument(wave="sine", env=Env(0.01, 0.0, 1.0, 0.1)), ctx, 69, 0.5)
    assert len(out) == round((0.5 + 0.1) * ctx.rate)
    spectrum = np.abs(np.fft.rfft(out[2000:2000 + 16384] * np.hanning(16384)))
    peak_hz = np.argmax(spectrum) * ctx.rate / 16384
    assert abs(peak_hz - 440) < 3


@pytest.mark.parametrize("drum", ["kick", "snare", "hat", "clap", "tom", "cymbal"])
def test_drums_sound_and_decay(drum: str) -> None:
    inst = Instrument(source="drum", wave=drum)
    out = render_note(inst, Context(), 60, 0.05)
    assert peak_db(out) > -30
    tail = out[-200:]
    assert np.max(np.abs(tail)) < 0.05 * np.max(np.abs(out))


def test_renders_are_deterministic() -> None:
    inst = Instrument(wave="pulse", duty=0.3, vibrato=(6.0, 0.2, 0.0), arp=(0, 4, 7))
    a = render_note(inst, Context(), 64, 0.3, seed=5)
    assert np.array_equal(a, render_note(inst, Context(), 64, 0.3, seed=5))
    noisy = Instrument(wave="noise")
    assert not np.array_equal(render_note(noisy, Context(), 60, 0.1, seed=1), render_note(noisy, Context(), 60, 0.1, seed=2))


def test_pulse_has_no_dc() -> None:
    out = render_note(Instrument(wave="pulse", duty=0.125, env=STEADY), Context(), 60, 0.5, length=0.5)
    assert abs(out.mean()) < 0.01


def test_harmonic_aliasing_metric_sees_naive_aliasing() -> None:
    rate = 44100
    f0 = midi_to_hz_scalar(96)
    t = np.arange(rate) / rate
    naive = 2 * ((t * f0) % 1.0) - 1  # a naive saw aliases badly
    assert harmonic_aliasing_db(naive, rate, f0) > -30


@pytest.mark.parametrize("wave", ["sine", "fm", "saw"])
def test_unison_starts_at_full_level(wave: str) -> None:
    """Two detuned voices must not start in antiphase (they'd swell in over 1 / (2 * beat))."""
    one = Instrument(wave=wave, env=STEADY)
    two = Instrument(wave=wave, env=STEADY, unison=2, detune=5.0)
    ctx = Context()
    a, b = (render_note(i, ctx, 84, 0.5, length=0.5)[: ctx.rate // 50] for i in (one, two))
    assert peak_db(b) > peak_db(a) - 3.0
