"""Instrument patches: the synth parameters shared by kit instruments, inline instruments and SFX layers.

A patch is a sound source (`osc: sine|triangle|saw|pulse|noise|bitnoise|fm`, `drum: kick|snare|hat|clap|tom|
cymbal` or `sample:` a WAV / SFZ / SoundFont / sample library) plus envelope, pitch modulation, filter, gain
and crush. Parsing collects every problem as a Finding.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from segan.findings import Finding
from segan.notes import note_name, parse_note
from segan.samples import SampleSpec
from segan.yamlio import LineMap

OSCILLATORS = ("sine", "triangle", "saw", "pulse", "noise", "bitnoise", "fm")
DRUMS = ("kick", "snare", "hat", "clap", "tom", "cymbal")
FILTER_TYPES = ("lp", "hp", "bp")
RESERVED_KEYS = (".", "-", "|")  # rest, hold, bar line

# Drum defaults: tune (Hz), decay (s), tone (Hz), noise (mix 0-1), click (0-1), punch (semitones of pitch drop)
DRUM_DEFAULTS: dict[str, dict[str, float]] = {
    "kick": {"tune": 52.0, "decay": 0.28, "tone": 4000.0, "noise": 0.0, "click": 0.35, "punch": 30.0},
    "snare": {"tune": 185.0, "decay": 0.16, "tone": 3200.0, "noise": 0.65, "click": 0.2, "punch": 7.0},
    "hat": {"tune": 400.0, "decay": 0.045, "tone": 8000.0, "noise": 1.0, "click": 0.0, "punch": 0.0},
    "clap": {"tune": 200.0, "decay": 0.22, "tone": 1300.0, "noise": 1.0, "click": 0.0, "punch": 0.0},
    "tom": {"tune": 110.0, "decay": 0.32, "tone": 2500.0, "noise": 0.08, "click": 0.2, "punch": 9.0},
    "cymbal": {"tune": 400.0, "decay": 1.1, "tone": 6500.0, "noise": 0.5, "click": 0.0, "punch": 0.0},
}
DRUM_PARAMS = ("tune", "decay", "tone", "noise", "click", "punch")

PATCH_FIELDS = (
    "name", "osc", "drum", "sample", "duty", "pwm", "fm", "detune", "unison", "env", "pitch_env", "vibrato", "tremolo",
    "arp", "arp_rate", "filter", "gain", "pan", "range", "voices", "crush", "note", *DRUM_PARAMS,
)  # fmt: skip


@dataclass(frozen=True)
class Env:
    attack: float = 0.005
    decay: float = 0.1
    sustain: float = 0.7
    release: float = 0.1

    def as_list(self) -> list[float]:
        return [self.attack, self.decay, self.sustain, self.release]


@dataclass(frozen=True)
class Filter:
    type: str = "lp"
    cutoff: float = 2000.0
    resonance: float = 0.0
    env_amount: float = 0.0  # octaves the envelope moves the cutoff at its peak
    env: Env | None = None  # defaults to the amplitude envelope
    keytrack: float = 0.0  # 0 = fixed cutoff, 1 = follows the note pitch


@dataclass(frozen=True)
class Crush:
    bits: int = 0  # 0 = off
    rate: float = 0.0  # Hz, 0 = off


@dataclass(frozen=True)
class FM:
    ratio: float = 2.0
    index: float = 1.0  # modulation index (radians)
    env: Env | None = None  # index envelope (0..index); None = constant


@dataclass(frozen=True)
class Instrument:
    key: str = "?"
    name: str = ""
    source: str = "osc"  # osc | drum
    wave: str = "pulse"  # oscillator or drum kind
    duty: float = 0.5
    pwm: tuple[float, float] | None = None  # rate Hz, depth (duty +/-)
    fm: FM | None = None
    detune: float = 0.0  # cents (spread width with unison > 1)
    unison: int = 1
    env: Env = field(default_factory=Env)
    pitch_env: tuple[tuple[float, float], ...] = ()  # (seconds, semitones) keyframes
    vibrato: tuple[float, float, float] | None = None  # rate Hz, depth semitones, delay s
    tremolo: tuple[float, float] | None = None  # rate Hz, depth 0-1
    arp: tuple[int, ...] = ()
    arp_rate: float = 20.0
    filter: Filter | None = None
    gain: float = 0.0  # dB
    pan: float = 0.0
    range: tuple[int, int] | None = None
    voices: int = 1
    crush: Crush | None = None
    note: int = 60  # pitch for one-shot hits (drum lanes, SFX layers without a pitch)
    drum: dict[str, float] = field(default_factory=dict)  # drum parameters (tune, decay, ...)
    sample: SampleSpec | None = None  # source "sample"
    sample_text: Any = field(default=None, compare=False)  # the `sample:` value as written (for `segan bake sfx`)
    line: int | None = None

    @property
    def is_drum(self) -> bool:
        return self.source == "drum"

    def drum_param(self, name: str) -> float:
        return self.drum.get(name, DRUM_DEFAULTS[self.wave][name]) if self.is_drum else DRUM_DEFAULTS["kick"][name]

    @property
    def is_sample(self) -> bool:
        return self.sample is not None

    def tail(self) -> float:
        """Seconds the sound keeps going after its gate closes (release, a drum's decay, a one-shot sample's length)."""
        if self.sample is not None:
            from segan.samples import load_set

            sset = load_set(self.sample)
            return max(self.env.release, sset.longest() if sset.one_shot else 0.0)
        if self.is_drum:
            return self.drum_param("decay") * (1.6 if self.wave in ("snare", "clap") else 1.0)
        return self.env.release

    def describe(self) -> str:
        if self.is_drum:
            return f"drum {self.wave}"
        if self.sample is not None:
            return f"sample {self.sample.kind} {Path(self.sample.path).stem}"
        return f"{self.wave}" + (f" duty {self.duty:g}" if self.wave == "pulse" else "")

    def to_yaml_fields(self) -> dict[str, Any]:
        """The patch as plain YAML-able fields (for `segan bake sfx`)."""
        out: dict[str, Any] = {}
        if self.name:
            out["name"] = self.name
        if self.is_drum:
            out["drum"] = self.wave
            out.update({k: v for k, v in sorted(self.drum.items())})
        elif self.sample is not None:
            out["sample"] = self.sample_text
            out["env"] = self.env.as_list()
        else:
            out["osc"] = self.wave
            if self.wave == "pulse":
                out["duty"] = self.duty
            out["env"] = self.env.as_list()
        if self.pwm:
            out["pwm"] = list(self.pwm)
        if self.fm:
            out["fm"] = {"ratio": self.fm.ratio, "index": self.fm.index, **({"env": self.fm.env.as_list()} if self.fm.env else {})}
        if self.detune:
            out["detune"] = self.detune
        if self.unison != 1:
            out["unison"] = self.unison
        if self.pitch_env:
            out["pitch_env"] = [list(k) for k in self.pitch_env]
        if self.vibrato:
            out["vibrato"] = list(self.vibrato)
        if self.tremolo:
            out["tremolo"] = list(self.tremolo)
        if self.arp:
            out["arp"] = list(self.arp)
            out["arp_rate"] = self.arp_rate
        if self.filter:
            f = self.filter
            out["filter"] = {"type": f.type, "cutoff": f.cutoff, "resonance": f.resonance, "env_amount": f.env_amount,
                             "keytrack": f.keytrack, **({"env": f.env.as_list()} if f.env else {})}  # fmt: skip
        if self.gain:
            out["gain"] = self.gain
        if self.pan:
            out["pan"] = self.pan
        if self.range:
            out["range"] = [note_name(self.range[0]), note_name(self.range[1])]
        if self.voices != 1:
            out["voices"] = self.voices
        if self.crush:
            out["crush"] = {"bits": self.crush.bits, "rate": self.crush.rate}
        return out


class Report:
    """Collects findings for one file; every message should say how to fix the problem."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.findings: list[Finding] = []

    def error(self, rule: str, message: str, line: int | None = None, where: str | None = None) -> None:
        self.findings.append(Finding(rule, message, self.path, line, where))

    warn = error  # warnings are findings with a W rule id

    @property
    def failed(self) -> bool:
        return any(f.severity == "error" for f in self.findings)


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def line_of(data: Any, key: Any, default: int | None = None) -> int | None:
    if isinstance(data, LineMap):
        return data.line_of(key) or default
    return default


