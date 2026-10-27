"""Songs (`music/<name>.song.yaml`): step-grid patterns over a kit, in a key (SEGAN's sprites).

Roll lanes have one row per scale note in the track's range (highest first): a kit key starts a note,
`-` holds it, `.` rests. Drum lanes have one row per drum key: `x` hit, `X` accent, `o` ghost. `|` is a
bar line (ignored). Trailing row labels (`A5`, `k`) are checked, so a missing row can't shift the grid.
Patterns are arranged into sections, sections into the arrangement; `loop` names where the loop starts.
A section can change its patterns' notes at play time (key change, transposition, swaps, mutes, velocity), and
`flow` lets the game walk the sections as a weighted graph instead of one fixed arrangement.
"""

from __future__ import annotations

import fnmatch
import itertools
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from segan.asset import META_FIELDS, SONG_SUFFIX, Meta, load_source, parse_meta, resolve_extends, resolve_kit
from segan.findings import Finding
from segan.kit import Kit
from segan.notes import Key, parse_key, parse_note, transpose_key
from segan.patch import Instrument, Report, is_number, line_of, parse_note_value
from segan.yamlio import LineMap

if TYPE_CHECKING:
    from segan.project import Project

SONG_FIELDS = (*META_FIELDS, "kit", "instruments", "groups", "tempo", "meter", "steps_per_beat", "swing", "key", "tracks",
               "patterns", "sections", "arrangement", "loop", "variants", "variant_axes", "markers", "normalize", "category", "stems",
               "flow", "sample_rate", "channels", "seed", "humanize", "fade_in", "fade_out")  # fmt: skip
DYNAMICS_FIELDS = ("velocity", "dynamics")  # per-pattern: velocity marks per step, dB ramps per track
MAX_RELEASE = 30.0  # seconds: a track's or pattern's release override (the kit's env allows the same)
VELOCITY_MARKS = {"X": 1.5, "x": 1.0, "o": 0.35, ".": None, "-": None, **{str(d): round(0.2 * d, 2) for d in range(1, 10)}}
STEM_FIELDS = ("groups", "mixes", "main_mix")
TRACK_FIELDS = ("roll", "drums", "chromatic", "gain", "pan", "release")
DERIVE_FIELDS = ("from", "transpose", "semitones", "shift", "reverse", "mute", "swap")
VARIANT_FIELDS = ("tempo", "swing", "instrument_swap", "group_swap", "kit", "transpose", "semitones", "key")
SECTION_FIELDS = ("patterns", "from", "transpose", "semitones", "key", "instrument_swap", "group_swap", "mute", "velocity")
FLOW_FIELDS = ("start", "next", "end", "no_repeat", "variants")
DRUM_MARKS = {"x": 1.0, "X": 1.5, "o": 0.35}
TRACK_RE = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_STEPS = 1024


@dataclass(frozen=True)
class Track:
    name: str
    drums: bool
    rows: tuple[int, ...] | tuple[str, ...]  # MIDI notes (roll, highest first) or drum keys
    gain: float = 0.0
    pan: float = 0.0
    line: int | None = None
    release: float | None = None  # seconds: overrides the release of every note on the track (roll tracks only)

    def label(self, row: int, key: Key | None) -> str:
        value = self.rows[row]
        if isinstance(value, str):
            return value
        return key.name(value) if key is not None else str(value)


@dataclass(frozen=True)
class Note:
    track: str
    row: int
    step: int
    length: int
    key: str
    velocity: float = 1.0
    release: float | None = None  # seconds: the pattern's release override for this note's track


@dataclass
class Pattern:
    name: str
    length: int
    notes: list[Note]
    lanes: set[str] = field(default_factory=set)  # tracks this pattern writes (or derives)
    line: int | None = None
    source: str | None = None  # derived from
    release: dict[str, float] = field(default_factory=dict)  # track -> release override (seconds), a derived pattern's included


@dataclass(frozen=True)
class Variant:
    name: str
    tempo: float | None = None
    swing: float | None = None
    swaps: tuple[tuple[str, str], ...] = ()  # instrument key -> key
    kit: Kit | None = None
    kit_name: str | None = None
    transpose: int = 0  # scale degrees
    semitones: int = 0
    key: Key | None = None
    line: int | None = None

    def combine(self, other: Variant, name: str) -> Variant:
        """Two variant-axis options applied together (`a+b`)."""
        return Variant(name, other.tempo or self.tempo, other.swing if other.swing is not None else self.swing,
                       self.swaps + other.swaps, other.kit or self.kit, other.kit_name or self.kit_name,
                       self.transpose + other.transpose, self.semitones + other.semitones, other.key or self.key)  # fmt: skip


@dataclass(frozen=True)
class SectionChange:
    """What a section changes about its patterns' notes, at play time and before a song variant: pitch (key,
    transpose, semitones), instrument swaps, muted tracks and velocity scales."""

    pitch: Variant
    mute: tuple[str, ...] = ()
    velocity: tuple[tuple[str, float], ...] = ()  # track -> scale


@dataclass(frozen=True)
class Flow:
    """`flow:` - the sections as a graph the game walks: weighted successors, where it starts, the optional
    ending section (reachable from every section) and the variants that get flow clips too."""

    start: tuple[str, ...]
    next: tuple[tuple[str, tuple[tuple[str, float], ...]], ...]  # section -> ((successor, weight), ...)
    end: str | None = None
    no_repeat: bool = True
    variants: tuple[str, ...] = ()

    @property
    def sections(self) -> list[str]:
        """Every section the flow can play, in a stable order (starts, then as listed, then the ending)."""
        out = list(self.start)
        for name, succ in self.next:
            out += [name, *(s for s, _ in succ)]
        if self.end:
            out.append(self.end)
        return list(dict.fromkeys(out))

    def successors(self, section: str) -> tuple[tuple[str, float], ...]:
        return dict(self.next).get(section, ())

    def predecessors(self, section: str) -> list[str]:
        """Sections that can be followed by `section` (every other section, for the ending)."""
        if section == self.end:
            return [s for s in self.sections if s != section]
        return [p for p in self.sections if any(s == section for s, _ in self.successors(p))]


@dataclass(frozen=True)
class Stems:
    """`stems:` - which tracks share a stem WAV (groups), the stem combinations the game plays (mixes: the
    stems are normalised so the loudest mix hits the target), and whether the full mix is built at all."""

    groups: tuple[tuple[str, tuple[str, ...]], ...] = ()  # group -> tracks, in source order
    mixes: tuple[tuple[str, tuple[str, ...]], ...] = ()  # mix -> groups
    main_mix: bool = True


@dataclass
class Song:
    meta: Meta
    kit: Kit
    tempo: float
    meter: tuple[int, int]
    steps_per_beat: int
    swing: float
    key: Key
    tracks: dict[str, Track]
    patterns: dict[str, Pattern]
    sections: dict[str, list[str]]
    arrangement: list[str]
    loop: str | None  # a section name, or None (no loop)
    markers: dict[str, tuple[str, int]] = field(default_factory=dict)
    variants: dict[str, Variant] = field(default_factory=dict)
    variant_axes: dict[str, dict[str, Variant]] = field(default_factory=dict)
    normalize: bool = True
    category: str = "music"
    stems: Stems | None = None
    section_changes: dict[str, SectionChange] = field(default_factory=dict)
    flow: Flow | None = None
    section_sources: dict[str, str] = field(default_factory=dict)  # section -> the section it derives from
    sample_rate: int | None = None  # the song's own output rate / channels ([mix] sample_rate / music_channels otherwise)
    channels: str | None = None
    seed: int | None = None  # the song's own seed (humanize); default: from its name
    humanize: tuple[float, float] = (0.0, 0.0)  # timing (ms, +/-), velocity (fraction, +/-)
    fades: tuple[float, float] = (0.0, 0.0)  # fade in over the first, fade out over the last seconds (non-looping songs)

    @property
    def name(self) -> str:
        return self.meta.name

    def played_sections(self) -> list[str]:
        """The arrangement's sections, then the flow's sections the arrangement doesn't play."""
        out = list(dict.fromkeys(self.arrangement))
        if self.flow is not None:
            out += [s for s in self.flow.sections if s not in out]
        return out

    @property
    def kind(self) -> str:
        return "song"

    def stem_groups(self) -> dict[str, tuple[str, ...]]:
        """Stem WAV name -> the tracks summed into it (one per track unless `stems.groups` says otherwise)."""
        if self.stems is not None and self.stems.groups:
            return dict(self.stems.groups)
        return {name: (name,) for name in self.tracks}

    @property
    def path(self) -> Path | None:
        return self.meta.path

    @property
    def steps_per_bar(self) -> int:
        return self.meter[0] * self.steps_per_beat

    def all_variants(self) -> dict[str, Variant]:
        """Plain variants plus every combination of the variant axes (`calm+night`)."""
        out = dict(self.variants)
        combos: list[Variant] = [Variant("")]
        for options in self.variant_axes.values():
            combos = [base.combine(opt, f"{base.name}+{opt.name}" if base.name else opt.name) for base in combos for opt in options.values()]
        if self.variant_axes:
            out.update({v.name: v for v in combos})
        return out

    def used_keys(self) -> set[str]:
        return {n.key for p in self.patterns.values() for n in p.notes}


