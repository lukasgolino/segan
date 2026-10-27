"""Instrument models beyond the basic oscillators: what they are, their parameters and presets, and parsing.

An `osc` with a model takes a block named after it (`osc: modal` + `modal: { material: marimba }`); a plain
string picks a preset (`modal: vibraphone`, `bowed: cello`, `formant: ah`), and no block means the defaults.

- `pluck`: a plucked string (Karplus-Strong: a noise burst circulating in a tuned, damped delay loop);
- `bowed`: a bowed string: per player a band-limited saw (Helmholtz motion) with its own slow pitch drift, bow
  noise and the body resonances of a violin, viola, cello or double bass (`unison` = players in the section);
- `additive`: a sum of partials (harmonic amplitudes, Hammond-style drawbars, or inharmonic [ratio, amp, decay]);
- `wavetable`: single-cycle frames (bundled tables) morphed by position, an envelope or an LFO;
- `formant`: a voice: a glottal source through the five formants of a vowel (soprano/alto/tenor/bass), vowels
  morphing over time (choir pads with `unison`);
- `modal`: a struck resonator: decaying modes of a material (marimba, vibraphone, glass, bell, metal...);
- `supersaw`: seven detuned saws (the JP-8000 trance/hoover stack).

`osc: impulses` (a basic oscillator, rendered in synth.py) also takes a block: sparse random impulses (crackle,
debris, bubbles), parsed here like `sub` and `sync`.

Rendering is in modelsynth.py; renders follow the determinism rules of dsp.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from segan.dsp import hz_to_midi
from segan.patch import Env, Report, is_number, parse_env, parse_note_value

MODELS = ("pluck", "bowed", "additive", "wavetable", "formant", "modal", "supersaw")


@dataclass(frozen=True)
class Pluck:
    decay: float = 3.0  # seconds for the fundamental of C4 to fall 60 dB
    brightness: float = 0.5  # 0 dull (high partials die fast) .. 1 bright, metallic
    pick: float = 0.15  # where along the string it's plucked (0-0.5): near the end = thin, middle = hollow
    damping: float = 0.5  # how much faster high notes die (0 = all as long as C4)
    body: str = "none"


@dataclass(frozen=True)
class Bowed:
    body: str = "auto"  # violin | viola | cello | bass | auto (from the instrument's range)
    bow: float = 0.3  # bow noise 0-1
    drift: float = 5.0  # cents each player wanders


@dataclass(frozen=True)
class Additive:
    partials: tuple[tuple[float, float, float | None], ...]  # (ratio, amplitude, decay seconds at C4 or None = held)
    stretch: float = 0.0  # inharmonicity B: partial k sits at k * sqrt(1 + B k^2) (stiff strings, pianos)


@dataclass(frozen=True)
class Wavetable:
    table: str = "analog"
    position: float = 0.0  # 0-1 through the table's frames
    env: Env | None = None
    env_amount: float = 0.0  # -1..1 of the table the envelope moves the position
    lfo: tuple[float, float] | None = None  # rate Hz, depth 0-1


@dataclass(frozen=True)
class Formant:
    vowels: tuple[tuple[float, str], ...] = ((0.0, "a"),)  # (seconds, vowel) keyframes
    voice: str = "auto"  # soprano | alto | tenor | bass | auto (from the instrument's range)
    breath: float = 0.1  # 0-1 noise in the voice
    drift: float = 4.0  # cents each singer wanders (with unison: a choir)


@dataclass(frozen=True)
class Modal:
    material: str = "marimba"
    strike: float = 0.5  # 0 soft mallet (fundamental) .. 1 hard (bright, more high modes, a click)
    decay: float | None = None  # seconds the fundamental rings at C4 (default: the material's)


@dataclass(frozen=True)
class Supersaw:
    spread: float = 30.0  # cents to the outermost saw
    mix: float = 0.6  # level of the six side saws against the centre one


Model = Pluck | Bowed | Additive | Wavetable | Formant | Modal | Supersaw


@dataclass(frozen=True)
class Sub:
    octave: int = -1
    wave: str = "sine"  # sine | square | triangle
    level: float = -6.0  # dB against the main oscillator


@dataclass(frozen=True)
class Sync:
    ratio: float = 2.0  # slave frequency / note frequency
    env_amount: float = 0.0  # octaves the envelope sweeps the ratio up
    env: Env | None = None  # default: the amplitude envelope


IMPULSE_SHAPES = ("click", "tick", "bubble")


@dataclass(frozen=True)
class Impulses:
    """`osc: impulses`: a Poisson stream of short impulses (crackle, debris, bubbles)."""

    density: float = 30.0  # impulses per second (x the gain keyframes' linear gain)
    shape: str = "click"  # click = 1-2 ms noise burst, tick = decaying sine, bubble = sine rising ~30% (Minnaert chirp)
    pitch: tuple[float, float] = (round(hz_to_midi(300.0), 9), round(hz_to_midi(3000.0), 9))  # MIDI notes; log-uniform per impulse
    decay: float = 0.02  # seconds per impulse (tick, bubble)
    level: tuple[float, float] = (0.5, 1.0)  # amplitude range per impulse


# --- tables ----------------------------------------------------------------------------------------

PLUCK_PRESETS: dict[str, Pluck] = {
    "guitar": Pluck(3.0, 0.55, 0.15, 0.5, "guitar"),
    "nylon": Pluck(2.5, 0.35, 0.18, 0.55, "guitar"),
    "steel": Pluck(3.5, 0.7, 0.12, 0.45, "guitar"),
    "harp": Pluck(5.0, 0.45, 0.45, 0.4, "none"),
    "koto": Pluck(2.2, 0.75, 0.08, 0.5, "none"),
    "pizz": Pluck(0.6, 0.35, 0.22, 0.5, "violin"),
    "bass": Pluck(2.5, 0.3, 0.2, 0.3, "none"),
    "muted": Pluck(0.35, 0.3, 0.12, 0.3, "guitar"),
    "harpsichord": Pluck(3.0, 0.9, 0.08, 0.5, "none"),
}

# Body resonances: (Hz, dB, Q) peaks, then a low-pass (Hz). After measured modes of each instrument (air and
# top-plate modes, the bridge hill, the "nasal" dip), simplified to five or six peaks.
BODIES: dict[str, tuple[tuple[tuple[float, float, float], ...], float]] = {
    "violin": (((280.0, 6.0, 3.0), (460.0, 4.0, 3.0), (550.0, 3.0, 3.0), (1200.0, -4.0, 1.5), (2500.0, 5.0, 1.2), (3500.0, 2.0, 2.0)), 9000.0),
    "viola": (((230.0, 6.0, 3.0), (380.0, 4.0, 3.0), (500.0, 3.0, 3.0), (1000.0, -4.0, 1.5), (2200.0, 4.0, 1.2)), 8000.0),
    "cello": (((100.0, 5.0, 3.0), (200.0, 5.0, 3.0), (400.0, 3.0, 2.5), (700.0, -3.0, 1.5), (1500.0, 3.0, 1.2)), 6500.0),
    "bass": (((60.0, 5.0, 3.0), (110.0, 4.0, 3.0), (250.0, 3.0, 2.0), (500.0, -3.0, 1.5), (1000.0, 2.0, 1.2)), 4500.0),
    "guitar": (((100.0, 4.0, 2.5), (200.0, 5.0, 3.0), (400.0, 2.0, 2.0), (1500.0, -2.0, 1.2), (3000.0, 2.0, 1.5)), 8000.0),
}
BODY_NAMES = ("violin", "viola", "cello", "bass")


def body_for(name: str, range_: tuple[int, int] | None) -> str:
    """`auto` picks the string family member from the instrument's range (its middle note)."""
    if name != "auto":
        return name
    middle = (range_[0] + range_[1]) / 2 if range_ else 67
    return "bass" if middle < 43 else "cello" if middle < 55 else "viola" if middle < 64 else "violin"