def number(
    data: dict[str, Any], key: str, lo: float, hi: float, report: Report, rule: str, where: str, hint: str = ""
) -> float | None:
    value: Any = data.get(key)
    if not is_number(value) or not lo <= value <= hi:
        report.error(rule, f"{key} must be a number {lo:g}..{hi:g}{hint}", line_of(data, key), f"{where}.{key}")
        return None
    return float(value)


def parse_env(value: Any, report: Report, rule: str, where: str, line: int | None) -> Env | None:
    """`[attack, decay, sustain, release]` or `{attack, decay, sustain, release}` (seconds, 0-1 sustain)."""
    names = ("attack", "decay", "sustain", "release")
    if isinstance(value, list):
        if len(value) != 4 or not all(is_number(v) for v in value):
            report.error(rule, "env must be [attack, decay, sustain, release] (seconds, seconds, 0-1, seconds)", line, where)
            return None
        parts = [float(v) for v in value]
    elif isinstance(value, dict):
        unknown = [k for k in value if k not in names]
        if unknown:
            report.error(rule, f"unknown env field {unknown[0]!r}; allowed: {', '.join(names)}", line, where)
            return None
        defaults = Env()
        parts = [float(value.get(n, getattr(defaults, n))) if is_number(value.get(n, 0)) else math.nan for n in names]
    else:
        report.error(rule, "env must be [attack, decay, sustain, release]", line, where)
        return None
    attack, decay, sustain, release = parts
    if not all(0 <= t <= 30 for t in (attack, decay, release)) or not 0 <= sustain <= 1:
        report.error(rule, "env times must be 0-30 seconds and sustain 0-1 (e.g. [0.005, 0.1, 0.7, 0.2])", line, where)
        return None
    return Env(attack, decay, sustain, release)