def _bad(report: Report, rule: str, message: str, line: int | None, where: str) -> None:
    report.error(rule, message, line, where)


def _int_field(data: dict[str, Any], key: str, lo: int, hi: int, default: int, report: Report, rule: str, where: str, line: int | None) -> int:
    value = data.get(key, default)
    if not (isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi):
        _bad(report, rule, f"{key} must be a whole number {lo}-{hi}", line_of(data, key, line), where)
        return default
    return value


def parse_tracks(raw: Any, kit: Kit, key: Key | None, report: Report, line: int | None) -> dict[str, Track]:
    tracks: dict[str, Track] = {}
    if not isinstance(raw, dict) or not raw:
        _bad(report, "E001", "tracks must map track names to { roll: [low, high] } or { drums: [keys] }", line, "tracks")
        return tracks
    for name, value in raw.items():
        where = f"tracks.{name}"
        tline = line_of(raw, name, line)
        if not isinstance(name, str) or not TRACK_RE.match(name):
            _bad(report, "E001", f"track name {name!r} must be lowercase letters, digits or '_'", tline, where)
            continue
        if not isinstance(value, dict) or any(k not in TRACK_FIELDS for k in value):
            _bad(report, "E001", f"track {name!r} must be {{ roll: [low, high], chromatic, gain, pan, release }} or {{ drums: [keys], gain, pan }}", tline, where)
            continue
        gain, pan = value.get("gain", 0.0), value.get("pan", 0.0)
        if not (is_number(gain) and -60 <= gain <= 24 and is_number(pan) and -1 <= pan <= 1):
            _bad(report, "E001", f"track {name!r}: gain must be -60..24 dB and pan -1..1", tline, where)
            continue
        if ("roll" in value) == ("drums" in value):
            _bad(report, "E001", f"track {name!r} needs exactly one of roll: [low, high] (melodic) or drums: [keys]", tline, where)
            continue
        release = value.get("release")
        if release is not None and ("drums" in value or not (is_number(release) and 0 <= release <= MAX_RELEASE)):
            why = "drum hits ring for their decay; release is for roll tracks" if "drums" in value else f"release must be 0-{MAX_RELEASE:g} seconds"
            _bad(report, "E001", f"track {name!r}: {why}", line_of(value, "release", tline), f"{where}.release")
            continue
        if "drums" in value:
            keys = value["drums"]
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
                _bad(report, "E001", f"track {name!r}: drums must list kit keys, e.g. [k, s, h]", tline, f"{where}.drums")
                continue
            missing = [k for k in keys if k not in kit.instruments]
            if missing:
                _bad(report, "E002", f"track {name!r}: drum key(s) {', '.join(map(repr, missing))} aren't in the kit (keys: {' '.join(kit.instruments)})", tline, f"{where}.drums")
                continue
            if len(set(keys)) != len(keys):
                _bad(report, "E001", f"track {name!r}: a drum key is listed twice", tline, f"{where}.drums")
                continue
            tracks[name] = Track(name, True, tuple(keys), float(gain), float(pan), tline)
            continue
        rng = value["roll"]
        notes = [parse_note_value(n) for n in rng] if isinstance(rng, list) and len(rng) == 2 else []
        if len(notes) != 2 or notes[0] is None or notes[1] is None or notes[0] > notes[1]:
            _bad(report, "E001", f"track {name!r}: roll must be [lowest, highest] notes, e.g. [A2, A3]", tline, f"{where}.roll")
            continue
        chromatic = value.get("chromatic", False)
        if not isinstance(chromatic, bool):
            _bad(report, "E001", f"track {name!r}: chromatic must be true or false", tline, f"{where}.chromatic")
            continue
        low, high = notes[0], notes[1]
        if chromatic or key is None:
            rows: tuple[int, ...] = tuple(range(high, low - 1, -1))
        else:
            rows = tuple(key.notes_between(low, high))
        if not rows:
            _bad(report, "E001", f"track {name!r}: no notes of {key.describe() if key else 'the key'} between {rng[0]} and {rng[1]}", tline, f"{where}.roll")
            continue
        if len(rows) > 64:
            _bad(report, "E001", f"track {name!r}: {len(rows)} rows is too many; keep a roll within about two octaves", tline, f"{where}.roll")
            continue
        tracks[name] = Track(name, False, rows, float(gain), float(pan), tline, float(release) if release is not None else None)
    return tracks


def _split_row(text: str) -> tuple[str, str | None, str | None]:
    """(cells, label, problem) for one grid row."""
    parts = text.split()
    if not parts:
        return "", None, None
    if len(parts) > 2:
        return parts[0].replace("|", ""), parts[1], "a row is the grid plus at most one label; spaces aren't allowed inside the grid"
    return parts[0].replace("|", ""), (parts[1] if len(parts) == 2 else None), None


def parse_lane(text: Any, track: Track, length: int, kit: Kit, key: Key | None, report: Report, where: str, line: int | None) -> list[Note]:
    """A lane's notes; every problem is reported with the row's file line."""
    notes: list[Note] = []
    if not isinstance(text, str):
        _bad(report, "E003", f"lane {track.name!r} must be a block of grid rows (use `|` and one row per line)", line, where)
        return notes
    rows = text.split("\n")
    while rows and not rows[-1].strip():
        rows.pop()
    first = (line + 1) if line is not None else None
    if len(rows) != len(track.rows):
        expected = ", ".join(track.label(i, key) for i in range(len(track.rows)))
        _bad(report, "E003", f"lane {track.name!r} has {len(rows)} rows; the track has {len(track.rows)} ({expected}), highest first", line, where)
        return notes
    for r, raw in enumerate(rows):
        rline = first + r if first is not None else None
        cells, label, problem = _split_row(raw)
        rwhere = f"{where} row {r + 1}"
        if problem:
            _bad(report, "E003", problem, rline, rwhere)
            continue
        if len(cells) != length:
            _bad(report, "E003", f"row {r + 1} has {len(cells)} steps; the pattern length is {length} (`|` bar lines don't count)", rline, rwhere)
            continue
        expected = track.label(r, key)
        if label is not None:
            ok = label == expected if track.drums else parse_note(label) == track.rows[r]
            if not ok:
                _bad(report, "E011", f"row {r + 1} is labelled {label!r} but that row is {expected!r}: a row is missing or extra above it", rline, rwhere)
                continue
        if track.drums:
            drum = str(track.rows[r])
            for step, char in enumerate(cells):
                if char == ".":
                    continue
                if char not in DRUM_MARKS:
                    _bad(report, "E002", f"{char!r} at step {step + 1} isn't a drum mark: x hit, X accent, o ghost, . rest", rline, f"{rwhere} col {step + 1}")
                    continue
                notes.append(Note(track.name, r, step, 1, drum, DRUM_MARKS[char]))
            continue
        current: Note | None = None
        for step, char in enumerate(cells):
            if char == "-":
                if current is None:
                    _bad(report, "E015", f"'-' at step {step + 1} holds nothing: a hold must follow a note on the same row", rline, f"{rwhere} col {step + 1}")
                else:
                    current = replace(current, length=current.length + 1)
                continue
            if current is not None:
                notes.append(current)
                current = None
            if char == ".":
                continue
            if char not in kit.instruments:
                _bad(report, "E002", f"{char!r} at step {step + 1} isn't a kit key, '.', '-' or '|' (keys: {' '.join(kit.instruments)})", rline, f"{rwhere} col {step + 1}")
                continue
            current = Note(track.name, r, step, 1, char)
        if current is not None:
            notes.append(current)
    return notes


