"""The synth: renders one note of one instrument to samples.

Everything runs at the oversampled rate (`[mix] oversample` x the sample rate) and is decimated by the
fixed polyphase filter at the end, so band-limited oscillators (PolyBLEP saw/pulse, PolyBLAMP triangle)
plus oversampling keep aliasing far below audibility. Envelopes are polynomials, sin/exp2 come from
tables and noise from a counter hash (see dsp.py), so renders are byte-identical on one machine and
within 1 LSB across machines.
"""

from __future__ import annotations

import math

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from segan.dsp import (
    Signal,
    biquad,
    db_to_gain,
    decimate,
    exp2,
    noise,
    noise_at,
    poly_blamp,
    poly_blep,
    resonance_to_q,
    seed_of,
    sin_turns,
)
from segan.patch import Crush, Env, Instrument

BLOCK = 64  # samples per filter-envelope block (oversampled rate)
DECLICK_ATTACK = 0.001
DECLICK_RELEASE = 0.003

Curve = Callable[[Signal], Signal]  # time (s) -> value per sample


@dataclass(frozen=True)
class Context:
    rate: int = 44100
    oversample: int = 2
    tuning: float = 440.0
    declick: bool = True
    measure: bool = False  # aliasing measurement: noise sources are silent

    @property
    def os_rate(self) -> int:
        return self.rate * self.oversample


# --- envelopes ---------------------------------------------------------------------------------

_LOG2_10 = round(math.log2(10.0), 12)


def exp10_neg3(x: Signal) -> Signal:
    """10 ** (-3 x) (-60 dB per unit of x) through the exp2 table, so it's the same on every machine."""
    return exp2(np.maximum(-1000.0, -3.0 * _LOG2_10 * np.asarray(x, dtype=np.float64)))


def adsr(env: Env, n_gate: int, n_total: int, rate: float, declick: bool) -> Signal:
    """Attack is linear; decay and release follow (1 - x)^3 (exponential-like, reaches zero exactly), or with
    `curve: exp` a true exponential: decay falls 60 dB (towards the sustain) per `decay` seconds and keeps going, so
    bells ring out instead of stopping dead; release falls 60 dB over `release`, bent to reach zero at its end."""
    attack = max(env.attack, DECLICK_ATTACK) if declick else env.attack
    release = max(env.release, DECLICK_RELEASE) if declick else env.release
    a, d, r = round(attack * rate), round(env.decay * rate), round(release * rate)
    s = env.sustain
    i = np.arange(n_total, dtype=np.float64)
    out = np.full(n_total, s)
    if a > 0:
        m = i < a
        out[m] = i[m] / a
    exp = env.curve == "exp"
    if d > 0:
        m = (i >= a) if exp else (i >= a) & (i < a + d)
        x = (i[m] - a) / d
        out[m] = s + (1.0 - s) * (exp10_neg3(x) if exp else (1.0 - x) ** 3)
    gate = min(n_gate, n_total)
    if gate < n_total:
        level = out[gate - 1] if gate > 0 else 0.0
        tail = i[gate:] - gate
        if r <= 0:
            out[gate:] = 0.0
        elif exp:
            out[gate:] = level * (exp10_neg3(tail / r) - 0.001) / 0.999
        else:
            out[gate:] = level * (1.0 - tail / r) ** 3
        out[gate:][tail >= r] = 0.0
    return out


def env_samples(env: Env, rate: float, declick: bool) -> int:
    release = max(env.release, DECLICK_RELEASE) if declick else env.release
    return round(release * rate)


# --- oscillators -------------------------------------------------------------------------------


def _phase(inc: Signal, start: float = 0.0) -> Signal:
    """Running phase (turns) before each sample."""
    out = np.empty_like(inc)
    out[0] = start
    np.cumsum(inc[:-1], out=out[1:])
    out[1:] += start
    return out