def parse_keyframes(
    value: Any, report: Report, rule: str, where: str, line: int | None, convert: Callable[[Any], float | None], what: str
) -> tuple[tuple[float, float], ...] | None:
    """`[[t, v], [t, v], ...]` with t ascending (seconds) and v converted (notes, Hz, dB...)."""
    if not isinstance(value, list) or not value:
        report.error(rule, f"{where.rsplit('.', 1)[-1]} keyframes must be a list of [seconds, {what}] pairs", line, where)
        return None
    frames: list[tuple[float, float]] = []
    for i, item in enumerate(value):
        if not (isinstance(item, list) and len(item) == 2 and is_number(item[0]) and item[0] >= 0):
            report.error(rule, f"keyframe {i} must be [seconds, {what}], seconds >= 0", line, f"{where}.{i}")
            return None
        converted = convert(item[1])
        if converted is None:
            report.error(rule, f"keyframe {i}: {item[1]!r} isn't a valid {what}", line, f"{where}.{i}")
            return None
        if frames and item[0] < frames[-1][0]:
            report.error(rule, f"keyframe {i}: times must not go backwards ({item[0]} after {frames[-1][0]})", line, f"{where}.{i}")
            return None
        frames.append((float(item[0]), converted))
    return tuple(frames)


def _semitones(v: Any) -> float | None:
    return float(v) if is_number(v) and -96 <= v <= 96 else None


