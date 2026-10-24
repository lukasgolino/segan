"""Rendering of the instrument models in models.py (one note, at the oversampled rate, before the amplitude
envelope). The same determinism rules as synth.py: sin/exp2 from tables, noise from a counter hash, tables
built once and rounded to 12 decimals.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from segan.dsp import Signal, biquad, cos_turns, exp2, noise, round12, seed_of, sin_turns, smooth_noise, uniform
from segan.models import (
    BODIES,
    FORMANTS,
    MATERIALS,
    Additive,
    Bowed,
    Formant,
    Modal,
    Model,
    Pluck,
    Supersaw,
    Wavetable,
    body_for,
    voice_for,
)
from segan.patch import Instrument

C4_HZ = 261.6255653


def _sos(x: Signal, sos: Signal) -> Signal:
    from scipy.signal import sosfilt

    return np.asarray(sosfilt(sos, x), dtype=np.float64)


def _freq(semis: Signal, cents: Signal | float, tuning: float) -> Signal:
    return tuning * exp2((semis + np.asarray(cents) / 100.0 - 69.0) / 12.0)


def _phase(inc: Signal, start: float = 0.0) -> Signal:
    out = np.empty_like(inc)
    out[0] = start
    np.cumsum(inc[:-1], out=out[1:])
    out[1:] += start
    return out


def _saw(inc: Signal, start: float = 0.0) -> Signal:
    from segan.dsp import poly_blep

    phase = _phase(inc, start)
    frac = phase - np.floor(phase)
    return 2.0 * frac - 1.0 - poly_blep(frac, np.minimum(inc, 0.5))


def _body(x: Signal, name: str, rate: float) -> Signal:
    peaks, lowpass = BODIES[name]
    stages = [biquad("peak", f, q, rate, db) for f, db, q in peaks] + [biquad("lp", lowpass, 0.7, rate)]
    return _sos(x, np.vstack(stages))


def drift_cents(n: int, seed: int, rate: float, cents: float, measure: bool) -> Signal | float:
    """A player's slow pitch wander (about three turns a second), in cents."""
    if measure or cents <= 0:
        return 0.0
    return cents * smooth_noise(n, seed, rate, 3.0)


def render_model(model: Model, inst: Instrument, ctx_rate: int, tuning: float, measure: bool, n: int, n_gate: int, t: Signal, semis: Signal,
                 seed: int) -> Signal:  # fmt: skip
    if isinstance(model, Pluck):
        return _pluck(model, inst, ctx_rate, tuning, n, semis, seed)
    if isinstance(model, Bowed):
        return _bowed(model, inst, ctx_rate, tuning, measure, n, t, semis, seed)
    if isinstance(model, Additive):
        f0 = float(_freq(semis[:1], 0.0, tuning)[0])
        return partial_sum(model.partials, model.stretch, inst, ctx_rate, tuning, n, t, semis, f0)
    if isinstance(model, Wavetable):
        return _wavetable(model, inst, ctx_rate, tuning, n, n_gate, t, semis)
    if isinstance(model, Formant):
        return _formant(model, inst, ctx_rate, tuning, measure, n, t, semis, seed)
    if isinstance(model, Modal):
        return _modal(model, inst, ctx_rate, tuning, measure, n, t, semis, seed)
    return _supersaw(model, inst, ctx_rate, tuning, n, semis, seed)


# --- additive ------------------------------------------------------------------------------------

_LOG2_10 = round(math.log2(10.0), 12)