@dataclass
class _Context:
    kit: Kit
    key: Key | None
    tracks: dict[str, Track]
    raw: dict[str, Any]
    report: Report
    line: int | None
    done: dict[str, Pattern] = field(default_factory=dict)
    failed: set[str] = field(default_factory=set)


def _resolve_pattern(name: str, ctx: _Context, chain: tuple[str, ...] = ()) -> Pattern | None:
    if name in ctx.done:
        return ctx.done[name]
    if name in ctx.failed:
        return None
    raw = ctx.raw.get(name)
    pline = line_of(ctx.raw, name, ctx.line)
    where = f"patterns.{name}"
    report = ctx.report
    if not isinstance(raw, dict):
        _bad(report, "E001", f"pattern {name!r} must be a mapping: {{ length, <track>: lane }} or {{ from: <pattern>, ... }}", pline, where)
        ctx.failed.add(name)
        return None
    allowed = ("length", *DERIVE_FIELDS, *DYNAMICS_FIELDS, "release", *ctx.tracks)
    for k in raw:
        if k not in allowed:
            hint = f"; tracks: {', '.join(ctx.tracks)}" if k not in DERIVE_FIELDS else ""
            _bad(report, "E001", f"pattern {name!r}: unknown field or track {k!r}{hint}", line_of(raw, k, pline), f"{where}.{k}")
    before = len(report.findings)
    if "from" in raw:
        pattern = _derive(name, raw, ctx, (*chain, name), pline, where)
    else:
        length = raw.get("length")
        if not (isinstance(length, int) and not isinstance(length, bool) and 1 <= length <= MAX_STEPS):
            _bad(report, "E003", f"pattern {name!r} needs length: steps per lane row (e.g. 16 for one 4/4 bar of 16ths)", line_of(raw, "length", pline), f"{where}.length")
            ctx.failed.add(name)
            return None
        notes: list[Note] = []
        lanes: set[str] = set()
        for track in ctx.tracks.values():
            if track.name in raw:
                lanes.add(track.name)
                notes += parse_lane(raw[track.name], track, length, ctx.kit, ctx.key, report, f"{where}.{track.name}", line_of(raw, track.name, pline))
        pattern = Pattern(name, length, notes, lanes, pline)
    if pattern is not None and any(k in raw for k in DYNAMICS_FIELDS):
        pattern.notes = _dynamics(name, raw, pattern, ctx, pline, where)
    if pattern is not None and "release" in raw and "release" not in ctx.tracks:  # a track named `release` keeps its lane
        pattern.release = {**pattern.release, **_release(name, raw["release"], ctx, line_of(raw, "release", pline), f"{where}.release")}
    if pattern is not None and pattern.release:
        pattern.notes = [replace(n, release=pattern.release[n.track]) if n.track in pattern.release else n for n in pattern.notes]
    if pattern is None or any(f.severity == "error" for f in report.findings[before:]):
        ctx.failed.add(name)
        return None
    ctx.done[name] = pattern
    return pattern


def _dynamics(name: str, raw: dict[str, Any], pattern: Pattern, ctx: _Context, pline: int | None, where: str) -> list[Note]:
    """`velocity: { track: "X..o|x.3." }` sets the velocity of the notes starting at each step (X accent, x plain,
    o ghost, 1-9 = 0.2-1.8, . or - keep); `dynamics: { track: [[step, dB], ...] }` then scales them by a ramp
    (steps from 1, linear in dB between points, held before the first and after the last): crescendos, swells."""
    report = ctx.report
    notes = list(pattern.notes)
    marks = raw.get("velocity", {})
    if not isinstance(marks, dict) or any(t not in ctx.tracks or not isinstance(v, str) for t, v in marks.items()):
        _bad(report, "E003", f"pattern {name!r}: velocity must map track names to a row of marks, e.g. {{ lead: \"X...o...x...3...\" }} (tracks: {', '.join(ctx.tracks)})",
             line_of(raw, "velocity", pline), f"{where}.velocity")  # fmt: skip
        return notes
    for track, row in marks.items():
        cells = row.replace("|", "").replace(" ", "")
        if len(cells) != pattern.length or any(c not in VELOCITY_MARKS for c in cells):
            _bad(report, "E003", f"pattern {name!r}: velocity row for {track!r} must be {pattern.length} marks of X (accent), x, o (ghost), 1-9 "
                 f"(0.2-1.8), . or - (unchanged); it has {len(cells)}", line_of(raw, "velocity", pline), f"{where}.velocity.{track}")  # fmt: skip
            continue
        notes = [replace(n, velocity=VELOCITY_MARKS[cells[n.step]] or n.velocity) if n.track == track and VELOCITY_MARKS[cells[n.step]] else n for n in notes]
    ramps = raw.get("dynamics", {})
    if not isinstance(ramps, dict):
        ramps = {"?": None}
    for track, points in ramps.items():
        ok = track in ctx.tracks and isinstance(points, list) and points and all(
            isinstance(p, list) and len(p) == 2 and isinstance(p[0], int) and not isinstance(p[0], bool) and 1 <= p[0] <= pattern.length
            and is_number(p[1]) and -40 <= p[1] <= 12 for p in points) and [p[0] for p in points] == sorted(p[0] for p in points)  # fmt: skip
        if not ok:
            _bad(report, "E003", f"pattern {name!r}: dynamics must map tracks to [[step, dB], ...] (steps 1-{pattern.length} in order, dB -40..12), "
                 "e.g. { strings: [[1, -12], [16, 0]] } (a crescendo)", line_of(raw, "dynamics", pline), f"{where}.dynamics")  # fmt: skip
            continue
        steps, dbs = [p[0] - 1 for p in points], [float(p[1]) for p in points]

        def level(step: int) -> float:
            if step <= steps[0]:
                return dbs[0]
            for (a, da), (b, db) in zip(zip(steps, dbs), zip(steps[1:], dbs[1:])):
                if step <= b:
                    return da + (db - da) * (step - a) / (b - a) if b > a else db
            return dbs[-1]

        notes = [replace(n, velocity=round(n.velocity * 10.0 ** (level(n.step) / 20.0), 6)) if n.track == track else n for n in notes]
    return [replace(n, velocity=min(2.0, max(0.05, n.velocity))) for n in notes]


def _release(name: str, value: Any, ctx: _Context, line: int | None, where: str) -> dict[str, float]:
    """`release: 3.0` (every roll track) or `{ pad: 3.0 }`: the notes of those tracks in this pattern release over
    that many seconds instead of their instrument's release."""
    roll = [t for t, tr in ctx.tracks.items() if not tr.drums]
    if is_number(value):
        value = {t: value for t in roll}
    if not isinstance(value, dict) or not all(k in roll and is_number(v) and 0 <= v <= MAX_RELEASE for k, v in value.items()):
        _bad(ctx.report, "E003", f"pattern {name!r}: release must be seconds (0-{MAX_RELEASE:g}) for every roll track or {{ track: seconds }}, "
             f"e.g. {{ pad: 3.0 }} (roll tracks: {', '.join(roll)}; drum hits ring for their decay)", line, where)  # fmt: skip
        return {}
    return {str(k): float(v) for k, v in value.items()}


