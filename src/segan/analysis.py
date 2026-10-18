"""Measurements an agent compares instead of listening: peak, true peak, loudness (ITU-R BS.1770 LUFS),
onsets, pitch (YIN), spectral centroid, DC offset, leading silence, loop-seam clicks and aliasing.

Signals are float arrays at the output rate, shape (frames,) or (frames, channels).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from segan.dsp import Signal, oversample, round12

SILENCE_DB = -120.0


def frames_of(x: Signal) -> Signal:
    return np.asarray(x, dtype=np.float64).reshape(len(x), -1)


def mono(x: Signal) -> Signal:
    return np.asarray(frames_of(x).mean(axis=1), dtype=np.float64)


def to_db(value: float, floor: float = SILENCE_DB) -> float:
    return max(floor, 20.0 * math.log10(value)) if value > 0 else floor


def peak_db(x: Signal) -> float:
    return to_db(float(np.max(np.abs(x)))) if len(x) else SILENCE_DB


def true_peak_envelope(x: Signal) -> Signal:
    """Per-frame inter-sample peak (4x oversampled), max over channels."""
    data = frames_of(x)
    peaks = np.zeros(len(data))
    for ch in range(data.shape[1]):
        up = np.abs(oversample(data[:, ch], 4))
        up = up[: len(data) * 4]
        if len(up) < len(data) * 4:
            up = np.pad(up, (0, len(data) * 4 - len(up)))
        peaks = np.maximum(peaks, up.reshape(-1, 4).max(axis=1))
    return np.asarray(np.maximum(peaks, np.abs(data).max(axis=1)), dtype=np.float64)


def true_peak_db(x: Signal) -> float:
    return to_db(float(true_peak_envelope(x).max())) if len(x) else SILENCE_DB


# --- loudness (BS.1770-4) ----------------------------------------------------------------------


def k_weight_sos(rate: int) -> Signal:
    """BS.1770 K-weighting (pre-filter shelf + RLB high-pass) for any sample rate; matches the spec's 48 kHz
    coefficients exactly."""
    k = math.tan(math.pi * 1681.974450955533 / rate)
    q = 0.7071752369554196
    vh = 10 ** (3.999843853973347 / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0, 1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    k = math.tan(math.pi * 38.13547087602444 / rate)
    q = 0.5003270373238773
    a0 = 1 + k / q + k * k
    high = [1.0, -2.0, 1.0, 1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return round12([shelf, high])


def k_weight(x: Signal, rate: int) -> Signal:
    from scipy.signal import sosfilt

    return np.asarray(sosfilt(k_weight_sos(rate), frames_of(x), axis=0), dtype=np.float64)


def _block_power(weighted: Signal, rate: int, window: float, hop: float) -> Signal:
    """Mean square per block, summed over channels (all channel weights 1: mono/stereo)."""
    size, step = round(window * rate), round(hop * rate)
    n = len(weighted)
    if n < size:
        weighted = np.pad(weighted, ((0, size - n), (0, 0)))
        n = size
    power = (weighted**2).sum(axis=1)
    csum = np.concatenate([[0.0], np.cumsum(power)])
    starts = np.arange(0, n - size + 1, step)
    return np.asarray((csum[starts + size] - csum[starts]) / size, dtype=np.float64)


def _lufs(power: Signal | float) -> Signal:
    p = np.maximum(np.asarray(power, dtype=np.float64), 1e-20)
    return -0.691 + 10.0 * np.log10(p)


def integrated_lufs(x: Signal, rate: int) -> float:
    """Gated integrated loudness (400 ms blocks, 75% overlap, -70 LUFS absolute and -10 LU relative gates)."""
    if len(x) == 0:
        return SILENCE_DB
    blocks = _block_power(k_weight(x, rate), rate, 0.4, 0.1)
    loud = _lufs(blocks)
    gated = blocks[loud > -70.0]
    if len(gated) == 0:
        return SILENCE_DB
    relative = float(_lufs(gated.mean())) - 10.0
    final = blocks[(loud > -70.0) & (loud > relative)]
    return float(_lufs(final.mean())) if len(final) else SILENCE_DB


def momentary_lufs(x: Signal, rate: int) -> Signal:
    """Momentary loudness (400 ms window) every 100 ms; short sounds are measured as one zero-padded window."""
    return _lufs(_block_power(k_weight(x, rate), rate, 0.4, 0.1)) if len(x) else np.array([SILENCE_DB])


def short_term_lufs(x: Signal, rate: int) -> Signal:
    """Short-term loudness (3 s window) every 100 ms."""
    return _lufs(_block_power(k_weight(x, rate), rate, 3.0, 0.1)) if len(x) else np.array([SILENCE_DB])


def max_momentary_lufs(x: Signal, rate: int) -> float:
    return float(momentary_lufs(x, rate).max())


def loudness(x: Signal, rate: int, measure: str) -> float:
    """"integrated" (music) or "momentary" (one-shot SFX: the loudest 400 ms)."""
    return integrated_lufs(x, rate) if measure == "integrated" else max_momentary_lufs(x, rate)


# --- time-domain checks ------------------------------------------------------------------------


def dc_offset(x: Signal) -> float:
    return float(np.abs(frames_of(x).mean(axis=0)).max()) if len(x) else 0.0


def leading_silence(x: Signal, rate: int, relative_db: float = -30.0) -> float:
    """Seconds before the signal first reaches `relative_db` below its peak."""
    level = np.abs(frames_of(x)).max(axis=1) if len(x) else np.zeros(0)
    peak = float(level.max()) if len(level) else 0.0
    if peak <= 0:
        return len(level) / rate
    first = int(np.argmax(level >= peak * 10 ** (relative_db / 20)))
    return first / rate


def clipped_samples(pcm: np.ndarray) -> int:
    return int(np.count_nonzero((pcm >= 32767) | (pcm <= -32767)))


def seam_click(x: Signal, start: int, end: int) -> float:
    """How much worse the loop splice (sample end-1 -> start) is than the signal's own sample-to-sample
    changes around it: the excess second difference at the splice, as a fraction of full scale."""
    data = frames_of(x)
    if end - start < 8:
        return 0.0
    worst = 0.0
    for ch in range(data.shape[1]):
        loop = data[start:end, ch]
        joined = np.concatenate([loop[-64:], loop[:64]])
        d2 = np.abs(np.diff(joined, 2))
        splice = float(d2[62:64].max())  # second differences that straddle the splice
        around = float(np.concatenate([d2[:58], d2[68:]]).max()) if len(d2) > 70 else 0.0
        worst = max(worst, splice - around)
    return max(0.0, worst)


# --- spectral ----------------------------------------------------------------------------------


def spectral_centroid(x: Signal, rate: int) -> float:
    m = mono(x)
    if len(m) < 64 or not np.any(m):
        return 0.0
    size = min(len(m), 1 << 16)
    spectrum = np.abs(np.fft.rfft(m[:size] * np.hanning(size)))
    freqs = np.fft.rfftfreq(size, 1.0 / rate)
    total = float(spectrum.sum())
    return float((spectrum * freqs).sum() / total) if total > 0 else 0.0


def onsets(x: Signal, rate: int, max_count: int = 64) -> list[float]:
    """Onset times (s) from positive spectral flux with an adaptive threshold."""
    m = mono(x)
    size, hop = 1024, 256
    if len(m) < size:
        m = np.pad(m, (0, size - len(m)))
    count = 1 + (len(m) - size) // hop
    window = np.hanning(size)
    frames = np.lib.stride_tricks.sliding_window_view(m, size)[::hop][:count] * window
    mags = np.log1p(np.abs(np.fft.rfft(frames, axis=1)) * 10.0)
    flux = np.concatenate([[mags[0].sum()], np.maximum(np.diff(mags, axis=0), 0.0).sum(axis=1)])
    if not np.any(flux):
        return []
    from scipy.ndimage import maximum_filter1d, uniform_filter1d

    local = uniform_filter1d(flux, 9, mode="nearest") * 1.5 + 0.05 * float(flux.max())
    peaks = (flux == maximum_filter1d(flux, 5, mode="nearest")) & (flux > local)
    times = [round(float(i * hop + size // 2) / rate, 4) for i in np.flatnonzero(peaks)]  # frame centres
    out: list[float] = []
    for time in times:  # at most one onset per 40 ms
        if not out or time - out[-1] >= 0.04:
            out.append(time)
    return out[:max_count]


@dataclass(frozen=True)
class PitchTrack:
    times: Signal  # frame centres (s)
    hz: Signal  # 0 where unvoiced


def yin(x: Signal, rate: int, fmin: float = 50.0, fmax: float = 4000.0, hop: float = 0.0, threshold: float = 0.15) -> PitchTrack:
    """YIN fundamental-frequency estimate per frame (de Cheveigne & Kawahara 2002), FFT autocorrelation."""
    m = mono(x)
    hop = hop or max(0.01, len(m) / rate / 1200)  # about one estimate per pixel column of a listen sheet
    tau_max = int(rate / fmin)
    tau_min = max(2, int(rate / fmax))
    size = 2 * tau_max
    step = max(1, round(hop * rate))
    if len(m) < size:
        return PitchTrack(np.zeros(0), np.zeros(0))
    starts = np.arange(0, len(m) - size, step)
    if len(starts) == 0:
        return PitchTrack(np.zeros(0), np.zeros(0))
    frames = np.lib.stride_tricks.sliding_window_view(m, size)[starts]
    nfft = 1 << (2 * size - 1).bit_length()
    w = tau_max  # integration window: the first half of each frame
    cross = np.fft.irfft(np.conj(np.fft.rfft(frames[:, :w], nfft, axis=1)) * np.fft.rfft(frames, nfft, axis=1), nfft, axis=1)[:, : w + 1]
    energy = np.cumsum(frames**2, axis=1)
    before = np.concatenate([np.zeros((len(frames), 1)), energy[:, :w]], axis=1)
    # d(tau) = sum_j (x_j - x_{j+tau})^2 over the window
    d = energy[:, w - 1][:, None] + (energy[:, w - 1 : 2 * w] - before) - 2 * cross
    d[:, 0] = 0.0
    cumulative = np.cumsum(d[:, 1:], axis=1) / np.arange(1, tau_max + 1)
    cmnd = np.ones_like(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        cmnd[:, 1:] = np.where(cumulative > 0, d[:, 1:] / cumulative, 1.0)
    hz = np.zeros(len(frames))
    loud = (frames**2).mean(axis=1) > 1e-6
    for i in range(len(frames)):
        if not loud[i]:
            continue
        row = cmnd[i]
        below = np.flatnonzero(row[tau_min : tau_max] < threshold)
        if len(below) == 0:
            continue
        tau = tau_min + int(below[0])
        while tau + 1 < tau_max and row[tau + 1] < row[tau]:
            tau += 1
        if 1 <= tau < tau_max:  # parabolic interpolation
            a, b, c = row[tau - 1], row[tau], row[tau + 1]
            denom = a - 2 * b + c
            shift = 0.5 * (a - c) / denom if denom != 0 else 0.0
            hz[i] = rate / (tau + shift)
    times = (starts + size / 2) / rate
    return PitchTrack(times, hz)


def harmonic_aliasing_db(x: Signal, rate: int, f0: float) -> float:
    """Energy away from the harmonics of `f0` relative to the energy on them (a steady tone's aliasing)."""
    from scipy.signal.windows import blackmanharris

    m = mono(x)
    if len(m) < 4096:
        return SILENCE_DB
    m = m[: 1 << int(math.log2(len(m)))]
    spectrum = np.abs(np.fft.rfft(m * blackmanharris(len(m)))) ** 2
    freqs = np.fft.rfftfreq(len(m), 1.0 / rate)
    k = np.round(freqs / f0)
    width = max(8.0, 6.0 * rate / len(m))
    near = (np.abs(freqs - k * f0) < width) & (k >= 1)
    tonal = float(spectrum[near].sum())
    stray = float(spectrum[~near & (freqs > 20.0)].sum())
    return 10.0 * math.log10(stray / tonal) if tonal > 0 and stray > 0 else SILENCE_DB