def partial_sum(partials: tuple[tuple[float, float, float | None], ...], stretch: float, inst: Instrument, rate: int, tuning: float, n: int,
                t: Signal, semis: Signal, f0: float) -> Signal:  # fmt: skip
    """Sum of sine partials (ratio, amplitude, decay at C4 or None) over the note's pitch curve; partials fade out
    as they near Nyquist (no aliasing), decays are keytracked (high notes ring shorter)."""
    voices = inst.unison
    out = np.zeros(n)
    nyquist = 0.45 * rate
    norm = 1.0 / math.sqrt(sum(a * a for _, a, _ in partials) or 1.0)
    keytrack = math.sqrt(C4_HZ / max(f0, 1.0))
    for k in range(voices):
        cents = inst.detune * ((2.0 * k / (voices - 1) - 1.0) if voices > 1 else 1.0)
        freq = _freq(semis, cents, tuning)
        base = _phase(freq / rate)
        for ratio, amp, decay in partials:
            r = ratio * math.sqrt(1.0 + stretch * ratio * ratio) if stretch else ratio
            top = r * freq
            if float(top.min()) >= nyquist:
                continue
            fade = np.clip((nyquist - top) / (0.05 * rate), 0.0, 1.0)
            wave = sin_turns(base * r + 0.25 * k / voices)
            level = amp * fade
            if decay is not None:
                level = level * exp2(np.maximum(-1000.0, -3.0 * _LOG2_10 * t / (decay * keytrack)))
            out += level * wave
    return out * norm / (math.sqrt(voices) if voices > 1 else 1.0)


# --- modal ---------------------------------------------------------------------------------------


def _modal(model: Modal, inst: Instrument, rate: int, tuning: float, measure: bool, n: int, t: Signal, semis: Signal, seed: int) -> Signal:
    modes, default_decay = MATERIALS[model.material]
    decay = model.decay if model.decay is not None else default_decay
    hard = model.strike
    partials = tuple((r, a * r ** (-(1.0 - hard) * 1.2), decay * d) for r, a, d in modes)
    f0 = float(_freq(semis[:1], 0.0, tuning)[0])
    out = partial_sum(partials, 0.0, inst, rate, tuning, n, t, semis, f0)
    if not measure and hard > 0:  # the mallet: a short noise thwack, brighter for harder mallets
        click = min(n, round(0.004 * rate))
        burst = noise(click, seed_of(seed, "mallet")) * (1.0 - np.arange(click) / click) ** 2
        cutoff = min(0.45 * rate, f0 * (3.0 + 20.0 * hard))
        thwack = np.zeros(n)
        thwack[:click] = _sos(burst, biquad("lp", cutoff, 0.7, rate))
        out = out + 0.25 * hard * thwack
    return out


# --- pluck ---------------------------------------------------------------------------------------


def _pluck(model: Pluck, inst: Instrument, rate: int, tuning: float, n: int, semis: Signal, seed: int) -> Signal:
    """Karplus-Strong: a noise burst one period long (low-passed by `brightness`, comb-filtered at the pick point)
    circulating in a delay loop of one period with a two-point damping filter. The loop gain is set so the
    fundamental falls 60 dB in `decay` seconds (shorter for higher notes by `damping`). Vectorised in chunks
    shorter than the shortest period, so every sample only reads samples already computed."""
    voices = inst.unison
    out = np.zeros(n)
    s = 0.5 * (1.0 - model.brightness) * 0.98 + 0.01  # damping filter: (1 - s) + s z^-1
    for k in range(voices):
        cents = inst.detune * ((2.0 * k / (voices - 1) - 1.0) if voices > 1 else 1.0)
        freq = np.clip(_freq(semis, cents, tuning), 20.0, 0.2 * rate)
        period = rate / freq
        f0 = float(freq[0])
        p0 = max(2, round(rate / f0))
        burst = noise(p0, seed_of(seed, "pluck", k))
        burst = _sos(burst, biquad("lp", min(0.45 * rate, f0 * (1.5 + 40.0 * model.brightness ** 2)), 0.6, rate))
        pick = round(model.pick * p0)
        if pick > 0:
            burst[pick:] -= burst[:-pick] if pick < p0 else 0.0
        burst -= burst.mean()
        excitation = np.zeros(n)
        excitation[: min(n, p0)] = burst[: min(n, p0)]
        decay = model.decay * (C4_HZ / f0) ** model.damping
        w = freq / rate
        loss = np.sqrt((1.0 - s) ** 2 + s * s + 2.0 * s * (1.0 - s) * cos_turns(w))
        gain = np.minimum(0.99999, exp2(-3.0 * _LOG2_10 * (period / rate) / decay) / loss)
        delay = period - s
        pad = int(math.ceil(float(delay.max()))) + 3
        y = np.zeros(n + pad)
        chunk = max(1, int(float(delay.min())) - 1)
        index = np.arange(n, dtype=np.float64)
        for a in range(0, n, chunk):
            b = min(n, a + chunk)
            pos = index[a:b] - delay[a:b] + pad
            i0 = np.floor(pos).astype(np.int64)
            fr = pos - i0
            v0 = y[i0] + (y[i0 + 1] - y[i0]) * fr
            v1 = y[i0 - 1] + (y[i0] - y[i0 - 1]) * fr
            y[a + pad : b + pad] = excitation[a:b] + gain[a:b] * ((1.0 - s) * v0 + s * v1)
        out += y[pad:]
    if model.body != "none":
        out = _body(out, model.body, rate)
    out = _sos(out, biquad("hp", 20.0, 0.7, rate))
    return out * 2.0 / (math.sqrt(voices) if voices > 1 else 1.0)


