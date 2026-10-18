"""Deterministic DSP primitives: tables for sin/exp2, a counter-based PRNG, band-limiting corrections,
biquad coefficients and the fixed decimator.

Determinism rules (PLAN.md §8):
- no `numpy.random` (its streams may change between numpy versions): noise is a splitmix64 hash of the
  sample index, so any sample can be computed on its own and the result never depends on the CPU;
- no per-sample `numpy.sin/exp/exp2` (SIMD code paths can differ by an ulp between machines): per-sample
  sin and exp2 come from tables built once with Python's `math` and rounded to 12 decimals (PAGAN's trick),
  read with linear interpolation; envelopes are polynomials (exact IEEE arithmetic);
- scalar coefficients (filters, gains) are computed with `math` and rounded to 12 decimals.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray

Signal = NDArray[np.float64]

TABLE_BITS = 12
TABLE_SIZE = 1 << TABLE_BITS


def _round(value: float) -> float:
    return round(value, 12)


_SIN_TABLE = np.array([_round(math.sin(2 * math.pi * i / TABLE_SIZE)) for i in range(TABLE_SIZE + 1)])
_EXP2_TABLE = np.array([_round(2.0 ** (i / TABLE_SIZE)) for i in range(TABLE_SIZE + 1)])


def _lookup(table: Signal, position: Signal) -> Signal:
    """Linear interpolation into a table of TABLE_SIZE + 1 entries; `position` in [0, TABLE_SIZE)."""
    index = np.floor(position)
    frac = position - index
    i = index.astype(np.int64)
    np.clip(i, 0, TABLE_SIZE - 1, out=i)
    return table[i] + (table[i + 1] - table[i]) * frac


def sin_turns(phase: Signal | float) -> Signal:
    """sin(2*pi*phase), with the phase in turns (cycles)."""
    p = np.asarray(phase, dtype=np.float64)
    flat = p.reshape(-1)
    return _lookup(_SIN_TABLE, (flat - np.floor(flat)) * TABLE_SIZE).reshape(p.shape)


def cos_turns(phase: Signal | float) -> Signal:
    return sin_turns(np.asarray(phase, dtype=np.float64) + 0.25)


def exp2(x: Signal | float) -> Signal:
    """2**x for arrays: integer part exactly (ldexp), fractional part from a table."""
    v = np.asarray(x, dtype=np.float64)
    flat = v.reshape(-1)
    whole = np.floor(flat)
    out = np.ldexp(_lookup(_EXP2_TABLE, (flat - whole) * TABLE_SIZE), whole.astype(np.int32))
    return out.reshape(v.shape)


def db_to_gain(db: float) -> float:
    return _round(10.0 ** (db / 20.0))


def gain_to_db(gain: float) -> float:
    return -math.inf if gain <= 0 else 20.0 * math.log10(gain)


def midi_to_hz(midi: Signal | float, tuning: float = 440.0) -> Signal:
    return tuning * exp2((np.asarray(midi, dtype=np.float64) - 69.0) / 12.0)


def midi_to_hz_scalar(midi: float, tuning: float = 440.0) -> float:
    return _round(tuning * 2.0 ** ((midi - 69.0) / 12.0))


def hz_to_midi(hz: float, tuning: float = 440.0) -> float:
    return 69.0 + 12.0 * math.log2(hz / tuning)


# --- noise ------------------------------------------------------------------------------------

_MASK = (1 << 64) - 1


def seed_of(*parts: object) -> int:
    """A stable 64-bit seed from any parts (asset name, layer index, user seed...)."""
    digest = hashlib.blake2b("\x1f".join(str(p) for p in parts).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def noise(n: int, seed: int, offset: int = 0) -> Signal:
    """White noise in [-1, 1): splitmix64 of the sample counter, so sample i is the same however it's computed."""
    if n <= 0:
        return np.zeros(0)
    counter = np.arange(offset + 1, offset + n + 1, dtype=np.uint64)
    return noise_at(counter, seed)


def noise_at(counter: NDArray[np.uint64], seed: int) -> Signal:
    """The noise value for each counter (used by sample-and-hold noise)."""
    with np.errstate(over="ignore"):
        z = np.uint64(seed & _MASK) + counter * np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return (z >> np.uint64(11)).astype(np.float64) * (2.0 / 9007199254740992.0) - 1.0


def uniform(seed: int, index: int) -> float:
    """One deterministic number in [0, 1) (for variations: pick a value per parameter)."""
    return float(noise_at(np.array([index + 1], dtype=np.uint64), seed)[0]) * 0.5 + 0.5