def oscillator(wave: str, inc: Signal, duty: Signal | float, seed: int, start_phase: float = 0.0) -> Signal:
    """One band-limited oscillator; `inc` = frequency / sample rate per sample."""
    n = len(inc)
    if n == 0:
        return np.zeros(0)
    if wave == "noise":
        return noise(n, seed)
    phase = _phase(inc, start_phase)
    if wave == "bitnoise":
        # sample-and-hold noise at 16 x the note frequency: the NES/sfxr "crunch" (pitch sets the grain)
        return noise_at(np.floor(phase * 16.0).astype(np.uint64), seed)
    frac = phase - np.floor(phase)
    dt = np.minimum(inc, 0.5)
    if wave == "sine":
        return sin_turns(frac)
    if wave == "saw":
        return 2.0 * frac - 1.0 - poly_blep(frac, dt)
    if wave == "pulse":
        d = np.broadcast_to(np.asarray(duty, dtype=np.float64), frac.shape)
        naive = np.where(frac < d, 1.0, -1.0)
        shifted = frac - d
        shifted -= np.floor(shifted)
        out = naive + poly_blep(frac, dt) - poly_blep(shifted, dt)
        return out - (2.0 * d - 1.0)  # remove the DC of an uneven duty
    if wave == "triangle":
        naive = 4.0 * np.abs(frac - 0.5) - 1.0  # +1 at phase 0, -1 at phase 0.5
        half = frac + 0.5
        half -= np.floor(half)
        return naive - 8.0 * dt * poly_blamp(frac, dt) + 8.0 * dt * poly_blamp(half, dt)
    raise ValueError(f"unknown oscillator {wave!r}")


# --- filters -----------------------------------------------------------------------------------


def apply_filter(x: Signal, kind: str, cutoff: Signal | float, q: float, rate: float) -> Signal:
    """Biquad filter; a time-varying cutoff is applied in BLOCK-sample blocks with the state carried over
    (cutoffs are quantised to 1/96 octave so steady stretches run as one block)."""
    from scipy.signal import sosfilt

    if np.ndim(cutoff) == 0:
        return np.asarray(sosfilt(biquad(kind, float(cutoff), q, rate), x), dtype=np.float64)
    cut = np.asarray(cutoff, dtype=np.float64)
    starts = np.arange(0, len(x), BLOCK)
    octaves = np.round(np.log2(np.clip(cut[starts], 10.0, 0.45 * rate)) * 96.0) / 96.0
    out = np.empty_like(x)
    zi = np.zeros((1, 2))
    i = 0
    while i < len(starts):
        j = i + 1
        while j < len(starts) and octaves[j] == octaves[i]:
            j += 1
        lo, hi = starts[i], (starts[j] if j < len(starts) else len(x))
        sos = biquad(kind, float(2.0 ** octaves[i]), q, rate)
        y, zi = sosfilt(sos, x[lo:hi], zi=zi)
        out[lo:hi] = y
        i = j
    return out


def crush(x: Signal, settings: Crush | None, rate: int) -> Signal:
    """Bit and sample-rate reduction at the output rate (deliberately lo-fi)."""
    if settings is None:
        return x
    out = x
    if settings.rate and settings.rate < rate:
        idx = np.floor(np.arange(len(out)) * (settings.rate / rate))
        first = np.searchsorted(idx, idx, side="left")
        out = out[first]
    if settings.bits:
        steps = float(2 ** (settings.bits - 1))
        out = np.round(out * steps) / steps
    return out


# --- notes -------------------------------------------------------------------------------------


def _keyframes(t: Signal, frames: tuple[tuple[float, float], ...]) -> Signal:
    times = np.array([f[0] for f in frames])
    values = np.array([f[1] for f in frames])
    return np.asarray(np.interp(t, times, values), dtype=np.float64)


def note_length(inst: Instrument, gate: float, ctx: Context, midi: float | None = None) -> float:
    """Seconds a note sounds: gate + release (drums: their decay; one-shot samples: the sample, longer when
    pitched down)."""
    if inst.is_drum:
        return inst.tail() + 0.01
    if inst.sample is not None:
        from segan.samples import audible_seconds, load_set

        sset = load_set(inst.sample)
        if sset.one_shot:
            key = round(midi) if midi is not None else None
            zones = [z for z in sset.zones if key is None or z.lokey <= key <= z.hikey] or list(sset.zones)
            return float(max(audible_seconds(z) * 2.0 ** (max(0.0, z.root - (midi if midi is not None else z.root)) / 12.0) for z in zones)) + 0.01
    release = max(inst.env.release, DECLICK_RELEASE) if ctx.declick else inst.env.release
    return gate + release