# --- bowed ---------------------------------------------------------------------------------------


def _bowed(model: Bowed, inst: Instrument, rate: int, tuning: float, measure: bool, n: int, t: Signal, semis: Signal, seed: int) -> Signal:
    """Each player: a band-limited saw (a bowed string's Helmholtz motion) with its own slow pitch drift and onset
    (a few ms apart); then bow noise (stronger at the attack) and the body's resonances."""
    voices = inst.unison
    out = np.zeros(n)
    for k in range(voices):
        cents = inst.detune * ((2.0 * k / (voices - 1) - 1.0) if voices > 1 else 1.0)
        wander = drift_cents(n, seed_of(seed, "drift", k), rate, model.drift, measure)
        freq = _freq(semis, np.asarray(cents) + wander, tuning)
        player = _saw(freq / rate, uniform(seed_of(seed, "phase"), k) if not measure else 0.25 * k / voices)
        if voices > 1 and not measure:  # players don't start together
            lag = round(uniform(seed_of(seed, "lag"), k) * 0.012 * rate)
            player = np.concatenate([np.zeros(lag), player[: n - lag]]) * np.clip((t - lag / rate) / 0.03, 0.0, 1.0)
        out += player
    out /= math.sqrt(voices) if voices > 1 else 1.0
    if not measure and model.bow > 0:
        hiss = noise(n, seed_of(seed, "bow")) * model.bow * 0.12 * (1.0 + 3.0 * exp2(-t / 0.05))
        out = out + _sos(hiss, biquad("hp", 1500.0, 0.7, rate))
    return _body(out, body_for(model.body, inst.range), rate) * 0.6


# --- supersaw ------------------------------------------------------------------------------------

SUPERSAW_OFFSETS = (-1.0, -0.62, -0.3, 0.0, 0.3, 0.62, 1.0)


def _supersaw(model: Supersaw, inst: Instrument, rate: int, tuning: float, n: int, semis: Signal, seed: int) -> Signal:
    out = np.zeros(n)
    for k, offset in enumerate(SUPERSAW_OFFSETS):
        level = 1.0 if offset == 0 else model.mix
        freq = _freq(semis, offset * model.spread + inst.detune, tuning)
        out += level * _saw(freq / rate, uniform(seed_of(seed, "supersaw"), k))
    f0 = float(_freq(semis[:1], 0.0, tuning)[0])
    out = _sos(out, biquad("hp", max(20.0, f0 * 0.9), 0.7, rate))  # the stack's low-end mud, as the original's filter does
    return out / math.sqrt(1.0 + 6.0 * model.mix**2)


# --- wavetable -----------------------------------------------------------------------------------

TABLE_N = 2048
HARMONICS = 64
LEVELS = (64, 48, 32, 24, 16, 12, 8, 6, 4, 3, 2, 1)


def _interp_frames(keys: list[np.ndarray], count: int) -> np.ndarray:
    """`count` frames spread evenly over the key spectra (linear blends between neighbours)."""
    out = []
    for i in range(count):
        x = i / (count - 1) * (len(keys) - 1)
        j = min(int(x), len(keys) - 2)
        w = x - j
        out.append(keys[j] * (1.0 - w) + keys[j + 1] * w)
    return np.array(out)


