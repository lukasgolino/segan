"""Note events -> track buffers: render each note once (identical notes are cached within a render),
cut mono voices when the next note starts (with a short fade when declick is on), pan, and sum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from segan.dsp import Signal, db_to_gain
from segan.patch import Instrument
from segan.synth import DECLICK_RELEASE, Context, note_length, render_note


@dataclass(frozen=True)
class NoteEvent:
    track: str
    key: str
    inst: Instrument
    start: int  # first frame at the output rate
    gate: float  # seconds held
    midi: float
    velocity: float = 1.0
    seed: int = 0
    cut: int | None = None  # frames after start where a mono voice is cut by the next note
    pan: float = 0.0  # track pan (added to the instrument's)
    gain_db: float = 0.0  # track gain


def pan_gains(pan: float) -> tuple[float, float]:
    """Constant-power pan: -1 left, 0 centre (-3 dB each side), 1 right."""
    angle = (max(-1.0, min(1.0, pan)) + 1.0) * math.pi / 4
    return round(math.cos(angle), 12), round(math.sin(angle), 12)


def event_end(event: NoteEvent, ctx: Context) -> int:
    """Last frame (exclusive) a note can sound."""
    length = round(note_length(event.inst, event.gate, ctx, event.midi) * ctx.rate)
    if event.cut is not None:
        length = min(length, event.cut + round(DECLICK_RELEASE * ctx.rate))
    return event.start + length


def assign_cuts(events: list[NoteEvent], ctx: Context) -> list[NoteEvent]:
    """Mono instruments (voices 1, or more voices than allowed): each new note on the same track and
    instrument cuts the oldest sounding one, like a chip channel."""
    from dataclasses import replace

    out: list[NoteEvent] = []
    sounding: dict[tuple[str, str], list[int]] = {}
    for event in sorted(events, key=lambda e: (e.start, e.track, e.key, e.midi)):
        group = sounding.setdefault((event.track, event.key), [])
        group[:] = [i for i in group if event_end(out[i], ctx) > event.start]
        while len(group) >= event.inst.voices:
            oldest = group.pop(0)
            out[oldest] = replace(out[oldest], cut=event.start - out[oldest].start)
        group.append(len(out))
        out.append(event)
    return out


def render_events(events: list[NoteEvent], ctx: Context, channels: int, frames: int | None = None) -> dict[str, Signal]:
    """Sum every event into one buffer per track, shape (frames, channels)."""
    cache: dict[tuple[object, ...], Signal] = {}
    events = assign_cuts(events, ctx)
    length = frames if frames is not None else max((event_end(e, ctx) for e in events), default=0)
    tracks: dict[str, Signal] = {}
    for event in events:
        if event.track not in tracks:
            tracks[event.track] = np.zeros((length, channels))
        buffer = tracks[event.track]
        key = (repr(event.inst), event.midi, event.gate, event.velocity, event.seed, event.cut)
        voice = cache.get(key)
        if voice is None:
            voice = render_note(event.inst, ctx, event.midi, event.gate, event.velocity, event.seed)
            if event.cut is not None and event.cut < len(voice):
                fade = round(DECLICK_RELEASE * ctx.rate) if ctx.declick else 0
                end = min(len(voice), event.cut + fade)
                voice = voice[:end].copy()
                if fade:
                    span = end - event.cut
                    voice[event.cut :] *= np.linspace(1.0, 0.0, span, endpoint=False) ** 2
            cache[key] = voice
        start = event.start
        if start >= length:
            continue
        piece = voice[: length - start] * db_to_gain(event.gain_db)
        if channels == 1:
            buffer[start : start + len(piece), 0] += piece
        else:
            left, right = pan_gains(event.pan + event.inst.pan)
            buffer[start : start + len(piece), 0] += piece * left
            buffer[start : start + len(piece), 1] += piece * right
    return tracks
