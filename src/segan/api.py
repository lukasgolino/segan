"""`segan.api`: a stable Python API for generator scripts (many similar sounds, procedural rhythms, chord
progressions). Use it instead of re-implementing SEGAN's notation: scripts write ordinary song/SFX files,
which are then linted and previewed like hand-written ones.

```python
from segan import api
key = "A minor"
lead = api.Track.roll("lead", key, "A4", "A5")
drums = api.Track.drums("drums", ["k", "s", "h"])
p = api.Pattern(16)
for step, midi, length in api.arpeggiate(api.chord(1, key, octave=4), 16, rate=2):
    p.note(lead, step, midi, length, "p")
for step, hit in enumerate(api.euclid(5, 16)):
    if hit:
        p.hit(drums, step, "k")
text = api.song_yaml("theme", key=key, tempo=120, kit="nes", tracks=[lead, drums], patterns={"a": p},
                     sections={"main": ["a"]}, arrangement=["main"], loop="main")
```

Versioned like the notation: `API_VERSION` changes when a function's behaviour changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from segan.dsp import seed_of, uniform
from segan.notes import Key, note_name, parse_key, parse_note
from segan.yamlwrite import dump_mapping, flow

API_VERSION = 2  # 2: note velocities, Rng, invert, voicing

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7}


def key_of(key: str | Key) -> Key:
    if isinstance(key, Key):
        return key
    parsed = parse_key(key)
    if parsed is None:
        raise ValueError(f"not a key: {key!r} (e.g. 'A minor', 'C# dorian')")
    return parsed


def note(name: str | int) -> int:
    """MIDI number of a note name ("A4" = 69); ints pass through."""
    if isinstance(name, int):
        return name
    midi = parse_note(name)
    if midi is None:
        raise ValueError(f"not a note: {name!r} (e.g. A4, C#5, Bb2)")
    return midi


def scale(key: str | Key, low: str | int = "C4", high: str | int = "C5") -> list[int]:
    """The key's notes from `low` to `high`, ascending."""
    return sorted(key_of(key).notes_between(note(low), note(high)))


