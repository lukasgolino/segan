"""Independent time-stretch and pitch-shift for recorded sounds: a phase vocoder with identity phase locking
(Laroche & Dolson 1999), then polyphase resampling for the pitch.

Varispeed (reading a sample faster or slower) couples pitch and length: a lion pitched down an octave also
lasts twice as long and sounds slowed down. Here `stretch(x, rate, factor, semitones)` changes the length by
`factor` and the pitch by `semitones` independently: the vocoder stretches by `factor * ratio` (ratio = the pitch
ratio), and resampling by `ratio` brings the length back while moving the pitch.

Deterministic: fixed frame sizes, numpy FFTs, `resample_poly` with a rational ratio; no randomness. Each frame's
instantaneous frequency comes from a second analysis frame a few samples later, so the analysis hop can be any
(rounded) position. Transients smear a little at large factors (no transient detection), as with any vocoder.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from segan.dsp import Signal

MAX_FACTOR = 4.0
MAX_SEMITONES = 24.0


def frame_size(rate: int) -> int:
    """FFT size: the power of two nearest 46 ms (2048 at 44.1 kHz)."""
    return 1 << max(8, round(math.log2(0.046 * rate)))


def time_stretch(x: Signal, rate: int, factor: float) -> Signal:
    """`x` made `factor` times longer (exactly round(len(x) * factor) samples) at the same pitch."""
    n_out = round(len(x) * factor)
    if factor == 1.0 or len(x) == 0:
        return np.array(x, dtype=np.float64, copy=True)[:n_out]
    size = frame_size(rate)
    hop = size // 4  # synthesis hop
    probe = size // 8  # second analysis frame, for the instantaneous frequency (< size / 4: unambiguous)
    window = np.hanning(size + 1)[:-1]  # periodic Hann
    pad = size
    xp = np.concatenate([np.zeros(pad), np.asarray(x, dtype=np.float64), np.zeros(pad + size + probe)])
    frames = (n_out + 2 * pad) // hop + 1
    out = np.zeros(frames * hop + size)
    norm = np.zeros(frames * hop + size)
    bins = np.arange(size // 2 + 1)
    expected = 2.0 * np.pi * bins / size  # radians per sample at each bin's centre
    phase_out = np.zeros(size // 2 + 1)
    last = len(xp) - size - probe
    for k in range(frames):
        centre_out = k * hop + size / 2  # in padded output samples
        start = int(round(pad + (centre_out - pad) / factor - size / 2))
        start = min(max(start, 0), last)
        spec = np.fft.rfft(xp[start : start + size] * window)
        ahead = np.fft.rfft(xp[start + probe : start + probe + size] * window)
        mag, phase = np.abs(spec), np.angle(spec)
        deviation = np.angle(ahead) - phase - expected * probe
        deviation = (deviation + np.pi) % (2.0 * np.pi) - np.pi
        omega = expected + deviation / probe
        if k == 0:
            phase_out = phase.copy()
        else:
            phase_out = phase_out + omega * hop
        # identity phase locking: every bin keeps its phase offset to the spectral peak it belongs to
        peaks = np.flatnonzero((mag[1:-1] > mag[:-2]) & (mag[1:-1] >= mag[2:])) + 1
        if len(peaks):
            edges = (peaks[:-1] + peaks[1:]) // 2
            owner = peaks[np.searchsorted(edges, bins, side="right")]
            locked = phase_out[owner] + phase - phase[owner]
            phase_out = np.where(np.isin(bins, peaks), phase_out, locked)
        phase_out = (phase_out + np.pi) % (2.0 * np.pi) - np.pi  # keep the numbers small (and exact across runs)
        frame = np.fft.irfft(mag * np.exp(1j * phase_out), size) * window
        out[k * hop : k * hop + size] += frame
        norm[k * hop : k * hop + size] += window**2
    out = out[pad : pad + n_out]
    norm = norm[pad : pad + n_out]
    return np.asarray(out / np.maximum(norm, 1e-3), dtype=np.float64)


def resample(x: Signal, ratio: float) -> Signal:
    """`x` read `ratio` times faster (len / ratio samples; pitch up by `ratio`), band-limited."""
    if ratio == 1.0 or len(x) == 0:
        return np.array(x, dtype=np.float64, copy=True)
    from scipy.signal import resample_poly

    frac = Fraction(ratio).limit_denominator(1000)
    return np.asarray(resample_poly(x, frac.denominator, frac.numerator), dtype=np.float64)


def stretch(x: Signal, rate: int, factor: float = 1.0, semitones: float = 0.0) -> Signal:
    """`x` made `factor` times longer and `semitones` higher, independently: exactly round(len(x) * factor) samples."""
    n_out = round(len(x) * factor)
    if semitones == 0.0:
        return time_stretch(x, rate, factor)
    ratio = 2.0 ** (semitones / 12.0)
    y = resample(time_stretch(x, rate, factor * ratio), ratio)
    if len(y) < n_out:
        y = np.concatenate([y, np.zeros(n_out - len(y))])
    return y[:n_out]
