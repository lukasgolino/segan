"""Song -> timeline and note events (the sequencer).

Steps are placed on a fixed grid (60 / tempo / steps_per_beat seconds), with `swing` delaying every
off-step. Sample positions are rounded once per step, so loop points and section boundaries are
sample-exact and identical in every output (main, variants, stems).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from segan.dsp import seed_of
from segan.song import Note, Song, Variant, instrument_for, note_midi
from segan.voices import NoteEvent


@dataclass(frozen=True)
class PatternSpan:
    name: str
    start: int  # step
    length: int


@dataclass(frozen=True)
class SectionSpan:
    name: str
    start: int  # step
    end: int
    patterns: tuple[PatternSpan, ...]


@dataclass
class Timeline:
    step_seconds: float
    swing: float
    steps_per_bar: int
    steps_per_beat: int
    total: int  # steps
    sections: list[SectionSpan]
    loop: tuple[int, int] | None  # steps
    markers: dict[str, int] = field(default_factory=dict)  # steps

    def seconds(self, step: int) -> float:
        offset = self.swing * self.step_seconds if step % 2 == 1 else 0.0
        return step * self.step_seconds + offset

    def frame(self, step: int, rate: int) -> int:
        return round(self.seconds(step) * rate)

    def bar_of(self, step: int) -> float:
        return step / self.steps_per_bar + 1


def build_timeline(song: Song, variant: Variant | None = None) -> Timeline:
    tempo = variant.tempo if variant is not None and variant.tempo is not None else song.tempo
    swing = variant.swing if variant is not None and variant.swing is not None else song.swing
    step_seconds = 60.0 / tempo / song.steps_per_beat
    sections: list[SectionSpan] = []
    step = 0
    loop: tuple[int, int] | None = None
    for name in song.arrangement:
        start = step
        spans = []
        for pattern in song.sections[name]:
            length = song.patterns[pattern].length
            spans.append(PatternSpan(pattern, step, length))
            step += length
        sections.append(SectionSpan(name, start, step, tuple(spans)))
        if song.loop == name and loop is None:
            loop = (start, -1)
    if loop is not None:
        loop = (loop[0], step)
    markers: dict[str, int] = {}
    for marker, (section, bar) in song.markers.items():
        span = next(s for s in sections if s.name == section)
        markers[marker] = span.start + (bar - 1) * song.steps_per_bar
    return Timeline(step_seconds, swing, song.steps_per_bar, song.steps_per_beat, step, sections, loop, markers)


@dataclass(frozen=True)
class Placed:
    """A note at its place in the song (for events and the piano roll)."""

    note: Note
    step: int  # absolute step
    midi: float
    key: str


def placed_notes(song: Song, timeline: Timeline, variant: Variant | None = None) -> list[Placed]:
    out: list[Placed] = []
    swaps = dict(variant.swaps) if variant is not None else {}
    for section in timeline.sections:
        for span in section.patterns:
            for note in song.patterns[span.name].notes:
                track = song.tracks[note.track]
                key = swaps.get(note.key, note.key)
                if track.drums:
                    inst = instrument_for(song, note.key, variant)
                    midi = float(inst.note) if inst is not None else 60.0
                else:
                    pitch = note_midi(song, note, variant)
                    if pitch is None:
                        continue
                    midi = float(pitch)
                out.append(Placed(note, span.start + note.step, midi, key))
    return out


def song_events(song: Song, timeline: Timeline, rate: int, variant: Variant | None = None, repeat_loop: bool = False) -> list[NoteEvent]:
    """Every note as an event; with `repeat_loop`, the loop is played a second time right after the end
    (its frames shifted by exactly the loop's length), which is what the looping output is cut from."""
    events: list[NoteEvent] = []
    kit = variant.kit if variant is not None and variant.kit is not None else song.kit
    placed = placed_notes(song, timeline, variant)
    for p in placed:
        inst = kit.instruments.get(p.key)
        if inst is None:
            continue
        track = song.tracks[p.note.track]
        start = timeline.frame(p.step, rate)
        if track.drums:
            gate = timeline.step_seconds * 0.5
        else:
            gate = timeline.seconds(p.step + p.note.length) - timeline.seconds(p.step)
        events.append(NoteEvent(track.name, p.key, inst, start, gate, p.midi, p.note.velocity, seed_of(song.name, track.name, p.key), None, track.pan, track.gain))
    if repeat_loop and timeline.loop is not None:
        first, end = timeline.loop
        shift = timeline.frame(end, rate) - timeline.frame(first, rate)
        start_frame = timeline.frame(first, rate)
        events += [
            NoteEvent(e.track, e.key, e.inst, e.start + shift, e.gate, e.midi, e.velocity, e.seed, None, e.pan, e.gain_db)
            for e in events
            if e.start >= start_frame
        ]
    return events