def _per_track(value: Any, tracks: dict[str, Track], what: str, report: Report, line: int | None, where: str) -> dict[str, int] | None:
    """`2` (every roll track) or `{lead: 2}`."""
    if isinstance(value, int) and not isinstance(value, bool):
        return {t: value for t, tr in tracks.items() if not tr.drums}
    if isinstance(value, dict) and all(k in tracks and isinstance(v, int) and not isinstance(v, bool) for k, v in value.items()):
        return {str(k): int(v) for k, v in value.items()}
    _bad(report, "E010", f"{what} must be a whole number or {{ track: number }} (tracks: {', '.join(tracks)})", line, where)
    return None


def _derive(name: str, raw: dict[str, Any], ctx: _Context, chain: tuple[str, ...], pline: int | None, where: str) -> Pattern | None:
    report = ctx.report
    source_name = raw["from"]
    if not isinstance(source_name, str) or source_name not in ctx.raw:
        _bad(report, "E010", f"pattern {name!r}: from {source_name!r} isn't a pattern (patterns: {', '.join(ctx.raw)})", line_of(raw, "from", pline), f"{where}.from")
        return None
    if source_name in chain:
        _bad(report, "E010", f"pattern {name!r}: derived patterns form a cycle ({' -> '.join((*chain, source_name))})", line_of(raw, "from", pline), f"{where}.from")
        return None
    source = _resolve_pattern(source_name, ctx, chain)
    if source is None:
        return None
    if "length" in raw and raw["length"] != source.length:
        _bad(report, "E010", f"pattern {name!r}: a derived pattern keeps its source's length ({source.length})", line_of(raw, "length", pline), f"{where}.length")
        return None
    length = source.length
    notes = list(source.notes)
    lanes = set(source.lanes)
    mute = raw.get("mute", [])
    if not isinstance(mute, list) or not all(m in ctx.tracks for m in mute):
        _bad(report, "E010", f"mute must list track names ({', '.join(ctx.tracks)})", line_of(raw, "mute", pline), f"{where}.mute")
        return None
    notes = [n for n in notes if n.track not in mute]
    swap = raw.get("swap", {})
    if not isinstance(swap, dict) or not all(str(k) in ctx.kit.instruments and str(v) in ctx.kit.instruments for k, v in swap.items()):
        _bad(report, "E010", f"swap must map kit keys to kit keys, e.g. {{ p: q }} (keys: {' '.join(ctx.kit.instruments)})", line_of(raw, "swap", pline), f"{where}.swap")
        return None
    swaps = {str(k): str(v) for k, v in swap.items()}
    if swaps:
        swapped = []
        for n in notes:
            track = ctx.tracks[n.track]
            if track.drums:
                swapped.append(n)  # drum rows are fixed keys; swap melodic instruments only
            else:
                swapped.append(replace(n, key=swaps.get(n.key, n.key)))
        notes = swapped
    for field_name, scale_steps in (("transpose", True), ("semitones", False)):
        if field_name not in raw:
            continue
        amounts = _per_track(raw[field_name], ctx.tracks, field_name, report, line_of(raw, field_name, pline), f"{where}.{field_name}")
        if amounts is None:
            return None
        moved = []
        for n in notes:
            amount = amounts.get(n.track, 0)
            track = ctx.tracks[n.track]
            if not amount or track.drums:
                moved.append(n)
                continue
            midi = int(track.rows[n.row])
            target = (ctx.key.degree_shift(midi, amount) if (scale_steps and ctx.key is not None) else midi + amount)
            rows = list(track.rows)
            if target is None or target not in rows:
                what = f"{amount:+d} scale degrees" if scale_steps else f"{amount:+d} semitones"
                why = "isn't a row of the track (off the key: use transpose for scale degrees)" if not scale_steps and target is not None and track.rows[-1] <= target <= track.rows[0] else "falls outside the track's roll range"  # type: ignore[operator]
                _bad(report, "E010", f"pattern {name!r}: moving {n.track} note at step {n.step + 1} by {what} {why}", line_of(raw, field_name, pline), f"{where}.{field_name}")
                return None
            moved.append(replace(n, row=rows.index(target)))
        notes = moved
    if "shift" in raw:
        shift = raw["shift"]
        if not (isinstance(shift, int) and not isinstance(shift, bool)):
            _bad(report, "E010", "shift must be a whole number of steps (+ later, - earlier)", line_of(raw, "shift", pline), f"{where}.shift")
            return None
        shifted = []
        for n in notes:
            start = n.step + shift
            if start < 0 or start >= length:
                _bad(report, "E010", f"pattern {name!r}: shift {shift:+d} pushes a {n.track} note off the pattern (step {start + 1} of {length})", line_of(raw, "shift", pline), f"{where}.shift")
                return None
            if n.length > length - start:
                report.warn("W012", f"pattern {name!r}: shift {shift:+d} cuts a {n.track} note held past the end of the pattern (it stops there)", line_of(raw, "shift", pline), f"{where}.shift")
            shifted.append(replace(n, step=start, length=min(n.length, length - start)))
        notes = shifted
    if "reverse" in raw:
        rev = raw["reverse"]
        targets = set(ctx.tracks) if rev is True else set(rev) if isinstance(rev, list) and all(r in ctx.tracks for r in rev) else None
        if targets is None and rev is not False:
            _bad(report, "E010", "reverse must be true or a list of track names", line_of(raw, "reverse", pline), f"{where}.reverse")
            return None
        notes = [replace(n, step=length - n.step - n.length) if targets and n.track in targets else n for n in notes]
    for track in ctx.tracks.values():
        if track.name in raw:
            notes = [n for n in notes if n.track != track.name]
            notes += parse_lane(raw[track.name], track, length, ctx.kit, ctx.key, report, f"{where}.{track.name}", line_of(raw, track.name, pline))
            lanes.add(track.name)
    lanes -= set(mute)
    return Pattern(name, length, sorted(notes, key=lambda n: (n.track, n.step, n.row)), lanes, pline, source_name, dict(source.release))


def _variant(name: str, raw: Any, song_kit: Kit, project: Project, report: Report, line: int | None, where: str) -> Variant | None:
    if not isinstance(raw, dict) or any(k not in VARIANT_FIELDS for k in raw):
        _bad(report, "E006", f"variant {name!r} must be a mapping of {', '.join(VARIANT_FIELDS)}", line, where)
        return None
    if "+" in name or "." in name or not name[:1].isalpha():
        _bad(report, "E006", f"variant name {name!r} must start with a letter and not contain '+' or '.'", line, where)
        return None
    vline = raw.line if isinstance(raw, LineMap) else line
    tempo, swing = raw.get("tempo"), raw.get("swing")
    if tempo is not None and not (is_number(tempo) and 20 <= tempo <= 400):
        _bad(report, "E006", "variant tempo must be 20-400 bpm", vline, f"{where}.tempo")
        return None
    if swing is not None and not (is_number(swing) and 0 <= swing <= 0.5):
        _bad(report, "E006", "variant swing must be 0-0.5", vline, f"{where}.swing")
        return None
    kit = song_kit
    kit_name = None
    if "kit" in raw:
        try:
            kit = project.load_kit(str(raw["kit"]))
            kit_name = str(raw["kit"])
        except Exception as exc:  # noqa: BLE001 - SeganError carries findings
            _bad(report, "E006", f"variant {name!r}: kit {raw['kit']!r} can't be loaded ({getattr(exc, 'findings', [exc])[0]})", vline, f"{where}.kit")
            return None
    swaps: list[tuple[str, str]] = []
    inst_swap = raw.get("instrument_swap", {})
    if not isinstance(inst_swap, dict):
        _bad(report, "E006", "instrument_swap must map kit keys, e.g. { q: p }", vline, f"{where}.instrument_swap")
        return None
    for a, b in inst_swap.items():
        if str(a) not in song_kit.instruments or str(b) not in kit.instruments:
            _bad(report, "E006", f"instrument_swap {a!r} -> {b!r}: both must be kit keys (keys: {' '.join(kit.instruments)})", vline, f"{where}.instrument_swap")
            return None
        swaps.append((str(a), str(b)))
    group_swap = raw.get("group_swap", {})
    if not isinstance(group_swap, dict):
        _bad(report, "E006", "group_swap must map kit groups, e.g. { leads: pads }", vline, f"{where}.group_swap")
        return None
    for a, b in group_swap.items():
        ga, gb = song_kit.groups.get(str(a)), kit.groups.get(str(b))
        if ga is None or gb is None:
            _bad(report, "E006", f"group_swap {a!r} -> {b!r}: unknown group (groups: {', '.join(kit.groups) or 'none'})", vline, f"{where}.group_swap")
            return None
        if len(ga) != len(gb):
            _bad(report, "E006", f"group_swap {a!r} -> {b!r}: groups must have the same number of instruments ({len(ga)} vs {len(gb)})", vline, f"{where}.group_swap")
            return None
        swaps += list(zip(ga, gb, strict=True))
    transpose, semitones = raw.get("transpose", 0), raw.get("semitones", 0)
    if not all(isinstance(v, int) and not isinstance(v, bool) and -24 <= v <= 24 for v in (transpose, semitones)):
        _bad(report, "E006", "transpose (scale degrees) and semitones must be whole numbers -24..24", vline, where)
        return None
    key = None
    if "key" in raw:
        key = parse_key(raw["key"])
        if key is None:
            _bad(report, "E006", "key must be a root and scale, e.g. A major", vline, f"{where}.key")
            return None
    return Variant(name, float(tempo) if tempo is not None else None, float(swing) if swing is not None else None, tuple(swaps), kit if kit_name else None,
                   kit_name, transpose, semitones, key, vline)  # fmt: skip