def chord(degree: int, key: str | Key, octave: int = 4, size: int = 3) -> list[int]:
    """The diatonic chord on a scale degree (1-7): stacked thirds of the key (3 = triad, 4 = seventh chord)."""
    k = key_of(key)
    if len(k.intervals) != 7:
        raise ValueError(f"chords need a seven-note scale; {k.describe()} has {len(k.intervals)}")
    root = (octave + 1) * 12 + k.root
    notes = []
    for i in range(size):
        step = (degree - 1) + 2 * i
        notes.append(root + 12 * (step // 7) + k.intervals[step % 7])
    return notes


def progression(numerals: str, key: str | Key, octave: int = 4, size: int = 3) -> list[list[int]]:
    """Chords for roman numerals ("i VI III VII"); the case is ignored (the key decides each chord's quality)."""
    out = []
    for numeral in numerals.split():
        degree = ROMAN.get(numeral.lower().rstrip("°+7"))
        if degree is None:
            raise ValueError(f"not a roman numeral: {numeral!r}")
        out.append(chord(degree, key, octave, size))
    return out


def euclid(hits: int, steps: int, rotate: int = 0) -> list[bool]:
    """Euclidean rhythm: `hits` spread as evenly as possible over `steps` (Bjorklund), rotated by `rotate`."""
    if not 0 <= hits <= steps:
        raise ValueError("hits must be between 0 and steps")
    pattern = [(i * hits) % steps < hits for i in range(steps)]
    rotate %= max(steps, 1)
    return pattern[-rotate:] + pattern[:-rotate] if rotate else pattern


def arpeggiate(notes: list[int], steps: int, rate: int = 1, order: str = "up", start: int = 0) -> list[tuple[int, int, int]]:
    """(step, midi, length) for an arpeggio over `steps`: a note every `rate` steps, `order` up, down or updown."""
    if not notes:
        return []
    sequence = sorted(notes)
    if order == "down":
        sequence = sequence[::-1]
    elif order == "updown":
        sequence = sequence + sequence[-2:0:-1]
    elif order != "up":
        raise ValueError("order must be up, down or updown")
    return [(step, sequence[i % len(sequence)], rate) for i, step in enumerate(range(start, steps, rate))]


def humanize(row: str, seed: int | str, amount: float = 0.3) -> str:
    """Vary a drum row deterministically: some hits become ghosts (o) or accents (X), by `amount` (0-1)."""
    out = []
    for i, char in enumerate(row):
        if char in "xX":
            u = uniform(seed_of("humanize", seed), i)
            char = "o" if u < amount / 2 else "X" if u > 1 - amount / 4 else char
        out.append(char)
    return "".join(out)


@dataclass
class Track:
    """A song track definition: a roll (scale rows in a range) or a drum lane (kit keys)."""

    name: str
    rows: list[int] | list[str]
    labels: list[str]
    percussion: bool = False
    spec: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def roll(cls, name: str, key: str | Key, low: str, high: str, chromatic: bool = False, **extra: Any) -> Track:
        k = key_of(key)
        midis = list(range(note(high), note(low) - 1, -1)) if chromatic else k.notes_between(note(low), note(high))
        spec: dict[str, Any] = {"roll": [low, high], **({"chromatic": True} if chromatic else {}), **extra}
        return cls(name, midis, [k.name(m) for m in midis], False, spec)

    @classmethod
    def drums(cls, name: str, keys: list[str], **extra: Any) -> Track:
        return cls(name, list(keys), list(keys), True, {"drums": list(keys), **extra})


@dataclass
class Pattern:
    """A pattern being built: notes per track, written out as labelled lanes."""

    length: int
    notes: dict[str, list[tuple[int, int, int, str]]] = field(default_factory=dict)  # track -> (row, step, length, char)
    velocity: dict[str, dict[int, str]] = field(default_factory=dict)  # track -> step -> velocity mark (written as a `velocity:` row)

    def note(self, track: Track, step: int, pitch: int | str, length: int = 1, key: str = "p", velocity: float | None = None) -> Pattern:
        """A roll note; `velocity` (0.2-1.8, 1 = plain; 1.5 accent, 0.35 ghost) is written as the nearest mark."""
        if track.percussion:
            raise ValueError(f"{track.name} is a drum track: use hit()")
        midi = note(pitch)
        if midi not in track.rows:
            raise ValueError(f"{note_name(midi)} isn't a row of {track.name} ({track.labels[-1]}-{track.labels[0]} in its key)")
        self._add(track, track.rows.index(midi), step, length, key)  # type: ignore[arg-type]
        if velocity is not None and abs(velocity - 1.0) > 0.05:
            self.velocity.setdefault(track.name, {})[step] = velocity_mark(velocity)
        return self

    def velocity_row(self, track: Track, group: int = 4) -> str | None:
        marks = self.velocity.get(track.name)
        if not marks:
            return None
        text = "".join(marks.get(i, ".") for i in range(self.length))
        return "|".join(text[i : i + group] for i in range(0, self.length, group)) if group else text

    def hit(self, track: Track, step: int, drum: str, mark: str = "x") -> Pattern:
        if not track.percussion or drum not in track.rows or mark not in "xXo":
            raise ValueError(f"hit() needs a drum track, one of its keys {track.rows} and a mark x, X or o")
        self._add(track, track.rows.index(drum), step, 1, mark)  # type: ignore[arg-type]
        return self

    def row(self, track: Track, drum: str, cells: str) -> Pattern:
        """A whole drum row at once, e.g. row(drums, "h", "x.x.x.x.x.x.x.x.")."""
        cells = cells.replace("|", "").replace(" ", "")
        if len(cells) != self.length:
            raise ValueError(f"row has {len(cells)} steps; the pattern has {self.length}")
        for step, char in enumerate(cells):
            if char != ".":
                self.hit(track, step, drum, char)
        return self

    def _add(self, track: Track, row: int, step: int, length: int, char: str) -> None:
        if not 0 <= step < self.length or length < 1 or step + length > self.length:
            raise ValueError(f"note at step {step} (length {length}) doesn't fit a {self.length}-step pattern")
        self.notes.setdefault(track.name, []).append((row, step, length, char))

    def lane(self, track: Track, group: int = 4) -> str:
        """The lane text for one track: every row, highest first, with its label."""
        grid = [["."] * self.length for _ in track.rows]
        for row, step, length, char in self.notes.get(track.name, []):
            cells = grid[row]
            for i in range(step, step + length):
                if cells[i] != ".":
                    raise ValueError(f"{track.name}: notes overlap at step {i} on row {track.labels[row]}")
            cells[step] = char
            for i in range(step + 1, step + length):
                cells[i] = "-"
        lines = []
        for cells, label in zip(grid, track.labels, strict=True):
            text = "".join(cells)
            if group:
                text = "|".join(text[i : i + group] for i in range(0, self.length, group))
            lines.append(f"{text}  {label}")
        return "\n".join(lines) + "\n"


VELOCITY_MARKS = {"X": 1.5, "o": 0.35, "x": 1.0, **{str(d): round(0.2 * d, 2) for d in range(1, 10)}}


def velocity_mark(velocity: float) -> str:
    """The velocity-row mark closest to a velocity (X accent 1.5, o ghost 0.35, digits 1-9 = 0.2-1.8)."""
    return min(VELOCITY_MARKS, key=lambda m: (abs(VELOCITY_MARKS[m] - velocity), m.isdigit()))


class Rng:
    """Seeded choices for generators: `rng = api.Rng(seed, "verse")`; `rng.random()`, `rng.choice(items)`, `rng.range(lo, hi)`.
    The same on every machine and Python version (no `random` module), so a script with a seed rewrites the same song."""

    def __new__(cls, *parts: object) -> Any:
        from segan.suggest import Rng as _Rng

        return _Rng("api", *parts)


def invert(notes: list[int], inversion: int) -> list[int]:
    """Chord notes in an inversion: 1 = lowest note up an octave, 2 = the two lowest, -1 = highest down an octave."""
    out = sorted(notes)
    for _ in range(max(0, inversion)):
        out = out[1:] + [out[0] + 12]
    for _ in range(max(0, -inversion)):
        out = [out[-1] - 12] + out[:-1]
    return sorted(out)


def voicing(notes: list[int], inversion: int = 0, spread: str = "close", octave: int = 0, bass: bool = False) -> list[int]:
    """A chord voiced: `inversion`, `spread` close | open (drop the 2nd voice from the top an octave: wider, warmer) |
    wide (lowest down and highest up an octave), moved by `octave`, with the root doubled below when `bass`."""
    out = invert(notes, inversion)
    if spread == "open" and len(out) >= 3:
        out = sorted([out[-2] - 12, *out[:-2], out[-1]])
    elif spread == "wide":
        out = sorted([out[0] - 12, *out[1:-1], out[-1] + 12]) if len(out) >= 3 else out
    elif spread != "close":
        raise ValueError("spread must be close, open or wide")
    out = [m + 12 * octave for m in out]
    if bass:
        out = sorted([sorted(notes)[0] + 12 * octave - 12, *out])
    return out


def song_yaml(name: str, *, tracks: list[Track], patterns: Mapping[str, Pattern | dict[str, Any]], sections: dict[str, list[str]],
              arrangement: list[str], key: str | Key, tempo: float = 120, loop: str | bool | None = None, group: int = 4,
              comments: dict[str, str] | None = None, **fields: Any) -> str:  # fmt: skip
    """A complete song file. `patterns` values are Pattern builders or raw mappings (derived patterns); fields
    that are None are left out. `comments` maps a dotted path (`patterns.chorus`, `sections.verse`, `tracks.lead`)
    to text written as `#` lines above it."""
    fields = {k: v for k, v in fields.items() if v is not None}
    data: dict[str, Any] = {"name": name, **{k: v for k, v in fields.items() if k in ("description", "kit")}}
    data.update({"tempo": tempo, "key": key_of(key).describe()})
    data.update({k: v for k, v in fields.items() if k not in ("description", "kit")})
    data["tracks"] = {t.name: t.spec for t in tracks}
    out: dict[str, Any] = {}
    for pname, pattern in patterns.items():
        if isinstance(pattern, Pattern):
            out[pname] = {"length": pattern.length, **{t.name: pattern.lane(t, group) for t in tracks if t.name in pattern.notes}}
            rows = {t.name: row for t in tracks if (row := pattern.velocity_row(t, group)) is not None}
            if rows:
                out[pname]["velocity"] = rows
        else:
            out[pname] = pattern
    data["patterns"] = out
    data["sections"] = sections
    data["arrangement"] = arrangement
    if loop is not None:
        data["loop"] = loop
    text = dump_mapping(data, ["name", "description", "kit", "tempo", "meter", "steps_per_beat", "swing", "key", "status", "style_version", "tags"], comments)
    return text.replace("tracks:\n", "tracks:\n", 1)


def sfx_yaml(name: str, *, layers: list[dict[str, Any]], comments: dict[str, str] | None = None, **fields: Any) -> str:
    """A complete SFX file from layer mappings (the same fields as in the notation); `comments` as in `song_yaml`."""
    data = {"name": name, **fields, "layers": layers}
    return dump_mapping(data, ["name", "description", "category", "kit", "preset", "duration", "loop", "status", "style_version", "tags", "layers"], comments)


def _signature(pattern: Pattern) -> tuple[Any, ...]:
    return (pattern.length, tuple(sorted((t, tuple(sorted(n))) for t, n in pattern.notes.items() if n)),
            tuple(sorted((t, tuple(sorted(v.items()))) for t, v in pattern.velocity.items() if v)))  # fmt: skip


def dedupe(patterns: dict[str, Pattern], sections: dict[str, list[str]]) -> tuple[dict[str, Pattern], dict[str, list[str]]]:
    """Identical patterns (same length and notes on every track) collapse into the first one's name, and the
    sections are rewritten to use it: generators can emit a pattern per bar and still write a tidy file."""
    first: dict[Any, str] = {}
    rename: dict[str, str] = {}
    kept: dict[str, Pattern] = {}
    for name, pattern in patterns.items():
        signature = _signature(pattern)
        if signature in first:
            rename[name] = first[signature]
        else:
            first[signature] = name
            kept[name] = pattern
    return kept, {s: [rename.get(p, p) for p in names] for s, names in sections.items()}


def derive(base_name: str, base: Pattern, pattern: Pattern, tracks: list[Track]) -> dict[str, Any] | None:
    """`pattern` written as a derived pattern of `base` (`{from: base_name, transpose: {...}, mute: [...], shift: N}`)
    when it is `base` with some tracks muted, scale-row transpositions per roll track and one time shift; else None.
    For `song_yaml(patterns={..., "b": api.derive("a", a, b, tracks) or b})`."""
    if pattern.length != base.length or pattern.velocity or base.velocity:
        return None  # velocity rows are per pattern: write it out
    by_name = {t.name: t for t in tracks}
    for shift in sorted(range(-base.length + 1, base.length), key=abs):
        spec: dict[str, Any] = {"from": base_name}
        transpose: dict[str, int] = {}
        mute: list[str] = []
        ok = True
        for track, notes in base.notes.items():
            moved = sorted((r, s + shift, n, c) for r, s, n, c in notes)
            if any(s < 0 or s + n > base.length for _, s, n, _ in moved):
                ok = False
                break
            target = sorted(pattern.notes.get(track, []))
            if not target:
                if notes:
                    mute.append(track)
                continue
            options = [0] if by_name.get(track) is None or by_name[track].percussion or by_name[track].spec.get("chromatic") else range(-24, 25)
            found = next((k for k in sorted(options, key=abs) if sorted((r - k, s, n, c) for r, s, n, c in moved) == target), None)
            if found is None:
                ok = False
                break
            if found:
                transpose[track] = found
        if not ok or any(t not in base.notes and n for t, n in pattern.notes.items()):
            continue
        if transpose:
            spec["transpose"] = transpose
        if shift:
            spec["shift"] = shift
        if mute:
            spec["mute"] = mute
        return spec
    return None


__all__ = [
    "API_VERSION", "Pattern", "Rng", "Track", "arpeggiate", "chord", "dedupe", "derive", "euclid", "flow", "humanize", "invert", "key_of", "note",
    "progression", "scale", "sfx_yaml", "song_yaml", "velocity_mark", "voicing",
]  # fmt: skip
