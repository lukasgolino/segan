import math

import numpy as np

from segan.dsp import decimate, exp2, midi_to_hz, noise, poly_blep, seed_of, sin_turns, uniform


def test_sin_table_is_accurate() -> None:
    phase = np.linspace(0, 3, 10007)
    assert np.max(np.abs(sin_turns(phase) - np.sin(2 * np.pi * phase))) < 1e-6


def test_exp2_is_accurate_and_exact_on_integers() -> None:
    x = np.linspace(-20, 20, 4001)
    assert np.max(np.abs(exp2(x) / 2.0**x - 1)) < 1e-8
    assert exp2(np.array([0.0, 1.0, -3.0])).tolist() == [1.0, 2.0, 0.125]


def test_midi_to_hz() -> None:
    assert abs(float(midi_to_hz(69.0)) - 440.0) < 1e-9
    assert abs(float(midi_to_hz(60.0)) - 261.6255653) < 1e-5


def test_noise_is_deterministic_and_offset_consistent() -> None:
    a = noise(1000, 42)
    assert np.array_equal(a, noise(1000, 42))
    assert np.array_equal(a[500:], noise(500, 42, offset=500))
    assert not np.array_equal(a, noise(1000, 43))
    assert -1.0 <= a.min() and a.max() < 1.0
    assert abs(a.mean()) < 0.1 and 0.25 < a.var() < 0.42


def test_seeds_and_uniform_are_stable() -> None:
    assert seed_of("coin", 1) == seed_of("coin", 1) != seed_of("coin", 2)
    values = [uniform(seed_of("x"), i) for i in range(100)]
    assert all(0 <= v < 1 for v in values) and len(set(values)) == 100


def test_poly_blep_is_zero_away_from_the_edge() -> None:
    t = np.array([0.0, 0.005, 0.5, 0.995])
    dt = np.full(4, 0.01)
    out = poly_blep(t, dt)
    assert out[2] == 0.0 and out[0] == -1.0 and out[1] < 0 < out[3]


def test_decimate_keeps_dc_and_low_tones() -> None:
    rate = 88200
    t = np.arange(rate) / rate
    x = 0.5 + 0.25 * np.sin(2 * math.pi * 1000 * t)
    y = decimate(x, 2)
    assert len(y) == rate // 2
    mid = y[1000:-1000]
    assert abs(mid.mean() - 0.5) < 1e-3 and abs(mid.max() - 0.75) < 2e-3