def _section_fields(name: str, raw_sections: dict[str, Any], report: Report, line: int | None, chain: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """A section's fields as a mapping, with `from` resolved (the section's own fields over its source's)."""
    raw = raw_sections[name]
    iline = line_of(raw_sections, name, line)
    where = f"sections.{name}"
    if isinstance(raw, list):
        return {"patterns": raw}
    if not isinstance(raw, dict):
        _bad(report, "E004", f"section {name!r} must be a list of patterns or a mapping of {', '.join(SECTION_FIELDS)}", iline, where)
        return None
    if unknown := [k for k in raw if k not in SECTION_FIELDS]:
        _bad(report, "E004", f"section {name!r}: unknown field(s) {', '.join(map(repr, unknown))}; allowed: {', '.join(SECTION_FIELDS)}", iline, where)
        return None
    if ("patterns" in raw) == ("from" in raw):
        _bad(report, "E004", f"section {name!r} needs exactly one of patterns: [...] or from: <section>", iline, where)
        return None
    if "patterns" in raw:
        return dict(raw)
    source = raw["from"]
    if not isinstance(source, str) or source not in raw_sections:
        _bad(report, "E004", f"section {name!r}: from {source!r} isn't a section (sections: {', '.join(raw_sections)})", iline, f"{where}.from")
        return None
    if source in (*chain, name):
        _bad(report, "E004", f"section {name!r}: sections derived with from form a cycle ({' -> '.join((*chain, name, source))})", iline, f"{where}.from")
        return None
    base = _section_fields(source, raw_sections, report, line, (*chain, name))
    if base is None:
        return None
    return {**base, **{k: v for k, v in raw.items() if k != "from"}}


def _section_change(name: str, fields: dict[str, Any], tracks: dict[str, Track], kit: Kit, project: Project, report: Report, line: int | None) -> SectionChange | None:
    where = f"sections.{name}"
    pitch_fields = {k: fields[k] for k in ("transpose", "semitones", "key", "instrument_swap", "group_swap") if k in fields}
    pitch = _variant(name, pitch_fields, kit, project, report, line, where)
    if pitch is None:
        return None
    mute = fields.get("mute", [])
    if not isinstance(mute, list) or not all(isinstance(m, str) and m in tracks for m in mute):
        _bad(report, "E004", f"section {name!r}: mute must list track names ({', '.join(tracks)})", line, f"{where}.mute")
        return None
    velocity = fields.get("velocity", {})
    if is_number(velocity):
        velocity = {t: velocity for t in tracks}
    if not (isinstance(velocity, dict) and all(k in tracks and is_number(v) and 0.05 <= v <= 2 for k, v in velocity.items())):
        _bad(report, "E004", f"section {name!r}: velocity must be a scale 0.05-2 or {{ track: scale }} (tracks: {', '.join(tracks)})", line, f"{where}.velocity")
        return None
    return SectionChange(pitch, tuple(mute), tuple((str(k), float(v)) for k, v in velocity.items() if v != 1))


def parse_sections(raw_sections: Any, raw_patterns: dict[str, Any], tracks: dict[str, Track], kit: Kit, project: Project, report: Report,
                   line: int | None) -> tuple[dict[str, list[str]], dict[str, SectionChange], dict[str, str]]:  # fmt: skip
    """Sections -> pattern lists, the changes of sections that make any (key, swaps, mutes, velocity), and which
    section each derived section comes `from`."""
    sections: dict[str, list[str]] = {}
    changes: dict[str, SectionChange] = {}
    sources: dict[str, str] = {}
    if not isinstance(raw_sections, dict) or not raw_sections:
        _bad(report, "E004", "sections must map section names to lists of patterns, e.g. main: [a, b, a, fill]", line, "sections")
        return sections, changes, sources
    for sname in raw_sections:
        where = f"sections.{sname}"
        iline = line_of(raw_sections, sname, line)
        if not isinstance(sname, str) or not TRACK_RE.match(sname):
            _bad(report, "E004", f"section name {sname!r} must be lowercase letters, digits or '_'", iline, where)
            continue
        fields = _section_fields(sname, raw_sections, report, line)
        if fields is None:
            continue
        items = fields["patterns"]
        if not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items):
            _bad(report, "E004", f"section {sname!r} must be a non-empty list of pattern names", iline, where)
            continue
        missing = [i for i in items if i not in raw_patterns]
        if missing:
            _bad(report, "E004", f"section {sname!r} uses unknown pattern(s) {', '.join(map(repr, missing))} (patterns: {', '.join(raw_patterns)})", iline, where)
            continue
        sections[sname] = list(items)
        if isinstance(raw_sections[sname], dict) and isinstance(raw_sections[sname].get("from"), str):
            sources[sname] = raw_sections[sname]["from"]
        if any(k in fields for k in SECTION_FIELDS[2:]) and tracks:
            change = _section_change(sname, fields, tracks, kit, project, report, iline)
            if change is not None:
                changes[sname] = change
    return sections, changes, sources


def _axis_names(axes: dict[str, dict[str, Variant]]) -> list[tuple[str, ...]]:
    """Option-name combinations of the variant axes (`calm+night`), none without axes."""
    return list(itertools.product(*(list(options) for options in axes.values()))) if axes else []