def parse_note_value(value: Any) -> int | None:
    """A note name, or a MIDI number 0-127."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 127:
        return value
    return parse_note(value)


def parse_patch(
    data: dict[str, Any],
    report: Report,
    rule: str,
    where: str,
    key: str = "?",
    base: Instrument | None = None,
    extra: Iterable[str] = (),
) -> Instrument | None:
    """Parse instrument fields from `data` on top of `base` (or the defaults). Fields in `extra` are left
    for the caller (SFX layers add start/pitch/...); anything else unknown is an error."""
    start = len(report.findings)
    line = data.line if isinstance(data, LineMap) else None
    allowed = (*PATCH_FIELDS, *extra)
    for name in data:
        if name not in allowed:
            report.error(rule, f"unknown instrument field {name!r}; allowed: {', '.join(PATCH_FIELDS)}", line_of(data, name, line), f"{where}.{name}")
    inst = base or Instrument()
    changes: dict[str, Any] = {"key": key, "line": line}

    has_osc, has_drum, has_sample = "osc" in data, "drum" in data, "sample" in data
    if has_osc + has_drum + has_sample > 1:
        report.error(rule, "give one sound source: osc, drum or sample", line, where)
    elif has_sample:
        sline = line_of(data, "sample", line)
        parsed = parse_sample(data["sample"], report, rule, f"{where}.sample", sline)
        if parsed is not None:
            spec, sset = parsed
            changes.update(source="sample", wave="sample", drum={}, sample=spec, sample_text=data["sample"])
            if "env" not in data:  # the file's own envelope (SFZ ampeg_*, SF2 volume envelope)
                e = sset.env
                changes["env"] = Env(round(e.attack, 6), round(e.hold + e.decay, 6), round(e.sustain, 6), round(min(30.0, e.release), 6))
            if "range" not in data and base is None and sset.key_span() != (0, 127):
                changes["range"] = sset.key_span()
    elif has_osc:
        if data["osc"] not in OSCILLATORS:
            report.error(rule, f"osc must be one of {', '.join(OSCILLATORS)}", line_of(data, "osc", line), f"{where}.osc")
        else:
            changes.update(source="osc", wave=data["osc"], drum={})
    elif has_drum:
        if data["drum"] not in DRUMS:
            report.error(rule, f"drum must be one of {', '.join(DRUMS)}", line_of(data, "drum", line), f"{where}.drum")
        else:
            changes.update(source="drum", wave=data["drum"], drum={} if inst.wave != data["drum"] else dict(inst.drum))
    elif base is None:
        report.error(rule, "an instrument needs a sound source: osc (sine, triangle, saw, pulse, noise, bitnoise, fm), drum (kick, snare, hat, clap, tom, cymbal) "
                     "or sample (a .wav/.sfz/.sf2 file or a library instrument like vsco2/violins_sus)", line, where)

    if "name" in data:
        if not isinstance(data["name"], str) or not data["name"]:
            report.error(rule, "name must be a short text, e.g. pulse_lead", line_of(data, "name", line), f"{where}.name")
        else:
            changes["name"] = data["name"]
    if "duty" in data and (v := number(data, "duty", 0.01, 0.99, report, rule, where, " (0.5 = square, 0.125 = thin)")) is not None:
        changes["duty"] = v
    if "pwm" in data:
        pwm = data["pwm"]
        if isinstance(pwm, list) and len(pwm) == 2 and all(is_number(v) for v in pwm) and 0 < pwm[0] <= 50 and 0 <= pwm[1] < 0.5:
            changes["pwm"] = (float(pwm[0]), float(pwm[1]))
        else:
            report.error(rule, "pwm must be [rate_hz, depth] (rate 0-50, depth 0-0.49 of duty)", line_of(data, "pwm", line), f"{where}.pwm")
    if "fm" in data:
        fm = data["fm"]
        if not isinstance(fm, dict) or any(k not in ("ratio", "index", "env") for k in fm):
            report.error(rule, "fm must be { ratio, index, env }", line_of(data, "fm", line), f"{where}.fm")
        else:
            ratio = fm.get("ratio", 2.0)
            index = fm.get("index", 1.0)
            fm_env = parse_env(fm["env"], report, rule, f"{where}.fm.env", line_of(data, "fm", line)) if "env" in fm else None
            if not (is_number(ratio) and 0.01 <= ratio <= 32 and is_number(index) and 0 <= index <= 50):
                report.error(rule, "fm.ratio must be 0.01-32 and fm.index 0-50", line_of(data, "fm", line), f"{where}.fm")
            else:
                changes["fm"] = FM(float(ratio), float(index), fm_env)
    if "detune" in data and (v := number(data, "detune", -1200, 1200, report, rule, where, " cents")) is not None:
        changes["detune"] = v
    if "unison" in data:
        u = data["unison"]
        if not (isinstance(u, int) and not isinstance(u, bool) and 1 <= u <= 8):
            report.error(rule, "unison must be a whole number 1-8 (voices spread over +/- detune cents)", line_of(data, "unison", line), f"{where}.unison")
        else:
            changes["unison"] = u
    if "env" in data and (env := parse_env(data["env"], report, rule, f"{where}.env", line_of(data, "env", line))) is not None:
        changes["env"] = env
    if "pitch_env" in data:
        pe = data["pitch_env"]
        pline = line_of(data, "pitch_env", line)
        if isinstance(pe, list) and len(pe) == 2 and all(is_number(v) for v in pe):
            amount, time = float(pe[0]), float(pe[1])
            if not (-96 <= amount <= 96 and 0 < time <= 30):
                report.error(rule, "pitch_env [semitones, seconds]: start that far from the note and glide to it (-96..96, 0-30 s)", pline, f"{where}.pitch_env")
            else:
                changes["pitch_env"] = ((0.0, amount), (time, 0.0))
        elif (frames := parse_keyframes(pe, report, rule, f"{where}.pitch_env", pline, _semitones, "semitones")) is not None:
            changes["pitch_env"] = frames
    if "vibrato" in data:
        vib = data["vibrato"]
        if isinstance(vib, list) and len(vib) in (2, 3) and all(is_number(v) for v in vib) and 0 < vib[0] <= 50 and 0 <= vib[1] <= 12 and (len(vib) == 2 or vib[2] >= 0):
            changes["vibrato"] = (float(vib[0]), float(vib[1]), float(vib[2]) if len(vib) == 3 else 0.0)
        else:
            report.error(rule, "vibrato must be [rate_hz, depth_semitones] or [rate, depth, delay_s] (e.g. [5.5, 0.15])", line_of(data, "vibrato", line), f"{where}.vibrato")
    if "tremolo" in data:
        trem = data["tremolo"]
        if isinstance(trem, list) and len(trem) == 2 and all(is_number(v) for v in trem) and 0 < trem[0] <= 50 and 0 <= trem[1] <= 1:
            changes["tremolo"] = (float(trem[0]), float(trem[1]))
        else:
            report.error(rule, "tremolo must be [rate_hz, depth 0-1]", line_of(data, "tremolo", line), f"{where}.tremolo")
    if "arp" in data:
        arp = data["arp"]
        if isinstance(arp, list) and 1 <= len(arp) <= 16 and all(isinstance(v, int) and not isinstance(v, bool) and -48 <= v <= 48 for v in arp):
            changes["arp"] = tuple(arp)
        else:
            report.error(rule, "arp must be a list of semitone offsets, e.g. [0, 4, 7] (a major chord as a fast arpeggio)", line_of(data, "arp", line), f"{where}.arp")
    if "arp_rate" in data and (v := number(data, "arp_rate", 1, 100, report, rule, where, " notes per second")) is not None:
        changes["arp_rate"] = v
    if "filter" in data:
        filt = _parse_filter(data["filter"], report, rule, f"{where}.filter", line_of(data, "filter", line))
        if filt is not None:
            changes["filter"] = filt
    if "gain" in data and (v := number(data, "gain", -60, 24, report, rule, where, " dB")) is not None:
        changes["gain"] = v
    if "pan" in data and (v := number(data, "pan", -1, 1, report, rule, where, " (-1 left, 1 right)")) is not None:
        changes["pan"] = v
    if "range" in data:
        rng = data["range"]
        notes = [parse_note_value(n) for n in rng] if isinstance(rng, list) and len(rng) == 2 else []
        if len(notes) != 2 or None in notes or notes[0] > notes[1]:  # type: ignore[operator]
            report.error(rule, "range must be [lowest, highest] notes, e.g. [E1, C4]", line_of(data, "range", line), f"{where}.range")
        else:
            changes["range"] = (notes[0], notes[1])
    if "voices" in data:
        voices = data["voices"]
        if not (isinstance(voices, int) and not isinstance(voices, bool) and 1 <= voices <= 16):
            report.error(rule, "voices must be 1-16 (notes this instrument can play at once; 1 = mono, like chiptune)", line_of(data, "voices", line), f"{where}.voices")
        else:
            changes["voices"] = voices
    if "crush" in data:
        crush = parse_crush(data["crush"], report, rule, f"{where}.crush", line_of(data, "crush", line))
        if crush is not None:
            changes["crush"] = crush
    if "note" in data:
        note = parse_note_value(data["note"])
        if note is None:
            report.error(rule, "note must be a note name like C4 (the pitch of one-shot hits)", line_of(data, "note", line), f"{where}.note")
        else:
            changes["note"] = note

    source_is_drum = changes.get("source", inst.source) == "drum"
    drum_params = dict(changes.get("drum", inst.drum))
    for name in DRUM_PARAMS:
        if name not in data:
            continue
        if not source_is_drum:
            report.error(rule, f"{name} is a drum parameter; this instrument isn't a drum", line_of(data, name, line), f"{where}.{name}")
            continue
        lo, hi = {"tune": (20, 4000), "decay": (0.005, 5), "tone": (50, 18000), "noise": (0, 1), "click": (0, 1), "punch": (0, 48)}[name]
        if (v := number(data, name, lo, hi, report, rule, where)) is not None:
            drum_params[name] = v
    changes["drum"] = drum_params
    if len(report.findings) > start and any(f.severity == "error" for f in report.findings[start:]):
        return None
    return replace(inst, **changes)


SAMPLE_FIELDS = ("wav", "sfz", "sf2", "library", "instrument", "root", "loop", "one_shot", "preset", "bank", "velocity")


def project_root(path: Path | None) -> Path:
    """The folder with segan.toml above `path` (relative sample paths start there), else the current folder."""
    if path is not None:
        for folder in path.resolve().parents:
            if (folder / "segan.toml").is_file():
                return folder
    return Path.cwd()


def parse_sample(value: Any, report: Report, rule: str, where: str, line: int | None) -> tuple[SampleSpec, Any] | None:
    """`sample: path.wav|.sfz|.sf2`, `sample: vsco2/violins_sus`, or the mapping form:
    `{ wav|sfz|sf2: path, root, loop, one_shot, preset, bank, velocity }` / `{ library: vsco2, instrument: x }`."""
    from segan.libraries import LibraryError, library_spec
    from segan.samples import SampleError, file_stamp, load_set

    if isinstance(value, str):
        suffix = Path(value).suffix.lower()
        if suffix in (".wav", ".sfz", ".sf2"):
            value = {suffix[1:]: value}
        elif "/" in value and not suffix:
            lib, _, inst = value.partition("/")
            value = {"library": lib, "instrument": inst}
        else:
            report.error(rule, f"sample {value!r} must be a .wav, .sfz or .sf2 path, or a library instrument like vsco2/violins_sus", line, where)
            return None
    if not isinstance(value, dict) or any(k not in SAMPLE_FIELDS for k in value):
        report.error(rule, f"sample must be a path or a mapping of {', '.join(SAMPLE_FIELDS)}", line, where)
        return None
    kinds = [k for k in ("wav", "sfz", "sf2", "library") if k in value]
    if len(kinds) != 1:
        report.error(rule, "sample needs exactly one of wav, sfz, sf2 or library", line, where)
        return None
    kind = kinds[0]
    root_note = parse_note_value(value.get("root", "C4"))
    preset, bank, velocity = value.get("preset"), value.get("bank", 0), value.get("velocity")
    flags = {k: value[k] for k in ("loop", "one_shot") if k in value}
    if root_note is None:
        report.error(rule, "sample.root must be the note the WAV was recorded at, e.g. A4", line, f"{where}.root")
        return None
    if any(not isinstance(v, bool) for v in flags.values()):
        report.error(rule, "sample.loop and sample.one_shot must be true or false", line, where)
        return None
    if preset is not None and not (isinstance(preset, str) or (isinstance(preset, int) and not isinstance(preset, bool) and 0 <= preset <= 127)):
        report.error(rule, "sample.preset must be a program number 0-127 or a preset name", line, f"{where}.preset")
        return None
    if not (isinstance(bank, int) and not isinstance(bank, bool) and 0 <= bank <= 128):
        report.error(rule, "sample.bank must be 0-128 (128 = GM percussion)", line, f"{where}.bank")
        return None
    if velocity is not None and not (isinstance(velocity, int) and not isinstance(velocity, bool) and 1 <= velocity <= 127):
        report.error(rule, "sample.velocity must be 1-127 (always play that velocity layer)", line, f"{where}.velocity")
        return None
    if kind != "wav" and "root" in value or kind != "sf2" and ("preset" in value or "bank" in value) or kind == "library" and "instrument" not in value:
        report.error(rule, "sample: root is for wav, preset/bank for sf2, and library needs instrument (e.g. { library: vsco2, instrument: violins_sus })", line, where)
        return None
    try:
        if kind == "library":
            spec = library_spec(str(value["library"]), str(value["instrument"]))
        else:
            path = Path(str(value[kind]))
            path = path if path.is_absolute() else (project_root(report.path) / path)
            if not path.is_file():
                report.error(rule, f"sample file {value[kind]!r} not found (relative paths start at the project folder: {project_root(report.path)})", line, f"{where}.{kind}")
                return None
            spec = SampleSpec(kind, str(path.resolve()), base=str(path.resolve().parent), stamp=(file_stamp(path),))
        from dataclasses import replace as _replace

        spec = _replace(spec, root=root_note, loop=flags.get("loop"), one_shot=flags.get("one_shot"),
                        preset=preset, bank=bank, velocity=velocity)  # fmt: skip
        sset = load_set(spec)
    except (SampleError, LibraryError) as exc:
        report.error(rule, f"sample: {exc}", line, where)
        return None
    return spec, sset


def parse_crush(value: Any, report: Report, rule: str, where: str, line: int | None) -> Crush | None:
    if not isinstance(value, dict) or any(k not in ("bits", "rate") for k in value):
        report.error(rule, "crush must be { bits: 1-16 (0 = off), rate: Hz (0 = off) }", line, where)
        return None
    bits, rate = value.get("bits", 0), value.get("rate", 0)
    if not (isinstance(bits, int) and not isinstance(bits, bool) and 0 <= bits <= 16):
        report.error(rule, "crush.bits must be 0 (off) or 1-16", line, f"{where}.bits")
        return None
    if not (is_number(rate) and (rate == 0 or 200 <= rate <= 48000)):
        report.error(rule, "crush.rate must be 0 (off) or 200-48000 Hz", line, f"{where}.rate")
        return None
    return Crush(bits, float(rate))


def _parse_filter(value: Any, report: Report, rule: str, where: str, line: int | None) -> Filter | None:
    allowed = ("type", "cutoff", "resonance", "env_amount", "env", "keytrack")
    if not isinstance(value, dict):
        report.error(rule, "filter must be { type: lp|hp|bp, cutoff: Hz, resonance: 0-1, env_amount: octaves, env, keytrack }", line, where)
        return None
    for k in value:
        if k not in allowed:
            report.error(rule, f"unknown filter field {k!r}; allowed: {', '.join(allowed)}", line, f"{where}.{k}")
            return None
    ftype = value.get("type", "lp")
    if ftype not in FILTER_TYPES:
        report.error(rule, "filter.type must be lp (low-pass), hp (high-pass) or bp (band-pass)", line, f"{where}.type")
        return None
    cutoff = value.get("cutoff", 2000)
    resonance = value.get("resonance", 0.0)
    amount = value.get("env_amount", 0.0)
    keytrack = value.get("keytrack", 0.0)
    if not (is_number(cutoff) and 20 <= cutoff <= 20000):
        report.error(rule, "filter.cutoff must be 20-20000 Hz", line, f"{where}.cutoff")
        return None
    if not (is_number(resonance) and 0 <= resonance <= 1):
        report.error(rule, "filter.resonance must be 0-1", line, f"{where}.resonance")
        return None
    if not (is_number(amount) and -8 <= amount <= 8):
        report.error(rule, "filter.env_amount must be -8..8 octaves", line, f"{where}.env_amount")
        return None
    if not (is_number(keytrack) and 0 <= keytrack <= 1):
        report.error(rule, "filter.keytrack must be 0-1", line, f"{where}.keytrack")
        return None
    env = parse_env(value["env"], report, rule, f"{where}.env", line) if "env" in value else None
    if "env" in value and env is None:
        return None
    return Filter(ftype, float(cutoff), float(resonance), float(amount), env, float(keytrack))