def render_note(
    inst: Instrument,
    ctx: Context,
    midi: float,
    gate: float,
    velocity: float = 1.0,
    seed: int = 0,
    pitch_curve: Curve | None = None,
    gain_curve: Curve | None = None,
    cutoff_curve: Curve | None = None,
    length: float | None = None,
) -> Signal:
    """One note at the output rate: `gate` seconds held, then the release. Curves (SFX keyframes) are
    functions of time: pitch in semitones added to `midi`, gain as a multiplier, cutoff as a multiplier."""
    rate = ctx.os_rate
    total = length if length is not None else note_length(inst, gate, ctx, midi)
    n = max(1, round(total * rate))
    n_gate = max(1, round(gate * rate))
    t = np.arange(n, dtype=np.float64) / rate
    semis = np.full(n, float(midi))
    if pitch_curve is not None:
        semis = semis + pitch_curve(t)
    if inst.pitch_env:
        semis = semis + _keyframes(t, inst.pitch_env)
    if inst.vibrato:
        vrate, depth, delay = inst.vibrato
        fade = np.clip((t - delay) / 0.15, 0.0, 1.0) if delay > 0 else 1.0
        semis = semis + depth * fade * sin_turns(t * vrate)
    if inst.arp:
        steps = np.floor(t * inst.arp_rate).astype(np.int64) % len(inst.arp)
        semis = semis + np.array(inst.arp, dtype=np.float64)[steps]

    if inst.is_drum:
        signal = _drum(inst, ctx, n, t, semis, seed)
    elif inst.sample is not None:
        signal = _sampled(inst, ctx, midi, semis, velocity, seed)
        one_shot = is_one_shot(inst)
        signal = signal * adsr(inst.env, n if one_shot else n_gate, n, rate, ctx.declick)
        if one_shot and ctx.declick:  # the sample may still ring where the note is cut
            fade = min(n, round(DECLICK_RELEASE * rate))
            signal[n - fade :] *= np.linspace(1.0, 0.0, fade, endpoint=False) ** 2
    else:
        signal = _tone(inst, ctx, n, n_gate, t, semis, seed)
        signal = signal * adsr(inst.env, n_gate, n, rate, ctx.declick)

    if inst.tremolo:
        trate, depth = inst.tremolo
        signal = signal * (1.0 - depth * (0.5 + 0.5 * sin_turns(t * trate)))
    if inst.filter is not None:
        f = inst.filter
        cutoff: Signal | float = f.cutoff
        if f.keytrack:
            cutoff = f.cutoff * exp2(f.keytrack * (semis - 60.0) / 12.0)
        if f.env_amount:
            fenv = adsr(f.env or inst.env, n_gate, n, rate, False)
            cutoff = cutoff * exp2(f.env_amount * fenv)
        if cutoff_curve is not None:
            cutoff = cutoff * cutoff_curve(t)
        signal = apply_filter(signal, f.type, cutoff, resonance_to_q(f.resonance), rate)
    if gain_curve is not None:
        signal = signal * gain_curve(t)
    signal = signal * (velocity * db_to_gain(inst.gain))
    out = decimate(signal, ctx.oversample)
    return crush(out, inst.crush, ctx.rate)


def _tone(inst: Instrument, ctx: Context, n: int, n_gate: int, t: Signal, semis: Signal, seed: int) -> Signal:
    rate = ctx.os_rate
    if inst.wave == "noise":
        return np.zeros(n) if ctx.measure else noise(n, seed_of(seed, "noise"))
    duty: Signal | float = inst.duty
    if inst.pwm:
        prate, depth = inst.pwm
        duty = np.clip(inst.duty + depth * sin_turns(t * prate), 0.02, 0.98)
    voices = inst.unison
    out = np.zeros(n)
    for k in range(voices):
        cents = inst.detune * ((2.0 * k / (voices - 1) - 1.0) if voices > 1 else 1.0)
        freq = ctx.tuning * exp2((semis + cents / 100.0 - 69.0) / 12.0)
        inc = freq / rate
        start = 0.25 * k / voices  # spread under a quarter turn: k / voices cancels the fundamental (2 voices)
        if inst.wave == "fm":
            fm = inst.fm
            ratio, index = (fm.ratio, fm.index) if fm else (2.0, 1.0)
            index_curve: Signal | float = index
            if fm is not None and fm.env is not None:
                index_curve = index * adsr(fm.env, n_gate, n, rate, False)
            mod = sin_turns(_phase(inc * ratio))
            carrier = _phase(inc, start)
            out += sin_turns(carrier + index_curve * mod / (2.0 * np.pi))
        elif inst.wave == "bitnoise" and ctx.measure:
            continue
        else:
            out += oscillator(inst.wave, inc, duty, seed_of(seed, "osc", k), start)
    return out / np.sqrt(voices) if voices > 1 else out


# --- samples -----------------------------------------------------------------------------------

VELOCITY_SCALE = 80  # note velocity 1.0 -> MIDI velocity 80 (picks the sample layer; accents 1.5 -> 120)