def parse_flow(raw: Any, sections: dict[str, list[str]], song_variants: set[str], report: Report, line: int | None) -> Flow | None:
    """E017: `flow:` - known sections, positive weights, every section reachable from a start and able to go on
    (or be the ending)."""
    def bad(message: str, where: str = "flow") -> None:
        _bad(report, "E017", message, line, where)

    if not isinstance(raw, dict) or any(k not in FLOW_FIELDS for k in raw):
        bad(f"flow must be a mapping of {', '.join(FLOW_FIELDS)}, e.g. {{ start: intro, next: {{ intro: [verse], verse: {{ chorus: 2, bridge: 1 }} }} }}")
        return None
    known = ", ".join(sections)
    start = raw.get("start")
    starts = [start] if isinstance(start, str) else start
    if not isinstance(starts, list) or not starts or not all(isinstance(s, str) for s in starts):
        bad("flow.start must be a section name or a list of them (where the game starts the song)", "flow.start")
        return None
    if missing := [s for s in starts if s not in sections]:
        bad(f"flow.start: unknown section(s) {', '.join(map(repr, missing))} (sections: {known})", "flow.start")
        return None
    raw_next = raw.get("next")
    if not isinstance(raw_next, dict) or not raw_next:
        bad("flow.next must map each section to the sections that may follow it: a list, or { section: weight }", "flow.next")
        return None
    graph: list[tuple[str, tuple[tuple[str, float], ...]]] = []
    for name, succ in raw_next.items():
        where = f"flow.next.{name}"
        if name not in sections:
            bad(f"flow.next: unknown section {name!r} (sections: {known})", where)
            return None
        weights = {s: 1 for s in succ} if isinstance(succ, list) else succ
        if not isinstance(weights, dict) or not weights or not all(isinstance(s, str) and is_number(w) and w > 0 for s, w in weights.items()):
            bad(f"flow.next.{name} must list sections ([verse, bridge]) or weight them ({{ verse: 2, bridge: 1 }}, weights > 0)", where)
            return None
        if missing := [s for s in weights if s not in sections]:
            bad(f"flow.next.{name}: unknown section(s) {', '.join(map(repr, missing))} (sections: {known})", where)
            return None
        if isinstance(succ, list) and len(set(succ)) != len(succ):
            bad(f"flow.next.{name} lists a section twice (use weights to make one likelier)", where)
            return None
        graph.append((str(name), tuple((str(s), float(w)) for s, w in weights.items())))
    end = raw.get("end")
    if end is not None and (not isinstance(end, str) or end not in sections):
        bad(f"flow.end must be a section (the ending, played when the game ends the song); sections: {known}", "flow.end")
        return None
    no_repeat = raw.get("no_repeat", True)
    if not isinstance(no_repeat, bool):
        bad("flow.no_repeat must be true or false", "flow.no_repeat")
        return None
    variants = raw.get("variants", [])
    if not isinstance(variants, list) or not all(isinstance(v, str) for v in variants):
        bad("flow.variants must list song variants that get flow clips too", "flow.variants")
        return None
    if missing := [v for v in variants if v not in song_variants]:
        bad(f"flow.variants: unknown variant(s) {', '.join(map(repr, missing))} (variants: {', '.join(sorted(song_variants)) or 'none'})", "flow.variants")
        return None
    flow = Flow(tuple(starts), tuple(graph), end, no_repeat, tuple(variants))
    reached = set(flow.start)
    frontier = list(flow.start)
    while frontier:
        for succ, _ in flow.successors(frontier.pop()):
            if succ not in reached:
                reached.add(succ)
                frontier.append(succ)
    if unreachable := [s for s in flow.sections if s not in reached and s != end]:
        bad(f"flow: section(s) {', '.join(map(repr, unreachable))} can't be reached from the start ({', '.join(flow.start)})", "flow.next")
        return None
    if dead := [s for s in flow.sections if not flow.successors(s) and s != end]:
        bad(f"flow: section(s) {', '.join(map(repr, dead))} have no next section (add them to flow.next, or make one the end)", "flow.next")
        return None
    if end is not None and flow.successors(end):
        bad(f"flow: the ending {end!r} can't have next sections (the song stops after it)", "flow.next")
        return None
    return flow


def load_song(path: Path, project: Project) -> tuple[Song | None, list[Finding]]:
    report = Report(path)
    try:
        data = load_source(path)
    except Exception as exc:  # noqa: BLE001
        return None, list(getattr(exc, "findings", [Finding("E001", str(exc), path)]))
    return parse_song(data, path, project, report)


def parse_stems(raw: Any, tracks: dict[str, Track], report: Report, line: int | None) -> Stems | None:
    """E016: every track in exactly one group (names or globs like `calm_*`); mixes list known groups."""
    if not isinstance(raw, dict) or any(k not in STEM_FIELDS for k in raw):
        _bad(report, "E016", f"stems must be a mapping of {', '.join(STEM_FIELDS)}, e.g. {{ groups: {{ base: [drums, bass], calm: [calm_*] }}, mixes: {{ calm: [base, calm] }} }}", line, "stems")
        return None
    groups: dict[str, tuple[str, ...]] = {}
    raw_groups = raw.get("groups", {})
    gline = line_of(raw, "groups", line)
    if not isinstance(raw_groups, dict):
        _bad(report, "E016", "stems.groups must map stem names to track lists, e.g. base: [drums, bass]", gline, "stems.groups")
        return None
    owner: dict[str, str] = {}
    for gname, items in raw_groups.items():
        where, iline = f"stems.groups.{gname}", line_of(raw_groups, gname, gline)
        if not isinstance(gname, str) or not TRACK_RE.match(gname):
            _bad(report, "E016", f"stem group name {gname!r} must be lowercase letters, digits or '_'", iline, where)
            continue
        if not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items):
            _bad(report, "E016", f"stem group {gname!r} must list track names or globs, e.g. [drums, calm_*]", iline, where)
            continue
        members: list[str] = []
        for item in items:
            found = [t for t in tracks if fnmatch.fnmatchcase(t, item)]
            if not found:
                _bad(report, "E016", f"stem group {gname!r}: {item!r} matches no track (tracks: {', '.join(tracks)})", iline, where)
            for t in found:
                if t in owner and owner[t] != gname:
                    _bad(report, "E016", f"track {t!r} is in stem groups {owner[t]!r} and {gname!r}: each track goes in one stem", iline, where)
                elif t not in members:
                    owner[t] = gname
                    members.append(t)
        groups[gname] = tuple(t for t in tracks if t in members)
    if groups and (left := [t for t in tracks if t not in owner]):
        _bad(report, "E016", f"track(s) {', '.join(left)} are in no stem group (the stems must add up to the song)", gline, "stems.groups")
    known = groups or {t: (t,) for t in tracks}
    mixes: dict[str, tuple[str, ...]] = {}
    raw_mixes = raw.get("mixes", {})
    xline = line_of(raw, "mixes", line)
    if not isinstance(raw_mixes, dict):
        _bad(report, "E016", "stems.mixes must map mix names to stem lists, e.g. calm: [base, calm]", xline, "stems.mixes")
    else:
        for mname, items in raw_mixes.items():
            where, iline = f"stems.mixes.{mname}", line_of(raw_mixes, mname, xline)
            if not isinstance(mname, str) or not TRACK_RE.match(mname):
                _bad(report, "E016", f"mix name {mname!r} must be lowercase letters, digits or '_'", iline, where)
            elif not isinstance(items, list) or not items or not all(isinstance(i, str) for i in items) or len(set(items)) != len(items):
                _bad(report, "E016", f"mix {mname!r} must list stems once each, e.g. [base, calm]", iline, where)
            elif missing := [i for i in items if i not in known]:
                _bad(report, "E016", f"mix {mname!r}: unknown stem(s) {', '.join(map(repr, missing))} (stems: {', '.join(known)})", iline, where)
            else:
                mixes[mname] = tuple(items)
    main_mix = raw.get("main_mix", True)
    if not isinstance(main_mix, bool):
        _bad(report, "E016", "stems.main_mix must be true or false (false: build only the stems)", line_of(raw, "main_mix", line), "stems.main_mix")
        main_mix = True
    return Stems(tuple(groups.items()), tuple(mixes.items()), main_mix)