ADDITIVE_PRESETS: dict[str, tuple[tuple[float, float, float | None], ...]] = {}

DRAWBAR_RATIOS = (0.5, 1.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)  # 16' 5 1/3' 8' 4' 2 2/3' 2' 1 3/5' 1 1/3' 1'


def drawbars(setting: str) -> tuple[tuple[float, float, float | None], ...]:
    """Hammond drawbars ("888000000"): nine digits 0-8, 3 dB per step."""
    out = []
    for ratio, digit in zip(DRAWBAR_RATIOS, setting, strict=True):
        if digit != "0":
            out.append((ratio, round(10.0 ** ((int(digit) - 8) * 3.0 / 20.0), 12), None))
    return tuple(sorted(out))


def _harmonics(amps: list[float]) -> tuple[tuple[float, float, float | None], ...]:
    return tuple((float(k + 1), a, None) for k, a in enumerate(amps) if a > 0)


ADDITIVE_PRESETS.update({
    "organ": drawbars("888000000"),
    "organ_full": drawbars("888888888"),
    "organ_soft": drawbars("008600000"),
    "flute": _harmonics([1.0, 0.25, 0.08, 0.03]),
    "clarinet": _harmonics([1.0, 0.0, 0.4, 0.0, 0.25, 0.0, 0.15, 0.0, 0.1]),
    "hollow": _harmonics([1.0, 0.0, 0.33, 0.0, 0.2]),
    "warm": _harmonics([1.0, 0.5, 0.3, 0.2, 0.12, 0.08, 0.05]),
    "bright": _harmonics([1.0 / k for k in range(1, 25)]),
    "bell": ((0.5, 0.6, 6.0), (1.0, 1.0, 4.0), (1.19, 0.6, 3.0), (1.5, 0.4, 2.5), (2.0, 0.5, 2.0), (2.52, 0.3, 1.5), (2.66, 0.25, 1.2),
             (3.0, 0.2, 1.0), (4.07, 0.15, 0.7), (5.43, 0.08, 0.5)),
    "glass": ((1.0, 1.0, 3.0), (2.32, 0.5, 2.0), (4.25, 0.25, 1.2), (6.63, 0.12, 0.8), (9.38, 0.06, 0.5)),
    "chime": ((1.0, 1.0, 5.0), (2.76, 0.6, 3.0), (5.4, 0.3, 1.5), (8.93, 0.15, 0.8)),
})  # fmt: skip