# --- band-limiting ------------------------------------------------------------------------------


def poly_blep(t: Signal, dt: Signal) -> Signal:
    """2-point PolyBLEP residual for a unit step at phase 0 (t in [0, 1), dt = phase increment)."""
    out = np.zeros_like(t)
    lo = t < dt
    x = t[lo] / dt[lo]
    out[lo] = x + x - x * x - 1.0
    hi = t > 1.0 - dt
    y = (t[hi] - 1.0) / dt[hi]
    out[hi] = y * y + y + y + 1.0
    return out


def poly_blamp(t: Signal, dt: Signal) -> Signal:
    """2-point PolyBLAMP residual for a unit slope change at phase 0 (in units of one sample's slope)."""
    out = np.zeros_like(t)
    lo = t < dt
    x = t[lo] / dt[lo] - 1.0
    out[lo] = -x * x * x / 3.0
    hi = t > 1.0 - dt
    y = (t[hi] - 1.0) / dt[hi] + 1.0
    out[hi] = y * y * y / 3.0
    return out


# --- filters -----------------------------------------------------------------------------------


def biquad(kind: str, cutoff: float, q: float, rate: float, gain_db: float = 0.0) -> NDArray[np.float64]:
    """RBJ cookbook biquad as one scipy `sos` row: lp, hp, bp, lowshelf, highshelf, peak."""
    cutoff = min(max(cutoff, 10.0), 0.45 * rate)
    w0 = 2 * math.pi * cutoff / rate
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    a = 10 ** (gain_db / 40)
    if kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        den = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        den = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bp":
        b = [alpha, 0.0, -alpha]
        den = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "peak":
        b = [1 + alpha * a, -2 * cw, 1 - alpha * a]
        den = [1 + alpha / a, -2 * cw, 1 - alpha / a]
    elif kind in ("lowshelf", "highshelf"):
        sq = 2 * math.sqrt(a) * alpha
        sign = 1 if kind == "lowshelf" else -1
        b = [
            a * ((a + 1) - sign * (a - 1) * cw + sq),
            sign * 2 * a * ((a - 1) - sign * (a + 1) * cw),
            a * ((a + 1) - sign * (a - 1) * cw - sq),
        ]
        den = [(a + 1) + sign * (a - 1) * cw + sq, -sign * 2 * ((a - 1) + sign * (a + 1) * cw), (a + 1) + sign * (a - 1) * cw - sq]
    else:
        raise ValueError(f"unknown filter kind {kind!r}")
    a0 = den[0]
    row = [_round(v / a0) for v in b] + [1.0] + [_round(v / a0) for v in den[1:]]
    return np.array([row], dtype=np.float64)


def resonance_to_q(resonance: float) -> float:
    """Resonance 0..1 -> Q 0.707..10 (exponential, so the middle of the range is musically useful)."""
    return _round(0.7071 * (14.14 ** resonance))


# --- decimation --------------------------------------------------------------------------------


@lru_cache(maxsize=8)
def decimator_taps(factor: int) -> NDArray[np.float64]:
    """Linear-phase FIR for decimating by `factor`: passband to 0.9 x the output Nyquist, ~-90 dB stopband."""
    from scipy.signal import firwin

    taps = firwin(96 * factor + 1, 0.9 / factor, window=("kaiser", 8.6))
    return np.round(np.asarray(taps, dtype=np.float64), 12)  # resample_poly scales by `up` itself


def decimate(x: Signal, factor: int) -> Signal:
    """Band-limit and downsample by `factor` (output sample i = input sample i * factor, no delay)."""
    if factor == 1:
        return x
    from scipy.signal import resample_poly

    return np.asarray(resample_poly(x, 1, factor, window=decimator_taps(factor)), dtype=np.float64)


@lru_cache(maxsize=8)
def interpolator_taps(factor: int) -> NDArray[np.float64]:
    """Short interpolation FIR (12 taps per phase, as BS.1770 suggests for true-peak meters)."""
    from scipy.signal import firwin

    return np.round(np.asarray(firwin(12 * factor + 1, 0.95 / factor, window=("kaiser", 6.0)), dtype=np.float64), 12)


def oversample(x: Signal, factor: int) -> Signal:
    """Upsample by `factor` (for true-peak measurement)."""
    if factor == 1:
        return x
    from scipy.signal import resample_poly

    return np.asarray(resample_poly(x, factor, 1, window=interpolator_taps(factor)), dtype=np.float64)
