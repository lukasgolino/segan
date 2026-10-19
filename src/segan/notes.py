"""Note names, keys and scales: the "colour space" of a song.

Roll rows are the notes of the song's scale inside a track's range, highest first, so an off-key note
can't be written (the way off-palette colours can't be in PAGAN).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCALES: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "pentatonic_major": (0, 2, 4, 7, 9),
    "pentatonic_minor": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "whole_tone": (0, 2, 4, 6, 8, 10),
    "chromatic": tuple(range(12)),
}
SCALE_ALIASES = {"ionian": "major", "aeolian": "minor", "natural_minor": "minor"}

_LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
NOTE_RE = re.compile(r"^([A-Ga-g])([#b]{0,2})(-?\d+)$")
LOWEST, HIGHEST = 0, 127


def parse_note(text: object) -> int | None:
    """MIDI number for a note name (`A4` = 69, `C#5`, `Bb2`, `C-1` = 0), or None if it isn't one."""
    if not isinstance(text, str):
        return None
    match = NOTE_RE.match(text.strip())
    if match is None:
        return None
    letter, accidentals, octave = match.groups()
    pitch = _LETTERS[letter.upper()] + accidentals.count("#") - accidentals.count("b") + (int(octave) + 1) * 12
    return pitch if LOWEST <= pitch <= HIGHEST else None


def note_name(midi: int, flats: bool = False) -> str:
    names = _FLAT_NAMES if flats else _SHARP_NAMES
    return f"{names[midi % 12]}{midi // 12 - 1}"


def pitch_class(text: str) -> int | None:
    match = re.match(r"^([A-Ga-g])([#b]{0,2})$", text.strip())
    if match is None:
        return None
    letter, accidentals = match.groups()
    return (_LETTERS[letter.upper()] + accidentals.count("#") - accidentals.count("b")) % 12


@dataclass(frozen=True)
class Key:
    root: int  # pitch class 0-11
    scale: str
    root_name: str

    @property
    def intervals(self) -> tuple[int, ...]:
        return SCALES[self.scale]

    @property
    def flats(self) -> bool:
        """Spell notes with flats (F major, D minor, Bb...) or sharps."""
        if "b" in self.root_name[1:]:
            return True
        if "#" in self.root_name:
            return False
        relative = {"minor": 9, "harmonic_minor": 9, "melodic_minor": 9, "pentatonic_minor": 9, "blues": 9,
                    "dorian": 2, "phrygian": 4, "mixolydian": 7, "lydian": 5, "locrian": 11}  # fmt: skip
        major_root = (self.root - relative.get(self.scale, 0)) % 12
        return major_root in (5, 10, 3, 8, 1, 6)  # F Bb Eb Ab Db Gb

    def contains(self, midi: int) -> bool:
        return (midi - self.root) % 12 in self.intervals

    def notes_between(self, low: int, high: int) -> list[int]:
        """Scale notes from high down to low (roll rows, highest first)."""
        return [m for m in range(high, low - 1, -1) if self.contains(m)]

    def name(self, midi: int) -> str:
        return note_name(midi, self.flats)

    def degree_shift(self, midi: int, degrees: int) -> int | None:
        """The scale note `degrees` steps above (or below) `midi`, which must be in the scale."""
        if not self.contains(midi):
            return None
        step = 1 if degrees > 0 else -1
        current, remaining = midi, abs(degrees)
        while remaining:
            current += step
            if current < LOWEST or current > HIGHEST:
                return None
            if self.contains(current):
                remaining -= 1
        return current

    def map_to(self, other: Key, midi: int) -> int | None:
        """The note at the same scale degree (and octave) in another key (A minor -> A major)."""
        if not self.contains(midi):
            return None
        own, target = self.intervals, other.intervals
        if len(target) != len(own):
            return None
        within = (midi - self.root) % 12
        root_below = midi - within
        shifted = root_below + (other.root - self.root) + target[own.index(within)]
        return shifted if LOWEST <= shifted <= HIGHEST else None

    def describe(self) -> str:
        return f"{self.root_name} {self.scale}"


def parse_key(text: object) -> Key | None:
    """`A minor`, `C# dorian`, `Eb major`, `F pentatonic_minor`; None if it isn't a key."""
    if not isinstance(text, str):
        return None
    parts = text.strip().split()
    if len(parts) != 2:
        return None
    root = pitch_class(parts[0])
    scale = parts[1].lower().replace("-", "_")
    scale = SCALE_ALIASES.get(scale, scale)
    if root is None or scale not in SCALES:
        return None
    return Key(root, scale, parts[0][0].upper() + parts[0][1:])


def transpose_key(key: Key, semitones: int) -> Key:
    root = (key.root + semitones) % 12
    flats = key.flats
    return Key(root, key.scale, (_FLAT_NAMES if flats else _SHARP_NAMES)[root])