WAVETABLES = ("analog", "pulse", "vocal", "glass", "digital", "organ", "harmonic", "sync")

VOWELS = ("a", "e", "i", "o", "u")
VOWEL_ALIASES = {"ah": "a", "aa": "a", "eh": "e", "ee": "i", "ih": "i", "oh": "o", "oo": "u", "uh": "u"}
VOICES = ("soprano", "alto", "tenor", "bass")

# Formants per voice and vowel: (Hz x5, dB x5, bandwidth Hz x5); the classic table of sung vowels.
FORMANTS: dict[str, dict[str, tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]]] = {
    "soprano": {
        "a": ((800, 1150, 2900, 3900, 4950), (0, -6, -32, -20, -50), (80, 90, 120, 130, 140)),
        "e": ((350, 2000, 2800, 3600, 4950), (0, -20, -15, -40, -56), (60, 100, 120, 150, 200)),
        "i": ((270, 2140, 2950, 3900, 4950), (0, -12, -26, -26, -44), (60, 90, 100, 120, 120)),
        "o": ((450, 800, 2830, 3800, 4950), (0, -11, -22, -22, -50), (70, 80, 100, 130, 135)),
        "u": ((325, 700, 2700, 3800, 4950), (0, -16, -35, -40, -60), (50, 60, 170, 180, 200)),
    },
    "alto": {
        "a": ((800, 1150, 2800, 3500, 4950), (0, -4, -20, -36, -60), (80, 90, 120, 130, 140)),
        "e": ((400, 1600, 2700, 3300, 4950), (0, -24, -30, -35, -60), (60, 80, 120, 150, 200)),
        "i": ((350, 1700, 2700, 3700, 4950), (0, -20, -30, -36, -60), (50, 100, 120, 150, 200)),
        "o": ((450, 800, 2830, 3500, 4950), (0, -9, -16, -28, -55), (70, 80, 100, 130, 135)),
        "u": ((325, 700, 2530, 3500, 4950), (0, -12, -30, -40, -64), (50, 60, 170, 180, 200)),
    },
    "tenor": {
        "a": ((650, 1080, 2650, 2900, 3250), (0, -6, -7, -8, -22), (80, 90, 120, 130, 140)),
        "e": ((400, 1700, 2600, 3200, 3580), (0, -14, -12, -14, -20), (70, 80, 100, 120, 120)),
        "i": ((290, 1870, 2800, 3250, 3540), (0, -15, -18, -20, -30), (40, 90, 100, 120, 120)),
        "o": ((400, 800, 2600, 2800, 3000), (0, -10, -12, -12, -26), (40, 80, 100, 120, 120)),
        "u": ((350, 600, 2700, 2900, 3300), (0, -20, -17, -14, -26), (40, 60, 100, 120, 120)),
    },
    "bass": {
        "a": ((600, 1040, 2250, 2450, 2750), (0, -7, -9, -9, -20), (60, 70, 110, 120, 130)),
        "e": ((400, 1620, 2400, 2800, 3100), (0, -12, -9, -12, -18), (40, 80, 100, 120, 120)),
        "i": ((250, 1750, 2600, 3050, 3340), (0, -30, -16, -22, -28), (60, 90, 100, 120, 120)),
        "o": ((400, 750, 2400, 2600, 2900), (0, -11, -21, -20, -40), (40, 80, 100, 120, 120)),
        "u": ((350, 600, 2400, 2675, 2950), (0, -20, -32, -28, -36), (40, 80, 100, 120, 120)),
    },
}