def parse_song(data: dict[str, Any], path: Path | None, project: Project, report: Report | None = None) -> tuple[Song | None, list[Finding]]:
    report = report or Report(path)
    data, chain = resolve_extends(data, path, path.parent if path else None, SONG_SUFFIX, report)
    line = data.line if isinstance(data, LineMap) else None
    for k in data:
        if k not in SONG_FIELDS:
            _bad(report, "E001", f"unknown song field {k!r}; allowed: {', '.join(SONG_FIELDS)}", line_of(data, k, line), str(k))
    meta = parse_meta(data, path, "song", report, "E001")
    meta.sources = ([path] if path else []) + chain
    kit = resolve_kit(data, project, report, "E005")
    if kit is None and not report.failed:
        _bad(report, "E005", "the song needs a kit: kit: <name>, a default_kit in segan.toml, or (open mode) instruments:", line, "kit")
    tempo = data.get("tempo", 120)
    if not (is_number(tempo) and 20 <= tempo <= 400):
        _bad(report, "E001", "tempo must be 20-400 bpm", line_of(data, "tempo", line), "tempo")
        tempo = 120
    meter = data.get("meter", [4, 4])
    if not (isinstance(meter, list) and len(meter) == 2 and all(isinstance(m, int) and not isinstance(m, bool) for m in meter) and 1 <= meter[0] <= 16 and meter[1] in (2, 4, 8, 16)):
        _bad(report, "E001", "meter must be [beats per bar, beat unit], e.g. [4, 4] or [6, 8]", line_of(data, "meter", line), "meter")
        meter = [4, 4]
    steps_per_beat = _int_field(data, "steps_per_beat", 1, 12, 4, report, "E001", "steps_per_beat", line)
    swing = data.get("swing", 0.0)
    if not (is_number(swing) and 0 <= swing <= 0.5):
        _bad(report, "E001", "swing must be 0-0.5 (how far every off-step is delayed, in steps)", line_of(data, "swing", line), "swing")
        swing = 0.0
    key = parse_key(data.get("key", "C major"))
    if key is None:
        _bad(report, "E001", "key must be a root and a scale, e.g. A minor, C# dorian, F pentatonic_minor", line_of(data, "key", line), "key")
    category = data.get("category", "music")
    if not (isinstance(category, str) and re.fullmatch(r"[a-z][a-z0-9_]*", category)):
        _bad(report, "E001", "category must be a lowercase word (it picks the loudness target)", line_of(data, "category", line), "category")
        category = "music"
    normalize = data.get("normalize", True)
    if not isinstance(normalize, bool):
        _bad(report, "E001", "normalize must be true or false", line_of(data, "normalize", line), "normalize")
        normalize = True
    from segan.project import CHANNELS, SAMPLE_RATES

    sample_rate = data.get("sample_rate")
    if sample_rate is not None and (isinstance(sample_rate, bool) or sample_rate not in SAMPLE_RATES):
        _bad(report, "E001", f"sample_rate must be one of {', '.join(map(str, SAMPLE_RATES))} (Hz; default: [mix] sample_rate)",
             line_of(data, "sample_rate", line), "sample_rate")  # fmt: skip
        sample_rate = None
    channels = data.get("channels")
    if channels is not None and channels not in CHANNELS:
        _bad(report, "E001", "channels must be mono or stereo (default: [mix] music_channels)", line_of(data, "channels", line), "channels")
        channels = None
    seed = data.get("seed")
    if seed is not None and not (isinstance(seed, int) and not isinstance(seed, bool) and 0 <= seed < 2**63):
        _bad(report, "E001", "seed must be a whole number (the song's own seed: humanize uses it; change it for another take)", line_of(data, "seed", line), "seed")
        seed = None
    humanize = data.get("humanize", {})
    if is_number(humanize):
        humanize = {"timing": humanize}
    if not (isinstance(humanize, dict) and all(k in ("timing", "velocity") for k in humanize) and is_number(humanize.get("timing", 0))
            and 0 <= humanize.get("timing", 0) <= 40 and is_number(humanize.get("velocity", 0)) and 0 <= humanize.get("velocity", 0) <= 0.5):  # fmt: skip
        _bad(report, "E001", "humanize must be { timing: ms 0-40 (each note early/late by up to that), velocity: 0-0.5 (louder/softer by up to that "
             "fraction) }", line_of(data, "humanize", line), "humanize")  # fmt: skip
        humanize = {}
    fades = [0.0, 0.0]
    for i, name in enumerate(("fade_in", "fade_out")):
        if name in data:
            value = data[name]
            if not (is_number(value) and 0 <= value <= 120):
                _bad(report, "E008", f"{name} must be 0-120 seconds", line_of(data, name, line), name)
            elif data.get("loop") not in (None, False) or "flow" in data:
                _bad(report, "E008", f"{name} is for songs that play once (no loop or flow): a looping song's seam can't fade", line_of(data, name, line), name)
            else:
                fades[i] = float(value)
    if kit is None or report.failed:
        return None, report.findings

    tracks = parse_tracks(data.get("tracks"), kit, key, report, line_of(data, "tracks", line))
    raw_patterns = data.get("patterns")
    patterns: dict[str, Pattern] = {}
    if not isinstance(raw_patterns, dict) or not raw_patterns:
        _bad(report, "E001", "patterns must map pattern names to grids (or derived patterns)", line_of(data, "patterns", line), "patterns")
    elif tracks:
        ctx = _Context(kit, key, tracks, raw_patterns, report, line_of(data, "patterns", line))
        for name in raw_patterns:
            if not isinstance(name, str) or not TRACK_RE.match(name):
                _bad(report, "E001", f"pattern name {name!r} must be lowercase letters, digits or '_'", line_of(raw_patterns, name, line), f"patterns.{name}")
                continue
            pattern = _resolve_pattern(name, ctx)
            if pattern is not None:
                patterns[name] = pattern

    raw_sections = data.get("sections")
    sline = line_of(data, "sections", line)
    sections, changes, section_sources = parse_sections(raw_sections, raw_patterns if isinstance(raw_patterns, dict) else {}, tracks, kit, project, report, sline)
    arrangement = data.get("arrangement", list(sections) if isinstance(raw_sections, dict) and len(raw_sections) == 1 else None)
    aline = line_of(data, "arrangement", line)
    if not isinstance(arrangement, list) or not arrangement or not all(isinstance(a, str) for a in arrangement):
        _bad(report, "E004", "arrangement must list sections in play order, e.g. [intro, main]", aline, "arrangement")
        arrangement = []
    elif isinstance(raw_sections, dict) and (missing := [a for a in arrangement if a not in raw_sections]):
        _bad(report, "E004", f"arrangement uses unknown section(s) {', '.join(map(repr, missing))} (sections: {', '.join(raw_sections)})", aline, "arrangement")
    loop_raw = data.get("loop")
    lline = line_of(data, "loop", line)
    loop: str | None = None
    if loop_raw is True and arrangement:
        loop = arrangement[0]
    elif isinstance(loop_raw, str):
        if loop_raw not in arrangement:
            _bad(report, "E008", f"loop {loop_raw!r} must be a section in the arrangement ({', '.join(arrangement)}); the loop runs from its start to the end", lline, "loop")
        else:
            loop = loop_raw
    elif loop_raw not in (None, False):
        _bad(report, "E008", "loop must be a section name (loop from there to the end), true (the whole song) or false", lline, "loop")
    markers: dict[str, tuple[str, int]] = {}
    raw_markers = data.get("markers", {})
    mline = line_of(data, "markers", line)
    if not isinstance(raw_markers, dict):
        _bad(report, "E004", "markers must map names to [section, bar], e.g. drop: [main, 2]", mline, "markers")
    else:
        for mname, value in raw_markers.items():
            if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int) and value[1] >= 1):
                _bad(report, "E004", f"marker {mname!r} must be [section, bar] (bars count from 1)", line_of(raw_markers, mname, mline), f"markers.{mname}")
            elif value[0] not in arrangement:
                _bad(report, "E004", f"marker {mname!r}: section {value[0]!r} isn't in the arrangement", line_of(raw_markers, mname, mline), f"markers.{mname}")
            else:
                markers[str(mname)] = (value[0], value[1])

    variants: dict[str, Variant] = {}
    raw_variants = data.get("variants", {})
    vline = line_of(data, "variants", line)
    if not isinstance(raw_variants, dict):
        _bad(report, "E006", "variants must map names to changes (tempo, instrument_swap, kit, transpose...)", vline, "variants")
    else:
        for vname, vraw in raw_variants.items():
            v = _variant(str(vname), vraw, kit, project, report, line_of(raw_variants, vname, vline), f"variants.{vname}")
            if v is not None:
                variants[str(vname)] = v
    axes: dict[str, dict[str, Variant]] = {}
    raw_axes = data.get("variant_axes", {})
    xline = line_of(data, "variant_axes", line)
    if not isinstance(raw_axes, dict):
        _bad(report, "E006", "variant_axes must map axis names to { option: changes }", xline, "variant_axes")
    else:
        for axis, options in raw_axes.items():
            if not isinstance(options, dict) or len(options) < 2:
                _bad(report, "E006", f"variant axis {axis!r} needs at least two options", line_of(raw_axes, axis, xline), f"variant_axes.{axis}")
                continue
            parsed = {str(o): _variant(str(o), raw, kit, project, report, line_of(options, o, xline), f"variant_axes.{axis}.{o}") for o, raw in options.items()}
            if all(v is not None for v in parsed.values()):
                axes[str(axis)] = {k: v for k, v in parsed.items() if v is not None}
        clash = [o for opts in axes.values() for o in opts if o in variants]
        if clash:
            _bad(report, "E006", f"variant name(s) {', '.join(clash)} are used by variants and variant_axes", xline, "variant_axes")
    stems = parse_stems(data["stems"], tracks, report, line_of(data, "stems", line)) if "stems" in data and tracks else None
    flow = None
    if "flow" in data:
        all_variants = set(variants) | {"+".join(c) for c in _axis_names(axes)}
        flow = parse_flow(data["flow"], sections, all_variants, report, line_of(data, "flow", line))
    if report.failed or key is None:
        return None, report.findings
    song = Song(meta, kit, float(tempo), (meter[0], meter[1]), steps_per_beat, float(swing), key, tracks, patterns, sections, arrangement, loop,
                markers, variants, axes, normalize, category, stems, changes, flow, section_sources, sample_rate, channels, seed,
                (float(humanize.get("timing", 0.0)), float(humanize.get("velocity", 0.0))), (fades[0], fades[1]))  # fmt: skip
    for name in flow.sections if flow is not None else []:
        steps = sum(patterns[p].length for p in sections[name])
        if steps % song.steps_per_bar:
            _bad(report, "E017", f"flow section {name!r} is {steps} steps, not whole bars of {song.steps_per_bar}: the game chains and syncs flow "
                 "sections on bar lines", line_of(data, "flow", line), f"sections.{name}")  # fmt: skip
    for mname, (section, bar) in markers.items():
        steps = sum(patterns[p].length for p in sections[section])
        if (bar - 1) * song.steps_per_bar >= steps:
            _bad(report, "E004", f"marker {mname!r}: section {section!r} has only {max(1, steps // song.steps_per_bar)} bars", line_of(raw_markers, mname, mline), f"markers.{mname}")
    check_notes(song, report, raw_patterns if isinstance(raw_patterns, dict) else {})
    if report.failed:
        return None, report.findings
    return song, report.findings


