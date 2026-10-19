import numpy as np

from segan.analysis import (
    dc_offset,
    integrated_lufs,
    leading_silence,
    max_momentary_lufs,
    onsets,
    seam_click,
    spectral_centroid,
    true_peak_db,
    yin,
)


def sine(freq: float, seconds: float, rate: int = 48000, amp: float = 1.0) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(int(seconds * rate)) / rate)


def test_lufs_matches_bs1770_reference() -> None:
    # a 0 dBFS 997 Hz sine in one channel reads -3.01 LUFS
    assert abs(integrated_lufs(sine(997, 3), 48000) + 3.01) < 0.05
    assert abs(integrated_lufs(sine(997, 3, 44100, 0.5), 44100) + 9.03) < 0.05


def test_momentary_of_a_short_sound_is_quieter_than_its_level() -> None:
    short = sine(997, 0.1, 44100)
    assert max_momentary_lufs(short, 44100) < -3.01 - 5


def test_true_peak_sees_intersample_peaks() -> None:
    rate = 44100
    x = np.sin(2 * np.pi * (rate / 4) * np.arange(4000) / rate + np.pi / 4)  # samples at 0.707
    assert abs(float(np.max(np.abs(x))) - 0.7071) < 1e-3
    assert true_peak_db(x) > -0.5


def test_yin_finds_pitch() -> None:
    track = yin(sine(220, 0.5, 44100) + 0.3 * sine(440, 0.5, 44100), 44100)
    voiced = track.hz[track.hz > 0]
    assert len(voiced) > 10 and abs(float(np.median(voiced)) - 220) < 1


def test_onsets() -> None:
    rate = 44100
    x = np.zeros(rate)
    for at in (0.1, 0.4, 0.7):
        i = int(at * rate)
        x[i : i + 4000] = sine(800, 4000 / rate, rate)[:4000] * np.linspace(1, 0, 4000) ** 3
    found = onsets(x, rate)
    assert len(found) == 3 and all(abs(a - b) < 0.03 for a, b in zip(found, (0.1, 0.4, 0.7)))


def test_leading_silence_and_dc() -> None:
    x = np.concatenate([np.zeros(441), sine(500, 0.1, 44100)])
    assert abs(leading_silence(x, 44100) - 0.01) < 0.001
    assert dc_offset(x + 0.1) > 0.09


def test_seam_click() -> None:
    rate = 44100
    smooth = sine(441, 1.0, rate)  # exactly 441 cycles in a second: loops cleanly
    assert seam_click(smooth, 0, rate) < 0.001
    cut = sine(440, 1.0, rate)  # 440.0 cycles + a broken phase
    broken = cut[: rate - 37]
    assert seam_click(broken, 0, len(broken)) > 0.02


def test_yin_can_ignore_a_dyads_common_period() -> None:
    dyad = sine(1567.98, 0.5, 44100) + sine(2093.0, 0.5, 44100)  # G6 + C7: common period ~ C5, which nobody hears
    assert np.any(yin(dyad, 44100).hz > 0)
    assert not np.any(yin(dyad, 44100, require_fundamental=True).hz > 0)
    track = yin(sine(220, 0.5, 44100) + 0.3 * sine(440, 0.5, 44100), 44100, require_fundamental=True)
    assert abs(float(np.median(track.hz[track.hz > 0])) - 220) < 1


def test_centroid_is_not_dominated_by_a_noise_floor() -> None:
    rate = 44100
    noise = np.random.default_rng(1).standard_normal(rate) * 10 ** (-50 / 20)
    assert spectral_centroid(sine(100, 1.0, rate) + noise, rate) < 300
    assert 900 < spectral_centroid(sine(1000, 1.0, rate), rate) < 1100