def voice_for(name: str, range_: tuple[int, int] | None) -> str:
    if name != "auto":
        return name
    middle = (range_[0] + range_[1]) / 2 if range_ else 60
    return "bass" if middle < 50 else "tenor" if middle < 57 else "alto" if middle < 65 else "soprano"


# Modes per material: (frequency ratio, amplitude, decay relative to the fundamental's); default decay at C4 (s).
MATERIALS: dict[str, tuple[tuple[tuple[float, float, float], ...], float]] = {
    "marimba": (((1.0, 1.0, 1.0), (3.99, 0.35, 0.3), (9.95, 0.12, 0.12)), 0.9),
    "vibraphone": (((1.0, 1.0, 1.0), (4.0, 0.3, 0.45), (10.0, 0.08, 0.2)), 3.0),
    "xylophone": (((1.0, 1.0, 1.0), (3.0, 0.4, 0.5), (6.0, 0.15, 0.3), (9.3, 0.06, 0.2)), 0.45),
    "glass": (((1.0, 1.0, 1.0), (2.32, 0.5, 0.7), (4.25, 0.25, 0.45), (6.63, 0.12, 0.3), (9.38, 0.06, 0.2)), 3.5),
    "bell": (((0.5, 0.5, 1.6), (1.0, 1.0, 1.0), (1.19, 0.6, 0.8), (1.5, 0.35, 0.7), (2.0, 0.45, 0.55), (2.52, 0.25, 0.4),
              (2.66, 0.2, 0.35), (3.01, 0.15, 0.3), (4.07, 0.1, 0.2)), 5.0),
    "tubular": (((1.0, 1.0, 1.0), (2.76, 0.8, 0.7), (5.4, 0.55, 0.45), (8.93, 0.3, 0.3), (13.34, 0.12, 0.2)), 5.0),
    "kalimba": (((1.0, 1.0, 1.0), (5.93, 0.2, 0.25), (16.6, 0.05, 0.1)), 1.8),
    "steel_drum": (((1.0, 1.0, 1.0), (2.01, 0.55, 0.75), (2.98, 0.3, 0.55), (4.03, 0.12, 0.35)), 1.6),
    "wood": (((1.0, 1.0, 1.0), (2.57, 0.45, 0.5), (4.42, 0.2, 0.3), (6.25, 0.1, 0.2)), 0.25),
    "metal": (((1.0, 1.0, 1.0), (1.41, 0.8, 0.9), (1.71, 0.7, 0.85), (2.25, 0.6, 0.7), (2.83, 0.5, 0.6), (3.24, 0.4, 0.5),
               (3.86, 0.3, 0.4)), 2.5),
    "membrane": (((1.0, 1.0, 1.0), (1.594, 0.6, 0.6), (2.136, 0.45, 0.45), (2.296, 0.35, 0.4), (2.653, 0.25, 0.3), (2.918, 0.2, 0.25)), 0.5),
}  # fmt: skip


