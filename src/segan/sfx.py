"""SFX (`sfx/<name>.sfx.yaml`): parametric sound effects (SEGAN's 3D models: rendered through the
project's shared [mix], so every SFX gets the same room, crush and loudness).

```yaml
name: coin
category: pickup
preset: coin            # optional starting point (presets/*.yaml)
duration: 0.25
layers:
  - id: tone
    osc: pulse
    pitch: [[0, B5], [0.06, E6]]     # keyframes (seconds, note | Hz); slide: true glides
    env: [0.002, 0.05, 0.4, 0.15]
variations: { count: 4, seed: 7, pitch: 0.5, timbre: 0.1 }
phases:
  charge: { duration: 1.0, loop: true, layers: [...] }
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from segan.asset import META_FIELDS, SFX_SUFFIX, Meta, load_source, merge_template, parse_meta, resolve_extends, resolve_kit
from segan.dsp import hz_to_midi
from segan.findings import Finding
from segan.kit import Kit
from segan.patch import Instrument, Report, is_number, line_of, parse_keyframes, parse_note_value, parse_patch
from segan.yamlio import LineMap, parse_yaml

if TYPE_CHECKING:
    from segan.project import Project

PRESETS = ("coin", "jump", "laser", "explosion", "hit", "hurt", "powerup", "blip", "select", "door", "step")
SFX_FIELDS = (*META_FIELDS, "category", "kit", "instruments", "groups", "preset", "duration", "layers", "variations", "phases", "room",
              "loop", "crossfade", "normalize")  # fmt: skip
LAYER_EXTRA = ("id", "instrument", "start", "length", "pitch", "slide", "gain", "cutoff", "distort", "delay", "ring")
PHASE_FIELDS = ("duration", "loop", "layers", "crossfade")
MAX_DURATION = 30.0


@dataclass(frozen=True)
class Layer:
    inst: Instrument
    id: str | None = None
    start: float = 0.0
    length: float | None = None  # gate seconds (default: until the release ends at `duration`)
    pitch: tuple[tuple[float, float], ...] | None = None  # (seconds, MIDI) keyframes
    slide: bool = False
    gain: tuple[tuple[float, float], ...] | None = None  # (seconds, dB) keyframes
    cutoff: tuple[tuple[float, float], ...] | None = None  # (seconds, Hz) keyframes
    distort: float = 0.0
    delay: tuple[float, float, float] | None = None  # time s, feedback, mix
    ring: tuple[float, float] | None = None  # Hz, mix
    line: int | None = None
    index: int = 0

    def base_midi(self) -> float:
        return self.pitch[0][1] if self.pitch else float(self.inst.note)

    def top_midi(self) -> float:
        return max(v for _, v in self.pitch) if self.pitch else float(self.inst.note)


@dataclass(frozen=True)
class Variations:
    count: int
    seed: int = 0
    pitch: float = 0.0  # +/- semitones
    timbre: float = 0.0  # 0-1 amount of jitter in duty, filter and envelope times
    gain: float = 0.0  # +/- dB
    include_main: bool = True  # false: build only the variations (the game plays them through a randomizer)
    timing: float = 0.0  # +/- seconds each layer's start moves (never before 0)
    envelope: float = 0.0  # 0-1: each layer's attack/decay/release scaled by up to 2x either way
    length: float = 0.0  # 0-0.5: the whole sound (duration, layer starts, lengths, keyframe times) stretched by up to +/- this


@dataclass(frozen=True)
class Phase:
    name: str
    duration: float
    loop: bool
    layers: tuple[Layer, ...]
    crossfade: float
    line: int | None = None


@dataclass
class Sfx:
    meta: Meta
    category: str
    kit: Kit | None
    duration: float
    layers: tuple[Layer, ...]
    loop: bool = False
    crossfade: float = 0.05
    variations: Variations | None = None
    phases: dict[str, Phase] = field(default_factory=dict)
    normalize: bool = True
    preset: str | None = None
    effective: dict[str, Any] = field(default_factory=dict)  # fields after preset/extends (for `segan bake sfx`)
    room: float | None = None  # room send (0-1, x mix.room); None = the category's [room] entry

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def kind(self) -> str:
        return "sfx"

    @property
    def path(self) -> Path | None:
        return self.meta.path


def preset_text(name: str) -> str:
    return files("segan").joinpath("presets", f"{name}.yaml").read_text(encoding="utf-8")


def preset_data(name: str) -> dict[str, Any]:
    data = parse_yaml(preset_text(name))
    assert isinstance(data, dict)
    return data


_CENTS_RE = re.compile(r"^(.+?)([+-]\d+(?:\.\d+)?)c$")


def _midi_value(value: Any) -> float | None:
    """A note name or MIDI number as text ("A4"), optionally with a cents offset ("A4+15c", "C6-30c"; up to an
    octave), or a number in Hz."""
    if isinstance(value, str):
        cents = 0.0
        if (match := _CENTS_RE.match(value.strip())) is not None:
            value, cents = match.group(1), float(match.group(2))
            if abs(cents) > 1200:
                return None
        midi = parse_note_value(value)
        return round(float(midi) + cents / 100.0, 9) if midi is not None else None
    if is_number(value) and 20 <= value <= 20000:
        return round(hz_to_midi(float(value)), 9)
    return None


def _db(value: Any) -> float | None:
    return float(value) if is_number(value) and -96 <= value <= 24 else None


def _hz(value: Any) -> float | None:
    return float(value) if is_number(value) and 20 <= value <= 20000 else None


def parse_layer(raw: Any, index: int, kit: Kit | None, report: Report, where: str) -> Layer | None:
    rule = "E013"
    if not isinstance(raw, dict):
        report.error(rule, "a layer must be a mapping of instrument fields (osc/drum, env, pitch...)", None, where)
        return None
    line = raw.line if isinstance(raw, LineMap) else None
    base: Instrument | None = None
    if "instrument" in raw:
        key = raw["instrument"]
        if kit is None or not isinstance(key, str) or key not in kit.instruments:
            known = " ".join(kit.instruments) if kit else "no kit"
            report.error(rule, f"instrument {key!r} isn't in the kit (keys: {known})", line_of(raw, "instrument", line), f"{where}.instrument")
            return None
        base = kit.instruments[key]
    patch_fields = {k: v for k, v in raw.items() if not (k == "gain" and isinstance(v, list))}
    if isinstance(raw, LineMap):
        patch = LineMap()
        patch.update(patch_fields)
        patch.line, patch.key_lines = raw.line, raw.key_lines
        patch_fields = patch
    inst = parse_patch(patch_fields, report, rule, where, key=f"layer{index}", base=base, extra=LAYER_EXTRA)
    if inst is None:
        return None
    errors = len(report.findings)
    lid = raw.get("id")
    if lid is not None and (not isinstance(lid, str) or not lid):
        report.error(rule, "id must be a short name (templates and presets merge layers by id)", line_of(raw, "id", line), f"{where}.id")
    start = raw.get("start", 0.0)
    if not (is_number(start) and 0 <= start <= MAX_DURATION):
        report.error(rule, "start must be seconds from the beginning (0-30)", line_of(raw, "start", line), f"{where}.start")
        start = 0.0
    length = raw.get("length")
    if length is not None and not (is_number(length) and 0 < length <= MAX_DURATION):
        report.error(rule, "length must be the seconds the layer is held before its release (0-30)", line_of(raw, "length", line), f"{where}.length")
        length = None
    pitch = None
    if "pitch" in raw:
        value = raw["pitch"]
        pline = line_of(raw, "pitch", line)
        if isinstance(value, list):
            pitch = parse_keyframes(value, report, rule, f"{where}.pitch", pline, _midi_value, "note (A4, A4+15c) or Hz")
        elif (single := _midi_value(value)) is not None:
            pitch = ((0.0, single),)
        else:
            report.error(rule, "pitch must be a note (A4, or A4+15c with a cents offset), Hz (440) or keyframes [[seconds, note|Hz], ...]", pline, f"{where}.pitch")
    slide = raw.get("slide", False)
    if not isinstance(slide, bool):
        report.error(rule, "slide must be true (glide between pitch keyframes) or false (step)", line_of(raw, "slide", line), f"{where}.slide")
        slide = False
    gain = None
    if isinstance(raw.get("gain"), list):
        gain = parse_keyframes(raw["gain"], report, rule, f"{where}.gain", line_of(raw, "gain", line), _db, "dB")
    cutoff = None
    if "cutoff" in raw:
        cutoff = parse_keyframes(raw["cutoff"], report, rule, f"{where}.cutoff", line_of(raw, "cutoff", line), _hz, "Hz (20-20000)")
    distort = raw.get("distort", 0.0)
    if not (is_number(distort) and 0 <= distort <= 1):
        report.error(rule, "distort must be 0-1", line_of(raw, "distort", line), f"{where}.distort")
        distort = 0.0
    delay = None
    if "delay" in raw:
        d = raw["delay"]
        if isinstance(d, dict) and set(d) <= {"time", "feedback", "mix"} and is_number(d.get("time", 0.15)) and 0.01 <= d.get("time", 0.15) <= 2 \
                and is_number(d.get("feedback", 0.4)) and 0 <= d.get("feedback", 0.4) < 0.95 and is_number(d.get("mix", 0.4)) and 0 <= d.get("mix", 0.4) <= 1:  # fmt: skip
            delay = (float(d.get("time", 0.15)), float(d.get("feedback", 0.4)), float(d.get("mix", 0.4)))
        else:
            report.error(rule, "delay must be { time: 0.01-2 s, feedback: 0-0.95, mix: 0-1 }", line_of(raw, "delay", line), f"{where}.delay")
    ring = None
    if "ring" in raw:
        r = raw["ring"]
        if isinstance(r, dict) and set(r) <= {"freq", "mix"} and is_number(r.get("freq")) and 1 <= r["freq"] <= 8000 and is_number(r.get("mix", 1.0)) and 0 <= r.get("mix", 1.0) <= 1:
            ring = (float(r["freq"]), float(r.get("mix", 1.0)))
        else:
            report.error(rule, "ring must be { freq: Hz 1-8000, mix: 0-1 } (ring modulation)", line_of(raw, "ring", line), f"{where}.ring")
    if len(report.findings) > errors:
        return None
    return Layer(inst, lid, float(start), float(length) if length is not None else None, pitch, slide, gain, cutoff, float(distort), delay, ring, line, index)


def _layers(raw: Any, kit: Kit | None, report: Report, where: str, line: int | None) -> tuple[Layer, ...] | None:
    if not isinstance(raw, list) or not raw:
        report.error("E013", "layers must be a non-empty list of layers (each: osc or drum, env, pitch...)", line, where)
        return None
    layers = [parse_layer(item, i, kit, report, f"{where}.{i}") for i, item in enumerate(raw)]
    ids = [layer.id for layer in layers if layer is not None and layer.id]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        report.error("E013", f"layer id {dup!r} is used twice", line, where)
    if any(layer is None for layer in layers):
        return None
    return tuple(layer for layer in layers if layer is not None)


def _duration(value: Any, report: Report, where: str, line: int | None) -> float | None:
    if not (is_number(value) and 0.01 <= value <= MAX_DURATION):
        report.error("E013", f"duration must be seconds, 0.01-{MAX_DURATION:g}", line, where)
        return None
    return float(value)


def load_sfx(path: Path, project: Project) -> tuple[Sfx | None, list[Finding]]:
    report = Report(path)
    try:
        data = load_source(path)
    except Exception as exc:  # noqa: BLE001 - SeganError carries findings
        return None, list(getattr(exc, "findings", [Finding("E001", str(exc), path)]))
    return parse_sfx(data, path, project, report)


def parse_sfx(data: dict[str, Any], path: Path | None, project: Project, report: Report | None = None) -> tuple[Sfx | None, list[Finding]]:
    report = report or Report(path)
    folder = path.parent if path is not None else None
    data, chain = resolve_extends(data, path, folder, SFX_SUFFIX, report)
    line = data.line if isinstance(data, LineMap) else None
    preset = data.get("preset")
    if preset is not None:
        if preset not in PRESETS:
            report.error("E013", f"unknown preset {preset!r}; presets: {', '.join(PRESETS)}", line_of(data, "preset", line), "preset")
        else:
            child = LineMap()
            child.update(data)
            if isinstance(data, LineMap):
                child.line, child.key_lines = data.line, data.key_lines
            data = merge_template(preset_data(preset), child)
            for own in ("name", "description", "tags", "status", "style_version", "template"):
                if own in child:
                    data[own] = child[own]
    for key in data:
        if key not in SFX_FIELDS:
            report.error("E013", f"unknown SFX field {key!r}; allowed: {', '.join(SFX_FIELDS)}", line_of(data, key, line), str(key))
    meta = parse_meta(data, path, "sfx", report, "E013")
    meta.sources = [p for p in ([path] if path else [])] + chain
    category = data.get("category", "sfx")
    if not (isinstance(category, str) and category.replace("_", "a").isalnum() and category == category.lower()):
        report.error("E013", "category must be a lowercase word (sfx, ui, pickup...); it picks the loudness target", line_of(data, "category", line), "category")
        category = "sfx"
    kit = resolve_kit(data, project, report, "E013")
    duration = _duration(data.get("duration", 0.5), report, "duration", line_of(data, "duration", line))
    has_phases = isinstance(data.get("phases"), dict) and bool(data.get("phases"))
    layers: tuple[Layer, ...] | None = ()
    if "layers" in data or not has_phases:
        layers = _layers(data.get("layers"), kit, report, "layers", line_of(data, "layers", line))
    loop = data.get("loop", False)
    if not isinstance(loop, bool):
        report.error("E013", "loop must be true or false (a looping SFX: engine hum, alarm)", line_of(data, "loop", line), "loop")
        loop = False
    crossfade = data.get("crossfade", 0.05)
    if not (is_number(crossfade) and 0 <= crossfade <= 1):
        report.error("E008", "crossfade must be 0-1 seconds (how the end of a loop blends into its start)", line_of(data, "crossfade", line), "crossfade")
        crossfade = 0.05
    normalize = data.get("normalize", True)
    if not isinstance(normalize, bool):
        report.error("E013", "normalize must be true or false", line_of(data, "normalize", line), "normalize")
        normalize = True
    variations = _variations(data.get("variations"), report, line_of(data, "variations", line))
    room = data.get("room")
    if room is not None and not (is_number(room) and 0 <= room <= 1):
        report.error("E013", "room must be a send of 0-1 (x the project's mix.room; 0 = dry, no tail)", line_of(data, "room", line), "room")
        room = None
    phases: dict[str, Phase] = {}
    raw_phases = data.get("phases")
    if raw_phases is not None:
        if not isinstance(raw_phases, dict):
            report.error("E008", "phases must map a phase name to { duration, loop, layers }", line_of(data, "phases", line), "phases")
        else:
            for pname, praw in raw_phases.items():
                phase = _phase(str(pname), praw, layers or (), kit, report, line_of(raw_phases, pname, line))
                if phase is not None:
                    phases[str(pname)] = phase
    if duration is not None and loop and crossfade >= duration / 2:
        report.error("E008", f"crossfade {crossfade:g}s must be under half the loop's duration ({duration:g}s)", line_of(data, "crossfade", line), "crossfade")
    if report.failed or duration is None or layers is None:
        return None, report.findings
    sfx = Sfx(meta, category, kit, duration, layers, loop, float(crossfade), variations, phases, normalize,
              preset if isinstance(preset, str) else None, dict(data), float(room) if room is not None else None)  # fmt: skip
    return sfx, report.findings


def _variations(raw: Any, report: Report, line: int | None) -> Variations | None:
    if raw is None:
        return None
    allowed = ("count", "seed", "pitch", "timbre", "gain", "timing", "envelope", "length", "include_main")
    if not isinstance(raw, dict) or any(k not in allowed for k in raw):
        report.error("E013", "variations must be { count, seed, pitch (semitones), timbre (0-1), gain (dB), timing (s), envelope (0-1), length (0-0.5), include_main }", line, "variations")
        return None
    count, seed = raw.get("count", 4), raw.get("seed", 0)
    pitch, timbre, gain = raw.get("pitch", 0.0), raw.get("timbre", 0.0), raw.get("gain", 0.0)
    if not (isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 32):
        report.error("E013", "variations.count must be 1-32", line, "variations.count")
    elif not (isinstance(seed, int) and not isinstance(seed, bool)):
        report.error("E013", "variations.seed must be a whole number (change it for a different set)", line, "variations.seed")
    elif not (is_number(pitch) and 0 <= pitch <= 12 and is_number(timbre) and 0 <= timbre <= 1 and is_number(gain) and 0 <= gain <= 12):
        report.error("E013", "variations: pitch 0-12 semitones, timbre 0-1, gain 0-12 dB (each is the most a variation moves)", line, "variations")
    elif not (is_number(timing := raw.get("timing", 0.0)) and 0 <= timing <= 0.5):
        report.error("E013", "variations.timing must be 0-0.5 seconds: the most each layer's start moves, earlier or later", line, "variations.timing")
    elif not (is_number(envelope := raw.get("envelope", 0.0)) and 0 <= envelope <= 1 and is_number(length := raw.get("length", 0.0)) and 0 <= length <= 0.5):
        report.error("E013", "variations: envelope 0-1 (envelope times up to 2x longer or shorter), length 0-0.5 (the sound up to 50% longer or shorter)", line, "variations")
    elif not isinstance(include_main := raw.get("include_main", True), bool):
        report.error("E013", "variations.include_main must be true or false (false: build only <name>.1..N.wav)", line, "variations.include_main")
    else:
        return Variations(count, seed, float(pitch), float(timbre), float(gain), include_main, float(timing), float(envelope), float(length))
    return None


def _phase(name: str, raw: Any, base: tuple[Layer, ...], kit: Kit | None, report: Report, line: int | None) -> Phase | None:
    where = f"phases.{name}"
    if not isinstance(raw, dict) or any(k not in PHASE_FIELDS for k in raw):
        report.error("E008", f"phase {name!r} must be {{ duration, loop, layers, crossfade }}", line, where)
        return None
    if not name.isidentifier() or not name[0].isalpha():
        report.error("E008", f"phase name {name!r} must start with a letter (outputs are <sfx>.<phase>.wav)", line, where)
        return None
    pline = raw.line if isinstance(raw, LineMap) else line
    duration = _duration(raw.get("duration", 0.5), report, f"{where}.duration", pline)
    loop = raw.get("loop", False)
    crossfade = raw.get("crossfade", 0.05)
    if not isinstance(loop, bool) or not (is_number(crossfade) and 0 <= crossfade <= 1):
        report.error("E008", "phase loop must be true/false and crossfade 0-1 s", pline, where)
        return None
    layers = _layers(raw["layers"], kit, report, f"{where}.layers", pline) if "layers" in raw else base
    if not layers:
        if layers is not None:
            report.error("E008", f"phase {name!r} has no layers (give it layers, or give the SFX base layers)", pline, where)
        return None
    if duration is None:
        return None
    if loop and crossfade >= duration / 2:
        report.error("E008", f"phase {name!r}: crossfade must be under half its duration", pline, where)
        return None
    return Phase(name, duration, loop, layers, float(crossfade), pline)