def is_one_shot(inst: Instrument) -> bool:
    from segan.samples import load_set

    return inst.sample is not None and load_set(inst.sample).one_shot


def _sampled(inst: Instrument, ctx: Context, midi: float, semis: Signal, velocity: float, seed: int) -> Signal:
    from segan.samples import load_set, play

    assert inst.sample is not None
    vel = inst.sample.velocity or max(1, min(127, round(velocity * VELOCITY_SCALE)))
    if ctx.measure:
        return np.zeros(len(semis))
    return play(load_set(inst.sample), semis, round(midi), vel, seed, ctx.os_rate, ctx.tuning)


# --- drums -------------------------------------------------------------------------------------


def _decay(t: Signal, length: float, power: int = 2) -> Signal:
    x = np.clip(t / max(length, 1e-4), 0.0, 1.0)
    return (1.0 - x) ** power


def _drum(inst: Instrument, ctx: Context, n: int, t: Signal, semis: Signal, seed: int) -> Signal:
    """Drum macros built from the same primitives as everything else (so their parameters are inspectable)."""
    rate = ctx.os_rate
    p = inst.drum_param
    tune, decay, tone, mix, click, punch = (p(k) for k in ("tune", "decay", "tone", "noise", "click", "punch"))
    # a drum played at its own `note` sounds at `tune`; other notes and pitch curves move it
    tune_curve = tune * exp2((semis - float(inst.note)) / 12.0)
    hiss = np.zeros(n) if ctx.measure else noise(n, seed_of(seed, "drum", inst.wave))
    kind = inst.wave

    def pitched(base: Signal | float, drop: float, drop_time: float, wave: str = "sine") -> Signal:
        bend = drop * _decay(t, drop_time, 3)
        freq = base * exp2(bend / 12.0)
        return oscillator(wave, np.broadcast_to(freq / rate, (n,)).copy(), 0.5, seed)

    if kind == "kick":
        body = pitched(tune_curve, punch, decay * 0.3) * _decay(t, decay, 2)
        snap = apply_filter(hiss, "lp", tone, 0.7, rate) * _decay(t, 0.006, 2)
        out = body + click * snap
    elif kind == "snare":
        body = pitched(tune_curve, punch, 0.04, "triangle") * _decay(t, decay * 0.55, 2)
        rattle = apply_filter(apply_filter(hiss, "hp", 900.0, 0.7, rate), "lp", tone * 2.5, 0.7, rate) * _decay(t, decay * 1.6, 2)
        snap = hiss * _decay(t, 0.004, 2)
        out = (1.0 - mix) * body + mix * rattle + click * snap * 0.5
    elif kind == "hat":
        metal = sum(
            (oscillator("pulse", np.full(n, tune * r / rate), 0.5, seed) for r in (2.0, 3.0, 4.16, 5.43, 6.79, 8.21)),
            np.zeros(n),
        )
        source = mix * hiss + (1.0 - mix) * metal / 3.0
        out = apply_filter(apply_filter(source, "hp", tone, 0.9, rate), "peak", tone * 1.3, 1.2, rate) * _decay(t, decay, 3)
    elif kind == "clap":
        bursts = np.zeros(n)
        for start in (0.0, 0.010, 0.021):
            bursts += np.where(t >= start, _decay(t - start, 0.008, 2), 0.0)
        tail = np.where(t >= 0.03, _decay(t - 0.03, decay, 2), 0.0) * 0.6
        out = apply_filter(hiss, "bp", tone, 1.4, rate) * (bursts + tail) * 1.6
    elif kind == "tom":
        body = pitched(tune_curve, punch, decay * 0.5) * _decay(t, decay, 2)
        out = body + mix * apply_filter(hiss, "lp", tone, 0.7, rate) * _decay(t, decay * 0.4, 2) + click * hiss * _decay(t, 0.004, 2) * 0.4
    elif kind == "cymbal":
        ratios = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)
        metal = sum((oscillator("pulse", np.full(n, tune / 400.0 * r / rate), 0.5, seed) for r in ratios), np.zeros(n))
        source = (1.0 - mix) * metal / 3.0 + mix * hiss
        out = apply_filter(source, "hp", tone, 0.8, rate) * _decay(t, decay, 3)
    else:
        raise ValueError(f"unknown drum {kind!r}")
    if ctx.declick:
        ramp = round(0.0003 * rate)
        if ramp > 0 and n > ramp:
            out[:ramp] *= np.arange(ramp) / ramp
    return np.asarray(out, dtype=np.float64)