# --- parsing -------------------------------------------------------------------------------------


def _fields(value: Any, allowed: tuple[str, ...], report: Report, rule: str, where: str, line: int | None, hint: str) -> dict[str, Any] | None:
    if value is None:
        return {}
    if not isinstance(value, dict):
        report.error(rule, f"{where.rsplit('.', 1)[-1]} must be {hint}", line, where)
        return None
    if unknown := [k for k in value if k not in allowed]:
        report.error(rule, f"unknown {where.rsplit('.', 1)[-1]} field {unknown[0]!r}; allowed: {', '.join(allowed)}", line, f"{where}.{unknown[0]}")
        return None
    return dict(value)


def _num(data: dict[str, Any], key: str, default: float, lo: float, hi: float, report: Report, rule: str, where: str, line: int | None, hint: str = "") -> float | None:
    value = data.get(key, default)
    if not (is_number(value) and lo <= value <= hi):
        report.error(rule, f"{key} must be a number {lo:g}..{hi:g}{hint}", line, f"{where}.{key}")
        return None
    return float(value)


def _choice(data: dict[str, Any], key: str, default: str, options: tuple[str, ...], report: Report, rule: str, where: str, line: int | None) -> str | None:
    value = data.get(key, default)
    if value not in options:
        report.error(rule, f"{key} must be one of {', '.join(options)}", line, f"{where}.{key}")
        return None
    return str(value)


def parse_model(wave: str, value: Any, report: Report, rule: str, where: str, line: int | None) -> Model | None:
    """The model block of `osc: <wave>` (None, a preset name or a mapping)."""
    before = len(report.findings)
    model: Model | None = None
    if wave == "pluck":
        model = _pluck(value, report, rule, where, line)
    elif wave == "bowed":
        model = _bowed(value, report, rule, where, line)
    elif wave == "additive":
        model = _additive(value, report, rule, where, line)
    elif wave == "wavetable":
        model = _wavetable(value, report, rule, where, line)
    elif wave == "formant":
        model = _formant(value, report, rule, where, line)
    elif wave == "modal":
        model = _modal(value, report, rule, where, line)
    elif wave == "supersaw":
        data = _fields(value, ("spread", "mix"), report, rule, where, line, "{ spread: cents, mix: 0-1 }")
        if data is not None:
            spread = _num(data, "spread", 30.0, 0, 100, report, rule, where, line, " cents to the outermost saw")
            mix = _num(data, "mix", 0.6, 0, 1, report, rule, where, line, " (side saws against the centre one)")
            model = Supersaw(spread, mix) if spread is not None and mix is not None else None
    return model if len(report.findings) == before else None


def _pluck(value: Any, report: Report, rule: str, where: str, line: int | None) -> Pluck | None:
    base = Pluck()
    if isinstance(value, str):
        if value not in PLUCK_PRESETS:
            report.error(rule, f"pluck preset must be one of {', '.join(PLUCK_PRESETS)} (or a mapping of decay, brightness, pick, damping, body)", line, where)
            return None
        return PLUCK_PRESETS[value]
    data = _fields(value, ("preset", "decay", "brightness", "pick", "damping", "body"), report, rule, where, line,
                   "a preset name or { preset, decay, brightness, pick, damping, body }")  # fmt: skip
    if data is None:
        return None
    if "preset" in data:
        if data["preset"] not in PLUCK_PRESETS:
            report.error(rule, f"pluck preset must be one of {', '.join(PLUCK_PRESETS)}", line, f"{where}.preset")
            return None
        base = PLUCK_PRESETS[data["preset"]]
    decay = _num(data, "decay", base.decay, 0.05, 30, report, rule, where, line, " seconds (C4 falls 60 dB)")
    bright = _num(data, "brightness", base.brightness, 0, 1, report, rule, where, line)
    pick = _num(data, "pick", base.pick, 0, 0.5, report, rule, where, line, " (pluck position along the string)")
    damping = _num(data, "damping", base.damping, 0, 1, report, rule, where, line)
    body = _choice(data, "body", base.body, ("none", *BODIES), report, rule, where, line)
    if None in (decay, bright, pick, damping, body):
        return None
    return Pluck(decay, bright, pick, damping, body)  # type: ignore[arg-type]


