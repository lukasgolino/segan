"""Per-instrument effects: `fx: [ { chorus: {...} }, { delay: {...} } ]` on any instrument (kits, inline
instruments, SFX layers), applied in order to each note after it's rendered (and after a mono voice is cut,
so echoes and reverb ring on).

Effects run per note with their LFOs starting at the note: a note sounds the same wherever it's played, so the
render cache, loop seams and flow clips stay exact. Times and rates can follow the song's tempo: a note value
string (`"1/8"`, dotted `"1/8."`, triplet `"1/8t"`, bars `"1"`) is that long (a delay time) or one LFO cycle
that long (a rate). SFX have no tempo: there a note value counts at 120 bpm.

Stereo effects (chorus, ensemble, ping-pong delay, autopan, reverb) make the note stereo in stereo songs; the
instrument and track pan then balance it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from segan.dsp import Signal, biquad, cos_turns, db_to_gain, round12, sin_turns
from segan.patch import Report, is_number

FX_KINDS = ("chorus", "ensemble", "flanger", "phaser", "delay", "reverb", "drive", "crush", "comb", "ring", "tremolo", "autopan", "filter")
NOTE_VALUE = re.compile(r"^(\d+)(?:/(\d+))?([.t]?)$")
DEFAULT_BEAT = 0.5  # seconds per quarter note when there's no tempo (120 bpm)

# kind -> field -> (default, low, high, kind of value: "hz" rate, "s" time, "ms", "n" number, "b" bool, "c:<a|b>" choice)
FX_FIELDS: dict[str, dict[str, tuple[Any, float, float, str]]] = {
    "chorus": {"rate": (0.8, 0.01, 20, "hz"), "depth": (3.0, 0, 20, "ms"), "delay": (12.0, 1, 40, "ms"), "mix": (0.5, 0, 1, "n"),
               "voices": (2, 1, 4, "n"), "width": (1.0, 0, 1, "n")},
    "ensemble": {"depth": (0.5, 0, 1, "n"), "mix": (0.6, 0, 1, "n"), "width": (1.0, 0, 1, "n")},
    "flanger": {"rate": (0.25, 0.01, 20, "hz"), "depth": (2.0, 0, 10, "ms"), "delay": (1.5, 1, 20, "ms"), "feedback": (0.5, -0.95, 0.95, "n"),
                "mix": (0.5, 0, 1, "n")},
    "phaser": {"rate": (0.4, 0.01, 20, "hz"), "depth": (0.8, 0, 1, "n"), "stages": (4, 2, 12, "n"), "center": (900.0, 100, 8000, "n"),
               "mix": (0.5, 0, 1, "n")},
    "delay": {"time": (0.3, 0.005, 4, "s"), "feedback": (0.35, 0, 0.95, "n"), "mix": (0.3, 0, 1, "n"), "damp": (5000.0, 200, 20000, "n"),
              "pingpong": (False, 0, 0, "b")},
    "reverb": {"mix": (0.3, 0, 1, "n"), "decay": (1.5, 0.1, 10, "n")},
    "drive": {"amount": (0.5, 0, 1, "n"), "tone": (8000.0, 200, 20000, "n"), "mix": (1.0, 0, 1, "n")},
    "crush": {"bits": (8, 1, 16, "n"), "rate": (0.0, 0, 48000, "n")},
    "comb": {"ratio": (1.0, 0.125, 16, "n"), "feedback": (0.7, -0.98, 0.98, "n"), "mix": (0.4, 0, 1, "n")},
    "ring": {"ratio": (2.0, 0.01, 32, "n"), "freq": (0.0, 0, 20000, "n"), "mix": (0.5, 0, 1, "n")},
    "tremolo": {"rate": (5.0, 0.01, 50, "hz"), "depth": (0.5, 0, 1, "n"), "shape": ("sine", 0, 0, "c:sine|square")},
    "autopan": {"rate": (0.5, 0.01, 20, "hz"), "depth": (0.7, 0, 1, "n")},
    "filter": {"type": ("lp", 0, 0, "c:lp|hp|bp|notch"), "cutoff": (1200.0, 20, 20000, "n"), "resonance": (0.3, 0, 1, "n"),
               "lfo": (None, 0, 0, "lfo")},
}  # fmt: skip
STEREO = ("chorus", "ensemble", "autopan", "reverb")


@dataclass(frozen=True)
class Effect:
    kind: str
    values: tuple[tuple[str, Any], ...]

    def get(self, name: str) -> Any:
        return dict(self.values).get(name, FX_FIELDS[self.kind][name][0])


def note_value(text: str) -> float | None:
    """Quarter notes in a note value: "1/4" -> 1, "1/8." -> 0.75, "1/8t" -> 1/3, "1" (a bar of 4/4) -> 4."""
    match = NOTE_VALUE.match(text.strip())
    if not match:
        return None
    num, den, mod = int(match.group(1)), int(match.group(2) or 1), match.group(3)
    if num <= 0 or den not in (1, 2, 4, 8, 16, 32, 64):
        return None
    quarters = 4.0 * num / den
    return quarters * (1.5 if mod == "." else 2.0 / 3.0 if mod == "t" else 1.0)


def parse_fx(value: Any, report: Report, rule: str, where: str, line: int | None) -> tuple[Effect, ...] | None:
    hint = "fx must be a list of effects, e.g. [{ chorus: { rate: 0.8, mix: 0.4 } }, { delay: { time: \"1/8.\", feedback: 0.3 } }]"
    if not isinstance(value, list) or len(value) > 16:
        report.error(rule, hint + " (at most 16)", line, where)
        return None
    out: list[Effect] = []
    for i, item in enumerate(value):
        iwhere = f"{where}.{i}"
        if isinstance(item, str) and item in FX_KINDS:
            item = {item: {}}
        if not (isinstance(item, dict) and len(item) == 1 and next(iter(item)) in FX_KINDS):
            report.error(rule, f"effect {i + 1} must be one of {', '.join(FX_KINDS)} with its settings, e.g. {{ chorus: {{ mix: 0.4 }} }}", line, iwhere)
            return None
        kind, settings = next(iter(item.items()))
        settings = settings or {}
        fields = FX_FIELDS[kind]
        if not isinstance(settings, dict) or (unknown := [k for k in settings if k not in fields]):
            report.error(rule, f"{kind}: settings must be a mapping of {', '.join(fields)}", line, iwhere)
            return None
        values: list[tuple[str, Any]] = []
        for name, raw in settings.items():
            default, lo, hi, kind_of = fields[name]
            ok = False
            if kind_of in ("hz", "s") and isinstance(raw, str):
                ok = note_value(raw) is not None
            elif kind_of == "b":
                ok = isinstance(raw, bool)
            elif kind_of.startswith("c:"):
                ok = raw in kind_of[2:].split("|")
            elif kind_of == "lfo":
                ok = isinstance(raw, list) and len(raw) == 2 and (is_number(raw[0]) and 0 < raw[0] <= 50 or isinstance(raw[0], str) and note_value(raw[0]) is not None) \
                    and is_number(raw[1]) and 0 <= raw[1] <= 8  # fmt: skip
            elif is_number(raw):
                ok = lo <= raw <= hi and (not isinstance(default, int) or isinstance(default, bool) or float(raw).is_integer())
            if not ok:
                what = {"hz": f"a rate {lo:g}-{hi:g} Hz or a note value (\"1/4\", \"1/8.\", \"1/8t\", \"2\" bars)",
                        "s": f"a time {lo:g}-{hi:g} s or a note value (\"1/8\", \"1/8.\", \"1/4t\")", "ms": f"{lo:g}-{hi:g} ms",
                        "b": "true or false", "lfo": "[rate Hz or note value, octaves 0-8]"}.get(kind_of, f"{lo:g}..{hi:g}")  # fmt: skip
                if kind_of.startswith("c:"):
                    what = " or ".join(kind_of[2:].split("|"))
                report.error(rule, f"{kind}.{name} must be {what}", line, f"{iwhere}.{name}")
                return None
            values.append((str(name), raw if not (is_number(raw) and not isinstance(raw, bool)) else float(raw)))
        out.append(Effect(kind, tuple(values)))
    return tuple(out)


def seconds(value: Any, beat: float) -> float:
    """A time in seconds: a number, or a note value at `beat` seconds per quarter note."""
    if isinstance(value, str):
        return float(note_value(value) or 1.0) * beat
    return float(value)


def hertz(value: Any, beat: float) -> float:
    """A rate in Hz: a number, or one cycle per note value."""
    if isinstance(value, str):
        return 1.0 / (float(note_value(value) or 1.0) * beat)
    return float(value)


def fx_tail(effects: tuple[Effect, ...], beat: float, midi: float = 60.0) -> float:
    """Seconds the effects ring on after the note (echoes and reverb to -60 dB, modulated delays)."""
    tail = 0.0
    for fx in effects:
        if fx.kind == "delay":
            time, fb, mix = seconds(fx.get("time"), beat), float(fx.get("feedback")), float(fx.get("mix"))
            repeats = 1 if fb <= 0 else 1 + max(0, math.ceil(math.log(1e-3 / max(mix, 1e-3)) / math.log(fb)))
            tail += min(20.0, time * min(repeats, 200))
        elif fx.kind == "reverb":
            tail += float(fx.get("decay")) + 0.02
        elif fx.kind == "comb":
            fb = abs(float(fx.get("feedback")))
            period = 1.0 / (440.0 * 2.0 ** ((midi - 69) / 12.0) * float(fx.get("ratio")))
            tail += period * math.log(1e-3) / math.log(max(fb, 1e-3)) if fb > 0 else period
        elif fx.kind in ("chorus", "flanger"):
            tail += (float(fx.get("delay")) + float(fx.get("depth"))) / 1000.0
        elif fx.kind == "ensemble":
            tail += 0.02
    return tail


def tempo_synced(effects: tuple[Effect, ...]) -> bool:
    return any(isinstance(v, str) and k in ("rate", "time") or k == "lfo" and isinstance(v[0], str) for fx in effects for k, v in fx.values)


# --- processing --------------------------------------------------------------------------------


def _frames(x: Signal) -> Signal:
    return x if x.ndim == 2 else x[:, None]


def _read(x: Signal, delay: Signal) -> Signal:
    """x[n - delay[n]] with linear interpolation (zero before the start); `delay` in samples, per sample."""
    n = len(x)
    pos = np.arange(n, dtype=np.float64) - delay
    i0 = np.floor(pos).astype(np.int64)
    frac = pos - i0
    padded = np.concatenate([np.zeros(2), x, np.zeros(1)])
    a = padded[np.clip(i0, -2, n) + 2]
    b = padded[np.clip(i0 + 1, -2, n) + 2]
    return np.asarray(a + (b - a) * frac, dtype=np.float64)


def _wet_dry(dry: Signal, wet: Signal, mix: float) -> Signal:
    return dry * (1.0 - mix) + wet * mix


def _modulated(x: Signal, rate: int, base_ms: float, depth_ms: float, lfo_hz: float, phase: float) -> Signal:
    t = np.arange(len(x), dtype=np.float64) / rate
    delay = (base_ms + depth_ms * 0.5 * (1.0 + sin_turns(t * lfo_hz + phase))) * rate / 1000.0
    return _read(x, delay)


def _chorus(x: Signal, fx: Effect, rate: int, beat: float, stereo: bool) -> Signal:
    lfo, depth, base, mix = hertz(fx.get("rate"), beat), float(fx.get("depth")), float(fx.get("delay")), float(fx.get("mix"))
    voices, width = int(fx.get("voices")), float(fx.get("width"))
    sides = []
    for side in range(2 if stereo else 1):
        wet = np.zeros(len(x))
        for v in range(voices):
            wet += _modulated(x, rate, base, depth, lfo, v / voices + side * 0.25 * width)
        sides.append(_wet_dry(x, wet / voices, mix))
    return np.stack(sides, axis=1) if stereo else sides[0]


def _ensemble(x: Signal, fx: Effect, rate: int, stereo: bool) -> Signal:
    """The string-machine ensemble: three delay taps swept by a slow and a fast LFO, 120 degrees apart."""
    depth, mix, width = float(fx.get("depth")), float(fx.get("mix")), float(fx.get("width"))
    t = np.arange(len(x), dtype=np.float64) / rate
    sides = []
    for side in range(2 if stereo else 1):
        wet = np.zeros(len(x))
        for tap in range(3):
            phase = tap / 3.0 + side * 0.5 * width / 3.0
            ms = 7.0 + depth * (2.5 * sin_turns(t * 0.6 + phase) + 0.35 * sin_turns(t * 6.0 + phase))
            wet += _read(x, ms * rate / 1000.0)
        sides.append(_wet_dry(x, wet / 3.0, mix))
    return np.stack(sides, axis=1) if stereo else sides[0]


def _feedback_delay(x: Signal, delay: Signal, feedback: float) -> Signal:
    """y[n] = x[n] + feedback * y[n - delay[n]], in chunks shorter than the shortest delay."""
    n = len(x)
    pad = int(math.ceil(float(delay.max()))) + 2
    y = np.zeros(n + pad)
    chunk = max(1, int(float(delay.min())) - 1)
    index = np.arange(n, dtype=np.float64)
    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        pos = index[a:b] - delay[a:b] + pad
        i0 = np.floor(pos).astype(np.int64)
        fr = pos - i0
        y[a + pad : b + pad] = x[a:b] + feedback * (y[i0] + (y[i0 + 1] - y[i0]) * fr)
    return y[pad:]


def _flanger(x: Signal, fx: Effect, rate: int, beat: float) -> Signal:
    lfo, depth, base, fb, mix = hertz(fx.get("rate"), beat), float(fx.get("depth")), float(fx.get("delay")), float(fx.get("feedback")), float(fx.get("mix"))
    t = np.arange(len(x), dtype=np.float64) / rate
    delay = (base + depth * 0.5 * (1.0 + sin_turns(t * lfo))) * rate / 1000.0
    looped = _feedback_delay(x, delay, fb)  # comb with feedback through the swept delay
    return _wet_dry(x, _read(looped, delay) * (1.0 - abs(fb)), mix)


def _phaser(x: Signal, fx: Effect, rate: int, beat: float) -> Signal:
    """A chain of first-order all-passes whose corner sweeps over two octaves around `center` (32-sample blocks)."""
    from scipy.signal import sosfilt

    lfo, depth, stages, centre, mix = hertz(fx.get("rate"), beat), float(fx.get("depth")), int(fx.get("stages")), float(fx.get("center")), float(fx.get("mix"))
    block = 32
    starts = np.arange(0, len(x), block)
    corner = centre * 2.0 ** (2.0 * depth * sin_turns(starts / rate * lfo))
    out = np.empty_like(x)
    zi = np.zeros((stages, 2))
    for i, start in enumerate(starts):
        tan = math.tan(math.pi * min(float(corner[i]), 0.45 * rate) / rate)
        a = round((tan - 1.0) / (tan + 1.0), 12)
        sos = np.tile(np.array([[a, 1.0, 0.0, 1.0, a, 0.0]]), (stages, 1))
        out[start : start + block], zi = sosfilt(sos, x[start : start + block], zi=zi)
    return _wet_dry(x, out, mix * 0.5) * (1.0 + mix * 0.5)


def _delay(x: Signal, fx: Effect, rate: int, beat: float, stereo: bool) -> Signal:
    """Echoes every `time`, each `feedback` quieter and darker (`damp` low-pass per repeat): one FFT convolution
    with the echo train. Ping-pong alternates the echoes between the sides."""
    from scipy.signal import fftconvolve, sosfilt

    step = max(1, round(seconds(fx.get("time"), beat) * rate))
    fb, mix, damp, pingpong = float(fx.get("feedback")), float(fx.get("mix")), float(fx.get("damp")), bool(fx.get("pingpong")) and stereo
    length = round(fx_tail((fx,), beat) * rate) + step + 1
    train = [np.zeros(length), np.zeros(length)]
    echo = np.zeros(min(length, 4 * step + 64))
    echo[0] = 1.0
    sos = biquad("lp", min(damp, 0.45 * rate), 0.6, rate)
    gain, k = mix, 1
    while gain > 1e-3 and k * step < length:
        echo = np.asarray(sosfilt(sos, echo), dtype=np.float64)
        side = (k - 1) % 2 if pingpong else 0
        seg = echo[: length - k * step]
        train[side][k * step : k * step + len(seg)] += seg * gain
        if not pingpong:
            train[1][k * step : k * step + len(seg)] += seg * gain
        gain *= fb
        k += 1
        if fb <= 0:
            break
    n = len(x) + length
    outs = []
    for side in range(2 if stereo else 1):
        wet = np.zeros(n)
        conv = fftconvolve(x, round12(train[side]))[:n]
        wet[: len(conv)] = conv
        dry = np.zeros(n)
        dry[: len(x)] = x
        outs.append(dry + wet)
    return np.stack(outs, axis=1) if stereo else outs[0]


def _reverb(x: Signal, fx: Effect, rate: int, stereo: bool) -> Signal:
    from scipy.signal import fftconvolve

    from segan.mix import room_ir

    channels = 2 if stereo else 1
    ir = room_ir(rate, float(fx.get("decay")), channels)
    mix = float(fx.get("mix"))
    outs = []
    for ch in range(channels):
        wet = fftconvolve(x, ir[:, ch])
        dry = np.zeros(len(wet))
        dry[: len(x)] = x
        outs.append(dry * (1.0 - mix * 0.5) + wet * mix)
    return np.stack(outs, axis=1) if stereo else outs[0]


def soft_clip(x: Signal) -> Signal:
    """A smooth saturator with exact arithmetic (no per-sample tanh): a rational tanh approximation, clamped."""
    y = np.clip(x, -3.0, 3.0)
    return y * (27.0 + y * y) / (27.0 + 9.0 * y * y)


def _drive(x: Signal, fx: Effect, rate: int) -> Signal:
    """Saturation at 4x the rate (so the new harmonics don't alias), then a tone low-pass."""
    from scipy.signal import resample_poly, sosfilt

    from segan.dsp import decimator_taps

    amount, tone, mix = float(fx.get("amount")), float(fx.get("tone")), float(fx.get("mix"))
    drive = 1.0 + 24.0 * amount * amount
    up = np.asarray(resample_poly(x, 4, 1, window=decimator_taps(4)), dtype=np.float64)
    shaped = soft_clip(up * drive) / (soft_clip(np.array([drive]))[0])
    down = np.asarray(resample_poly(shaped, 1, 4, window=decimator_taps(4)), dtype=np.float64)[: len(x)]
    wet = np.asarray(sosfilt(biquad("lp", min(tone, 0.45 * rate), 0.7, rate), down), dtype=np.float64) * db_to_gain(-3.0 * amount)
    return _wet_dry(x, wet, mix)


def _comb(x: Signal, fx: Effect, rate: int, midi: float, tuning: float) -> Signal:
    from scipy.signal import fftconvolve

    hz = tuning * 2.0 ** ((midi - 69.0) / 12.0) * float(fx.get("ratio"))
    period = rate / hz
    fb, mix = float(fx.get("feedback")), float(fx.get("mix"))
    length = round(fx_tail((fx,), 0.5, midi) * rate) + 2
    ir = np.zeros(length)
    gain, k = 1.0, 1
    while abs(gain) > 1e-3 and k * period < length - 1:
        at = k * period
        i = int(at)
        ir[i] += gain * (1.0 - (at - i))
        ir[i + 1] += gain * (at - i)
        gain *= fb
        k += 1
    wet = fftconvolve(x, round12(ir))[: len(x) + length]
    dry = np.zeros(len(wet))
    dry[: len(x)] = x
    return np.asarray(dry + mix * wet * (1.0 - abs(fb)), dtype=np.float64)


def _autofilter(x: Signal, fx: Effect, rate: int, beat: float) -> Signal:
    from segan.dsp import exp2, resonance_to_q
    from segan.synth import apply_filter

    cutoff: Signal | float = float(fx.get("cutoff"))
    lfo = fx.get("lfo")
    if lfo is not None:
        t = np.arange(len(x), dtype=np.float64) / rate
        cutoff = float(fx.get("cutoff")) * exp2(float(lfo[1]) * 0.5 * (1.0 - cos_turns(t * hertz(lfo[0], beat))))
    return apply_filter(x, str(fx.get("type")), cutoff, resonance_to_q(float(fx.get("resonance"))), rate)


def apply_fx(x: Signal, effects: tuple[Effect, ...], rate: int, beat: float, channels: int, midi: float, tuning: float = 440.0) -> Signal:
    """Run a note (mono, output rate) through its effects; returns mono, or (frames, 2) once a stereo effect ran
    in a stereo song."""
    from segan.patch import Crush
    from segan.synth import crush

    out = x
    stereo = channels == 2
    for fx in effects:
        if out.ndim == 2:  # already stereo: run each side
            sides = [apply_fx(out[:, ch], (fx,), rate, beat, 1, midi, tuning) for ch in range(2)]
            if fx.kind == "autopan":
                out = _autopan(out, fx, rate, beat)
                continue
            n = max(len(s) for s in sides)
            out = np.stack([np.pad(s, (0, n - len(s))) for s in sides], axis=1)
            continue
        if fx.kind == "chorus":
            out = _chorus(out, fx, rate, beat, stereo)
        elif fx.kind == "ensemble":
            out = _ensemble(out, fx, rate, stereo)
        elif fx.kind == "flanger":
            out = _flanger(out, fx, rate, beat)
        elif fx.kind == "phaser":
            out = _phaser(out, fx, rate, beat)
        elif fx.kind == "delay":
            out = _delay(out, fx, rate, beat, stereo)
        elif fx.kind == "reverb":
            out = _reverb(out, fx, rate, stereo)
        elif fx.kind == "drive":
            out = _drive(out, fx, rate)
        elif fx.kind == "crush":
            out = crush(out, Crush(int(fx.get("bits")), float(fx.get("rate"))), rate)
        elif fx.kind == "comb":
            out = _comb(out, fx, rate, midi, tuning)
        elif fx.kind == "ring":
            t = np.arange(len(out), dtype=np.float64) / rate
            hz = float(fx.get("freq")) or tuning * 2.0 ** ((midi - 69.0) / 12.0) * float(fx.get("ratio"))
            out = _wet_dry(out, out * sin_turns(t * hz), float(fx.get("mix")))
        elif fx.kind == "tremolo":
            t = np.arange(len(out), dtype=np.float64) / rate
            wave = sin_turns(t * hertz(fx.get("rate"), beat))
            if fx.get("shape") == "square":
                wave = np.clip(wave * 8.0, -1.0, 1.0)
            out = out * (1.0 - float(fx.get("depth")) * (0.5 + 0.5 * wave))
        elif fx.kind == "autopan":
            if stereo:
                out = _autopan(np.stack([out, out], axis=1), fx, rate, beat)
        elif fx.kind == "filter":
            out = _autofilter(out, fx, rate, beat)
    return out


def _autopan(x: Signal, fx: Effect, rate: int, beat: float) -> Signal:
    t = np.arange(len(x), dtype=np.float64) / rate
    pan = float(fx.get("depth")) * sin_turns(t * hertz(fx.get("rate"), beat))
    angle = (pan + 1.0) / 8.0  # turns: 0 = left, 1/8 = centre, 1/4 = right
    mono = 0.5 * (x[:, 0] + x[:, 1])
    return np.stack([mono * cos_turns(angle) * math.sqrt(2.0), mono * sin_turns(angle) * math.sqrt(2.0)], axis=1)


def describe_fx(effects: tuple[Effect, ...]) -> str:
    return " + ".join(fx.kind for fx in effects)


__all__ = ["FX_KINDS", "Effect", "apply_fx", "describe_fx", "fx_tail", "note_value", "parse_fx", "tempo_synced", "_frames"]