def _formant_spectrum(vowel: str, f_ref: float = 130.0) -> np.ndarray:
    freqs, dbs, bws = FORMANTS["tenor"][vowel]
    k = np.arange(1, HARMONICS + 1, dtype=np.float64)
    env = np.zeros(HARMONICS)
    for f, db, bw in zip(freqs, dbs, bws, strict=True):
        env += 10.0 ** (db / 20.0) / (1.0 + ((k * f_ref - f) / (bw * 1.5)) ** 2)
    return env / k**0.5


def _table_spectra(name: str) -> np.ndarray:
    """Complex harmonic coefficients (frames x HARMONICS): real = sine, imaginary = cosine part."""
    k = np.arange(1, HARMONICS + 1, dtype=np.float64)
    odd = (k % 2 == 1).astype(np.float64)
    if name == "analog":
        saw, square, tri, sine = 1.0 / k, odd / k, odd * (-1.0) ** ((k - 1) // 2) / k**2, (k == 1).astype(np.float64)
        return _interp_frames([saw, square, tri, sine], 8).astype(np.complex128)
    if name == "pulse":
        frames = [np.sin(np.pi * k * d) / k for d in np.linspace(0.5, 0.04, 8)]
        return np.array(frames).astype(np.complex128)
    if name == "vocal":
        return _interp_frames([_formant_spectrum(v) for v in ("a", "e", "i", "o", "u")], 9).astype(np.complex128)
    if name == "glass":
        frames = []
        for i in range(8):
            spacing = 2 + i
            frames.append(((k - 1) % spacing == 0) * k ** (-0.3) * np.exp(-k / (8.0 + 6.0 * i)) + (k == 1) * 0.5)
        return np.array(frames).astype(np.complex128)
    if name == "digital":
        frames = []
        for i in range(8):
            gate = np.array([uniform(seed_of("digital", i), int(h)) < 0.25 + 0.06 * i for h in k], dtype=np.float64)
            frames.append(gate * k ** (-0.6 + 0.08 * i) + (k == 1))
        return np.array(frames).astype(np.complex128)
    if name == "organ":
        settings = ("008000000", "008800000", "008080000", "888000000", "868800000", "888880000", "888888000", "888888888")
        harmonic_of = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 8}  # drawbar index -> harmonic (the sub-octave drawbars have none)
        frames = []
        for setting in settings:
            amps = np.zeros(HARMONICS)
            for index, digit in enumerate(setting):
                if index in harmonic_of and digit != "0":
                    amps[harmonic_of[index] - 1] += 10.0 ** ((int(digit) - 8) * 3.0 / 20.0)
            frames.append(amps)
        return np.array(frames).astype(np.complex128)
    if name == "harmonic":
        frames = [0.3 / k + np.exp(-(((k - h) / 1.2) ** 2)) for h in range(1, 17)]
        return np.array(frames).astype(np.complex128)
    if name == "sync":  # a saw hard-synced at rising ratios, from its spectrum
        frames = []
        x = np.arange(4096) / 4096.0
        for ratio in np.linspace(1.0, 6.0, 9):
            wave = 2.0 * ((x * ratio) % 1.0) - 1.0
            spec = np.fft.rfft(wave)[1 : HARMONICS + 1] / 2048.0
            frames.append(-spec.imag + 1j * spec.real)
        return np.array(frames)
    raise ValueError(f"unknown wavetable {name!r}")


@lru_cache(maxsize=16)
def wavetable(name: str) -> dict[int, np.ndarray]:
    """Mip-mapped single-cycle frames: harmonics limit -> (frames, TABLE_N + 1) array, every frame at the same
    RMS (so morphing doesn't change the level)."""
    spectra = _table_spectra(name)
    i = np.arange(TABLE_N, dtype=np.float64) / TABLE_N
    k = np.arange(1, HARMONICS + 1, dtype=np.float64)
    sines = sin_turns(np.outer(k, i))
    cosines = cos_turns(np.outer(k, i))
    rms = np.sqrt(0.5 * (np.abs(spectra) ** 2).sum(axis=1, keepdims=True))
    spectra = spectra / np.maximum(rms, 1e-12) * 0.5
    out: dict[int, np.ndarray] = {}
    for limit in LEVELS:
        keep = (k <= limit).astype(np.float64)
        frames = (spectra.real * keep) @ sines + (spectra.imag * keep) @ cosines
        out[limit] = round12(np.concatenate([frames, frames[:, :1]], axis=1))
    return out