def _bowed(value: Any, report: Report, rule: str, where: str, line: int | None) -> Bowed | None:
    if isinstance(value, str):
        value = {"body": value}
    data = _fields(value, ("body", "bow", "drift"), report, rule, where, line, "a body (violin, viola, cello, bass) or { body, bow, drift }")
    if data is None:
        return None
    body = _choice(data, "body", "auto", ("auto", *BODY_NAMES), report, rule, where, line)
    bow = _num(data, "bow", 0.3, 0, 1, report, rule, where, line, " (bow noise)")
    drift = _num(data, "drift", 5.0, 0, 30, report, rule, where, line, " cents each player wanders")
    if body is None or bow is None or drift is None:
        return None
    return Bowed(body, bow, drift)


def _additive(value: Any, report: Report, rule: str, where: str, line: int | None) -> Additive | None:
    if isinstance(value, str):
        value = {"partials": value}
    data = _fields(value, ("partials", "drawbars", "stretch"), report, rule, where, line,
                   "a preset name or { partials | drawbars, stretch }")  # fmt: skip
    if data is None:
        return None
    stretch = _num(data, "stretch", 0.0, 0, 0.02, report, rule, where, line, " (inharmonicity; 0.0005 is piano-like)")
    if stretch is None:
        return None
    if ("partials" in data) == ("drawbars" in data):
        report.error(rule, f"additive needs partials (a preset: {', '.join(ADDITIVE_PRESETS)}; harmonic amplitudes [1, 0.5, 0.3]; or "
                     "[[ratio, amp], [ratio, amp, decay_s], ...]) or drawbars (\"888000000\")", line, where)  # fmt: skip
        return None
    if "drawbars" in data:
        bars = data["drawbars"]
        bars = str(bars) if isinstance(bars, int) and not isinstance(bars, bool) else bars
        if not (isinstance(bars, str) and len(bars) == 9 and all(c in "012345678" for c in bars) and bars.strip("0")):
            report.error(rule, "drawbars must be nine digits 0-8 (16' 5 1/3' 8' 4' 2 2/3' 2' 1 3/5' 1 1/3' 1'), e.g. \"888000000\"", line, f"{where}.drawbars")
            return None
        return Additive(drawbars(bars), stretch)
    raw = data["partials"]
    if isinstance(raw, str):
        if raw not in ADDITIVE_PRESETS:
            report.error(rule, f"partials preset must be one of {', '.join(ADDITIVE_PRESETS)}", line, f"{where}.partials")
            return None
        return Additive(ADDITIVE_PRESETS[raw], stretch)
    if not isinstance(raw, list) or not raw or len(raw) > 64:
        report.error(rule, "partials must be a list of 1-64 harmonic amplitudes, or [ratio, amp] / [ratio, amp, decay_s] items", line, f"{where}.partials")
        return None
    partials: list[tuple[float, float, float | None]] = []
    for i, item in enumerate(raw):
        if is_number(item) and 0 <= item <= 1:
            if item > 0:
                partials.append((float(i + 1), float(item), None))
        elif isinstance(item, list) and len(item) in (2, 3) and all(is_number(v) for v in item) and 0.1 <= item[0] <= 64 and 0 <= item[1] <= 1 \
                and (len(item) == 2 or 0.01 <= item[2] <= 30):  # fmt: skip
            partials.append((float(item[0]), float(item[1]), float(item[2]) if len(item) == 3 else None))
        else:
            report.error(rule, f"partial {i + 1}: an amplitude 0-1, or [ratio 0.1-64, amp 0-1] / [ratio, amp, decay 0.01-30 s]", line, f"{where}.partials.{i}")
            return None
    if not partials:
        report.error(rule, "partials are all zero", line, f"{where}.partials")
        return None
    return Additive(tuple(partials), stretch)


