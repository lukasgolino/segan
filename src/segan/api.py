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

from dataclasses import dataclass, field
from typing import Any

from segan.dsp import seed_of, uniform
from segan.notes import Key, note_name, parse_key, parse_note
from segan.yamlwrite import dump_mapping, flow

API_VERSION = 1

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

    def note(self, track: Track, step: int, pitch: int | str, length: int = 1, key: str = "p") -> Pattern:
        if track.percussion:
            raise ValueError(f"{track.name} is a drum track: use hit()")
        midi = note(pitch)
        if midi not in track.rows:
            raise ValueError(f"{note_name(midi)} isn't a row of {track.name} ({track.labels[-1]}-{track.labels[0]} in its key)")
        self._add(track, track.rows.index(midi), step, length, key)  # type: ignore[arg-type]
        return self

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


def song_yaml(name: str, *, tracks: list[Track], patterns: dict[str, Pattern | dict[str, Any]], sections: dict[str, list[str]],
              arrangement: list[str], key: str | Key, tempo: float = 120, loop: str | bool | None = None, group: int = 4, **fields: Any) -> str:  # fmt: skip
    """A complete song file. `patterns` values are Pattern builders or raw mappings (derived patterns); fields
    that are None are left out."""
    fields = {k: v for k, v in fields.items() if v is not None}
    data: dict[str, Any] = {"name": name, **{k: v for k, v in fields.items() if k in ("description", "kit")}}
    data.update({"tempo": tempo, "key": key_of(key).describe()})
    data.update({k: v for k, v in fields.items() if k not in ("description", "kit")})
    data["tracks"] = {t.name: t.spec for t in tracks}
    out: dict[str, Any] = {}
    for pname, pattern in patterns.items():
        if isinstance(pattern, Pattern):
            out[pname] = {"length": pattern.length, **{t.name: pattern.lane(t, group) for t in tracks if t.name in pattern.notes}}
        else:
            out[pname] = pattern
    data["patterns"] = out
    data["sections"] = sections
    data["arrangement"] = arrangement
    if loop is not None:
        data["loop"] = loop
    text = dump_mapping(data, ["name", "description", "kit", "tempo", "meter", "steps_per_beat", "swing", "key", "status", "style_version", "tags"])
    return text.replace("tracks:\n", "tracks:\n", 1)


def sfx_yaml(name: str, *, layers: list[dict[str, Any]], **fields: Any) -> str:
    """A complete SFX file from layer mappings (the same fields as in the notation)."""
    data = {"name": name, **fields, "layers": layers}
    return dump_mapping(data, ["name", "description", "category", "kit", "preset", "duration", "loop", "status", "style_version", "tags", "layers"])


__all__ = [
    "API_VERSION", "Pattern", "Track", "arpeggiate", "chord", "euclid", "flow", "humanize", "key_of", "note", "progression", "scale",
    "sfx_yaml", "song_yaml",
]  # fmt: skip
