"""The shared mix bus ([mix] in segan.toml): the same room, tone, crush, loudness and limiter for every
asset, so a project's sounds belong together (SEGAN's equivalent of PAGAN's project camera and light).

Order: tracks/layers -> room -> tone (brightness, warmth) -> crush -> loudness normalisation -> true-peak limiter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from segan.analysis import frames_of, loudness, true_peak_envelope
from segan.dsp import Signal, biquad, db_to_gain, exp2, noise, round12, seed_of
from segan.patch import Crush
from segan.project import MixConfig
from segan.synth import crush as crush_signal

PRE_DELAY = 0.012
TAIL_FLOOR_DB = -70.0


@lru_cache(maxsize=16)
def room_ir(rate: int, decay: float, channels: int) -> Signal:
    """The project's room: early reflections plus a noise tail falling 60 dB over `decay` seconds that gets
    darker as it fades. Each channel's tail is decorrelated (stereo width). Unit energy per channel."""
    from scipy.signal import sosfilt

    n = round((decay + PRE_DELAY) * rate)
    t = np.arange(n, dtype=np.float64) / rate
    out = np.zeros((n, channels))
    envelope = exp2(-math.log2(1000.0) * np.clip(t - PRE_DELAY, 0.0, None) / decay)
    envelope[t < PRE_DELAY] = 0.0
    for ch in range(channels):
        bright = noise(n, seed_of("room", ch))
        dark = np.asarray(sosfilt(biquad("lp", 2200.0, 0.7, rate), bright), dtype=np.float64)
        mixture = np.clip(t / decay, 0.0, 1.0)
        tail = envelope * (bright * (1.0 - mixture) + dark * mixture * 1.6)
        for delay, gain in ((0.011, 0.6), (0.017, -0.45), (0.023, 0.4), (0.031, -0.3), (0.041, 0.25)):
            tap = round((delay + ch * 0.0013) * rate)
            if tap < n:
                tail[tap] += gain * 4.0
        out[:, ch] = tail / math.sqrt(float((tail**2).sum()))
    return round12(out)


def room_tail(mix: MixConfig) -> float:
    """Seconds the room keeps ringing after the dry sound stops."""
    return mix.room_decay + PRE_DELAY if mix.room > 0 else 0.0


def apply_room(x: Signal, mix: MixConfig) -> Signal:
    """Dry + room * wet. The output is longer than the input by the room's tail."""
    from scipy.signal import fftconvolve

    data = frames_of(x)
    if mix.room <= 0:
        return data
    ir = room_ir(mix.sample_rate, mix.room_decay, data.shape[1])
    wet = np.stack([fftconvolve(data[:, ch], ir[:, ch]) for ch in range(data.shape[1])], axis=1)
    out = np.zeros_like(wet)
    out[: len(data)] = data
    return out + mix.room * 0.5 * wet


def apply_tone(x: Signal, mix: MixConfig) -> Signal:
    """Brightness: a high/low tilt around 1 kHz (+ = brighter). Warmth: low-mid body (+ = warmer, darker top)."""
    from scipy.signal import sosfilt

    if not mix.brightness and not mix.warmth:
        return x
    rate = mix.sample_rate
    stages = []
    if mix.brightness:
        stages += [biquad("highshelf", 2500.0, 0.7, rate, mix.brightness), biquad("lowshelf", 300.0, 0.7, rate, -mix.brightness / 2)]
    if mix.warmth:
        stages += [biquad("peak", 250.0, 0.8, rate, mix.warmth), biquad("highshelf", 7000.0, 0.7, rate, -mix.warmth / 2)]
    return np.asarray(sosfilt(np.vstack(stages), frames_of(x), axis=0), dtype=np.float64)


def apply_crush(x: Signal, mix: MixConfig) -> Signal:
    if not mix.crush_bits and not mix.crush_rate:
        return x
    data = frames_of(x)
    settings = Crush(mix.crush_bits, mix.crush_rate)
    return np.stack([crush_signal(data[:, ch], settings, mix.sample_rate) for ch in range(data.shape[1])], axis=1)


def bus(x: Signal, mix: MixConfig) -> Signal:
    """Room, tone and crush: everything every asset shares before loudness."""
    return apply_crush(apply_tone(apply_room(x, mix), mix), mix)


def trim_tail(x: Signal, keep: int, rate: int) -> Signal:
    """Cut the silent end after `keep` frames (the room tail below -70 dB of the peak), with a 5 ms fade."""
    data = frames_of(x)
    if len(data) <= keep:
        return data
    level = np.abs(data).max(axis=1)
    peak = float(level.max())
    if peak <= 0:
        return data[:keep]
    loud = np.flatnonzero(level[keep:] > peak * 10 ** (TAIL_FLOOR_DB / 20))
    end = keep + (int(loud[-1]) + 1 if len(loud) else 0)
    out = data[:end].copy()
    fade = min(round(0.005 * rate), end - keep)
    if fade > 0:
        out[end - fade :] *= np.linspace(1.0, 0.0, fade, endpoint=False)[:, None] ** 2
    return out


# --- loudness and limiting ----------------------------------------------------------------------


@dataclass(frozen=True)
class Level:
    measured: float  # LUFS before normalisation
    gain_db: float  # normalisation gain
    target: float | None  # None = not normalised
    limiting_db: float  # most gain reduction the limiter applied
    lufs: float  # after normalisation and limiting


def limiter_gain(x: Signal, ceiling_db: float, rate: int) -> Signal:
    """Per-frame gain that keeps the true peak under the ceiling: required gain, held over a 4 ms look-ahead
    window, then averaged over the same window (never above the requirement, no clicks)."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    ceiling = db_to_gain(ceiling_db)
    peaks = true_peak_envelope(x)
    required = np.minimum(1.0, ceiling / np.maximum(peaks, 1e-12))
    if required.min() >= 1.0:
        return np.ones(len(peaks))
    width = 2 * round(0.004 * rate) + 1
    held = minimum_filter1d(required, width, mode="nearest")
    smooth = uniform_filter1d(held, width, mode="nearest")
    return np.asarray(np.minimum(smooth, required), dtype=np.float64)


def finish(x: Signal, rate: int, target: float | None, measure: str, ceiling_db: float, gain: Signal | None = None) -> tuple[Signal, Level, Signal]:
    """Normalise to `target` LUFS (None = keep the level) and limit to the true-peak ceiling. Returns the signal,
    the level report and the gain curve applied (so stems can follow the mix exactly)."""
    data = frames_of(x)
    measured = loudness(data, rate, measure)
    gain_db = 0.0 if target is None or measured <= -100 else target - measured
    scaled = data * db_to_gain(gain_db)
    curve = limiter_gain(scaled, ceiling_db, rate) if gain is None else gain
    limited = scaled * curve[:, None]
    excess = float(true_peak_envelope(limited).max()) / db_to_gain(ceiling_db) if len(limited) else 0.0
    if excess > 1.0:  # inter-sample overshoot left after smoothing: scale it away
        curve = curve / excess
        limited = scaled * curve[:, None]
    reduction = -20.0 * math.log10(float(curve.min())) if len(curve) and curve.min() > 0 else 0.0
    level = Level(measured, gain_db, target, reduction, loudness(limited, rate, measure))
    return limited, level, curve * db_to_gain(gain_db)