def _wavetable(value: Any, report: Report, rule: str, where: str, line: int | None) -> Wavetable | None:
    if isinstance(value, str):
        value = {"table": value}
    data = _fields(value, ("table", "position", "env", "env_amount", "lfo"), report, rule, where, line,
                   f"a table ({', '.join(WAVETABLES)}) or {{ table, position, env, env_amount, lfo }}")  # fmt: skip
    if data is None:
        return None
    table = _choice(data, "table", "analog", WAVETABLES, report, rule, where, line)
    position = _num(data, "position", 0.0, 0, 1, report, rule, where, line, " (through the table's frames)")
    amount = _num(data, "env_amount", 0.0, -1, 1, report, rule, where, line, " (of the table the envelope moves the position)")
    env = parse_env(data["env"], report, rule, f"{where}.env", line) if "env" in data else None
    lfo = data.get("lfo")
    if lfo is not None and not (isinstance(lfo, list) and len(lfo) == 2 and all(is_number(v) for v in lfo) and 0 < lfo[0] <= 50 and 0 <= lfo[1] <= 1):
        report.error(rule, "lfo must be [rate_hz, depth 0-1] (moves the position)", line, f"{where}.lfo")
        return None
    if table is None or position is None or amount is None or ("env" in data and env is None):
        return None
    return Wavetable(table, position, env, amount, (float(lfo[0]), float(lfo[1])) if lfo is not None else None)


def vowel_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = VOWEL_ALIASES.get(value.lower(), value.lower())
    return name if name in VOWELS else None


def _formant(value: Any, report: Report, rule: str, where: str, line: int | None) -> Formant | None:
    if isinstance(value, str):
        value = {"vowel": value}
    data = _fields(value, ("vowel", "voice", "breath", "drift"), report, rule, where, line, "a vowel (a e i o u, ah oh oo ee eh) or { vowel, voice, breath, drift }")
    if data is None:
        return None
    voice = _choice(data, "voice", "auto", ("auto", *VOICES), report, rule, where, line)
    breath = _num(data, "breath", 0.1, 0, 1, report, rule, where, line, " (noise in the voice)")
    drift = _num(data, "drift", 4.0, 0, 30, report, rule, where, line, " cents each singer wanders")
    raw = data.get("vowel", "a")
    vowels: list[tuple[float, str]] = []
    if isinstance(raw, str):
        name = vowel_name(raw)
        if name is not None:
            vowels.append((0.0, name))
    elif isinstance(raw, list) and raw:
        for item in raw:  # [ah, oh] (spread over a second each) or [[0, ah], [0.8, oh]]
            if isinstance(item, list) and len(item) == 2 and is_number(item[0]) and item[0] >= 0 and vowel_name(item[1]):
                vowels.append((float(item[0]), vowel_name(item[1])))  # type: ignore[arg-type]
            elif vowel_name(item):
                vowels.append((float(len(vowels)), vowel_name(item)))  # type: ignore[arg-type]
            else:
                vowels = []
                break
    if not vowels or any(b[0] < a[0] for a, b in zip(vowels, vowels[1:])):
        report.error(rule, "vowel must be a, e, i, o, u (or ah, eh, ee, oh, oo), a list of them ([ah, oh]: one per second) or keyframes "
                     "[[seconds, vowel], ...] in time order", line, f"{where}.vowel")  # fmt: skip
        return None
    if voice is None or breath is None or drift is None:
        return None
    return Formant(tuple(vowels), voice, breath, drift)


def _modal(value: Any, report: Report, rule: str, where: str, line: int | None) -> Modal | None:
    if isinstance(value, str):
        value = {"material": value}
    data = _fields(value, ("material", "strike", "decay"), report, rule, where, line, f"a material ({', '.join(MATERIALS)}) or {{ material, strike, decay }}")
    if data is None:
        return None
    material = _choice(data, "material", "marimba", tuple(MATERIALS), report, rule, where, line)
    strike = _num(data, "strike", 0.5, 0, 1, report, rule, where, line, " (mallet hardness)")
    decay = _num(data, "decay", MATERIALS.get(str(data.get("material", "marimba")), MATERIALS["marimba"])[1], 0.02, 30, report, rule, where, line,
                 " seconds the fundamental rings at C4")  # fmt: skip
    if material is None or strike is None or decay is None:
        return None
    return Modal(material, strike, decay if "decay" in data else None)