def _wavetable(model: Wavetable, inst: Instrument, rate: int, tuning: float, n: int, n_gate: int, t: Signal, semis: Signal) -> Signal:
    from segan.synth import adsr

    position: Signal | float = model.position
    if model.env is not None and model.env_amount:
        position = position + model.env_amount * adsr(model.env, n_gate, n, rate, False)
    if model.lfo is not None:
        position = position + model.lfo[1] * 0.5 * (1.0 - cos_turns(t * model.lfo[0]))
    pos = np.clip(np.broadcast_to(np.asarray(position, dtype=np.float64), (n,)), 0.0, 1.0)
    voices = inst.unison
    out = np.zeros(n)
    for k in range(voices):
        cents = inst.detune * ((2.0 * k / (voices - 1) - 1.0) if voices > 1 else 1.0)
        freq = _freq(semis, cents, tuning)
        limit = max(1, int(0.45 * rate / float(freq.max())))
        table = wavetable(model.table)[next(level for level in LEVELS if level <= limit)]
        frames = len(table)
        phase = _phase(freq / rate, 0.25 * k / voices)
        x = (phase - np.floor(phase)) * TABLE_N
        i0 = np.minimum(np.floor(x).astype(np.int64), TABLE_N - 1)
        fx = x - i0
        f = pos * (frames - 1)
        j0 = np.minimum(np.floor(f).astype(np.int64), frames - 2)
        fw = f - j0
        a = table[j0, i0] + (table[j0, i0 + 1] - table[j0, i0]) * fx
        b = table[j0 + 1, i0] + (table[j0 + 1, i0 + 1] - table[j0 + 1, i0]) * fx
        out += a + (b - a) * fw
    return out * 1.6 / (math.sqrt(voices) if voices > 1 else 1.0)


# --- formant -------------------------------------------------------------------------------------


def _formant(model: Formant, inst: Instrument, rate: int, tuning: float, measure: bool, n: int, t: Signal, semis: Signal, seed: int) -> Signal:
    """Singers (saws with their own drift) plus breath, through five band-pass formants that follow the vowel
    keyframes."""
    from segan.synth import apply_filter

    voices = inst.unison
    source = np.zeros(n)
    for k in range(voices):
        cents = inst.detune * ((2.0 * k / (voices - 1) - 1.0) if voices > 1 else 1.0)
        wander = drift_cents(n, seed_of(seed, "singer", k), rate, model.drift, measure)
        freq = _freq(semis, np.asarray(cents) + wander, tuning)
        source += _saw(freq / rate, uniform(seed_of(seed, "phase"), k) if not measure else 0.25 * k / voices)
    source /= math.sqrt(voices) if voices > 1 else 1.0
    source = _sos(source, biquad("lp", 2500.0, 0.5, rate))  # glottal tilt: -12 dB/octave overall above the formants' range
    if not measure and model.breath > 0:
        source = source + model.breath * 0.6 * _sos(noise(n, seed_of(seed, "breath")), biquad("hp", 900.0, 0.7, rate))
    table = FORMANTS[voice_for(model.voice, inst.range)]
    times = np.array([v[0] for v in model.vowels])
    out = np.zeros(n)
    for j in range(5):
        freqs = np.array([table[v][0][j] for _, v in model.vowels], dtype=np.float64)
        dbs = np.array([table[v][1][j] for _, v in model.vowels], dtype=np.float64)
        bw = float(np.mean([table[v][2][j] for _, v in model.vowels]))
        centre: Signal | float = float(freqs[0]) if len(freqs) == 1 else np.interp(t, times, freqs)
        level = 10.0 ** (dbs[0] / 20.0) if len(dbs) == 1 else exp2(np.interp(t, times, dbs) * (_LOG2_10 / 20.0))
        q = max(0.5, float(np.mean(freqs)) / bw)
        out += apply_filter(source, "bp", centre, q, rate) * level
    # the voice's fundamental passes under the first formant too (a low voice singing "a" still has its pitch)
    out += 0.5 * _sos(source, biquad("lp", 350.0, 0.6, rate))
    return out * 2.5