def _move(midi: int, key: Key, change: Variant) -> tuple[int | None, Key]:
    """One change's key mapping, scale-degree transposition and semitones; returns the note and the key it's in."""
    out: int | None = midi
    if change.key is not None:
        out = key.map_to(change.key, midi) if key.contains(midi) else midi
        key = change.key
    if change.transpose and out is not None:
        out = key.degree_shift(out, change.transpose) if key.contains(out) else out + change.transpose
    if change.semitones and out is not None:
        out += change.semitones
        key = transpose_key(key, change.semitones)
    return out, key


def note_midi(song: Song, note: Note, variant: Variant | None = None, section: SectionChange | None = None) -> int | None:
    """The pitch a roll note plays: a variant's key change/transpose/semitones, then the section's on top. None
    for drum lanes or when a change moves it off the scale or out of MIDI range."""
    track = song.tracks[note.track]
    if track.drums:
        return None
    midi: int | None = int(track.rows[note.row])
    key = song.key
    for change in (variant, section.pitch if section is not None else None):
        if change is not None and midi is not None:
            midi, key = _move(midi, key, change)
    return midi if midi is not None and 0 <= midi <= 127 else None


def note_release(song: Song, note: Note) -> float | None:
    """A note's release override (seconds): its pattern's for its track, else its track's; None = the instrument's."""
    return note.release if note.release is not None else song.tracks[note.track].release


def section_key(section: SectionChange | None, key: str) -> str:
    """The kit key a note plays after its section's swaps (a variant's swaps apply after these)."""
    return dict(section.pitch.swaps).get(key, key) if section is not None else key


def instrument_for(song: Song, key: str, variant: Variant | None = None) -> Instrument | None:
    """The instrument a key plays (after a variant's swaps and kit)."""
    if variant is not None:
        key = dict(variant.swaps).get(key, key)
        if variant.kit is not None:
            return variant.kit.instruments.get(key)
    return song.kit.instruments.get(key)


def check_notes(song: Song, report: Report, raw_patterns: dict[str, Any]) -> None:
    """E007 notes outside an instrument's range (also in every variant and under every section change) and E014
    more simultaneous notes on a track than the instrument's voices."""
    variants: list[Variant | None] = [None, *song.all_variants().values()]
    for pattern in song.patterns.values():
        pline = line_of(raw_patterns, pattern.name, pattern.line)
        reported: set[tuple[str, str, str]] = set()
        # the section changes this pattern plays under (none when a plain section, or no section, plays it)
        contexts: dict[str, SectionChange | None] = {s: song.section_changes.get(s) for s, items in song.sections.items() if pattern.name in items}
        changed = {s: c for s, c in contexts.items() if c is not None}
        under: list[tuple[str, SectionChange | None]] = [("", None)] if len(changed) < len(contexts) or not contexts else []
        under += list(changed.items())
        for (section, change), variant in itertools.product(under, variants):
            for note in pattern.notes:
                if change is not None and note.track in change.mute:
                    continue
                inst = instrument_for(song, section_key(change, note.key), variant)
                vname = (f" in variant {variant.name!r}" if variant is not None else "") + (f" in section {section!r}" if section else "")
                if inst is None:
                    if (pattern.name, note.key, vname) not in reported:
                        reported.add((pattern.name, note.key, vname))
                        report.error("E006", f"pattern {pattern.name!r}: key {note.key!r} has no instrument{vname} (check its kit / instrument_swap)", pline, f"patterns.{pattern.name}")
                    continue
                midi = note_midi(song, note, variant, change)
                if midi is None or inst.range is None:
                    if midi is None and not song.tracks[note.track].drums and (pattern.name, "pitch", vname) not in reported:
                        reported.add((pattern.name, "pitch", vname))
                        report.error("E007", f"pattern {pattern.name!r}: a {note.track} note{vname} leaves the playable pitch range", pline, f"patterns.{pattern.name}")
                    continue
                if not inst.range[0] <= midi <= inst.range[1] and (pattern.name, note.key + str(midi), vname) not in reported:
                    reported.add((pattern.name, note.key + str(midi), vname))
                    low, high = (song.key.name(m) for m in inst.range)
                    report.error("E007", f"pattern {pattern.name!r}: {note.track} note {song.key.name(midi)} at step {note.step + 1}{vname} is outside "
                                 f"{inst.name or note.key}'s range {low}-{high}", pline, f"patterns.{pattern.name}.{note.track}")  # fmt: skip
        for track in song.tracks.values():
            by_key: dict[str, list[Note]] = {}
            for note in pattern.notes:
                if note.track == track.name:
                    by_key.setdefault(note.key, []).append(note)
            for key, notes in by_key.items():
                insts = [song.kit.instruments.get(section_key(c, key)) for _, c in under]
                inst = min((i for i in insts if i is not None), key=lambda i: i.voices, default=None)
                if inst is None or inst.is_drum:
                    continue
                for step in range(pattern.length):
                    sounding = [n for n in notes if n.step <= step < n.step + n.length]
                    if len(sounding) > inst.voices:
                        report.error("E014", f"pattern {pattern.name!r}: {len(sounding)} {key!r} notes sound at once on {track.name} at step {step + 1}, "
                                     f"but {inst.name or key} has voices: {inst.voices} (raise voices in the kit or use another instrument)",
                                     pline, f"patterns.{pattern.name}.{track.name}")  # fmt: skip
                        break