def parse_sub(value: Any, report: Report, rule: str, where: str, line: int | None) -> Sub | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = {"octave": value}
    data = _fields(value, ("octave", "wave", "level"), report, rule, where, line, "an octave (-1, -2) or { octave, wave, level }")
    if data is None:
        return None
    octave = data.get("octave", -1)
    if octave not in (-1, -2) or isinstance(octave, bool):
        report.error(rule, "sub.octave must be -1 or -2", line, f"{where}.octave")
        return None
    wave = _choice(data, "wave", "sine", ("sine", "square", "triangle"), report, rule, where, line)
    level = _num(data, "level", -6.0, -60, 12, report, rule, where, line, " dB against the main oscillator")
    if wave is None or level is None:
        return None
    return Sub(int(octave), wave, level)


def parse_sync(value: Any, report: Report, rule: str, where: str, line: int | None) -> Sync | None:
    if is_number(value):
        value = {"ratio": value}
    data = _fields(value, ("ratio", "env_amount", "env"), report, rule, where, line, "a ratio (1-16) or { ratio, env_amount, env }")
    if data is None:
        return None
    ratio = _num(data, "ratio", 2.0, 1, 16, report, rule, where, line, " (slave pitch / note pitch)")
    amount = _num(data, "env_amount", 0.0, 0, 4, report, rule, where, line, " octaves the envelope sweeps the ratio")
    env = parse_env(data["env"], report, rule, f"{where}.env", line) if "env" in data else None
    if ratio is None or amount is None or ("env" in data and env is None):
        return None
    return Sync(ratio, amount, env)


def _impulse_pitch(value: Any) -> float | None:
    if isinstance(value, str):
        note = parse_note_value(value)
        return float(note) if note is not None else None
    if is_number(value) and 20 <= value <= 20000:
        return round(hz_to_midi(float(value)), 9)
    return None


def parse_impulses(value: Any, report: Report, rule: str, where: str, line: int | None) -> Impulses | None:
    data = _fields(value, ("density", "shape", "pitch", "decay", "level"), report, rule, where, line, "{ density, shape, pitch, decay, level }")
    if data is None:
        return None
    default = Impulses()
    density = _num(data, "density", default.density, 0.1, 2000, report, rule, where, line, " impulses per second")
    shape = _choice(data, "shape", default.shape, IMPULSE_SHAPES, report, rule, where, line)
    decay = _num(data, "decay", default.decay, 0.001, 2, report, rule, where, line, " seconds per impulse")
    pitch: tuple[float, float] | None = default.pitch
    if "pitch" in data:
        raw = data["pitch"]
        pair = [_impulse_pitch(v) for v in raw] if isinstance(raw, list) and len(raw) == 2 else []
        lo, hi = (pair[0], pair[1]) if len(pair) == 2 else (None, None)
        if lo is None or hi is None or lo > hi:
            report.error(rule, "pitch must be [low, high]: notes (C5) or Hz (20-20000), e.g. [300, 3000]", line, f"{where}.pitch")
            pitch = None
        else:
            pitch = (lo, hi)
    level: tuple[float, float] | None = default.level
    if "level" in data:
        raw = data["level"]
        if isinstance(raw, list) and len(raw) == 2 and all(is_number(v) for v in raw) and 0 <= raw[0] <= raw[1] <= 1:
            level = (float(raw[0]), float(raw[1]))
        else:
            report.error(rule, "level must be [low, high] amplitudes 0-1, e.g. [0.5, 1]", line, f"{where}.level")
            level = None
    if density is None or shape is None or decay is None or pitch is None or level is None:
        return None
    return Impulses(density, shape, pitch, decay, level)


def describe_model(model: Model) -> str:
    if isinstance(model, Pluck):
        return f"decay {model.decay:g}s, brightness {model.brightness:g}"
    if isinstance(model, Bowed):
        return f"{model.body} body"
    if isinstance(model, Additive):
        return f"{len(model.partials)} partials"
    if isinstance(model, Wavetable):
        return f"table {model.table}"
    if isinstance(model, Formant):
        return f"vowel {'-'.join(v for _, v in model.vowels)}, {model.voice}"
    if isinstance(model, Modal):
        return model.material
    return f"spread {model.spread:g} cents"
