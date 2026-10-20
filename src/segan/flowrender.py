"""Flow clips: a song's sections as pieces the game chains at run time (`flow:` in the song).

Every section has its own timeline (positions rounded from its own start), so its length `L` in frames is the
same wherever it's played and chained clips never drift. `H` = whole bars covering the longest ring-out
(releases + room) of any flow section, capped at the section's length. Per section S:

- `S` (rest): frames [H, L) of S rendered on its own;
- `S.head`: frames [0, H) of S on its own (the song starts with S);
- `S.from.P`: frames [0, H) of S rendered right after P (P's ring-out baked in), one per predecessor;
- `S.tail`: S's own ring-out after L (the song stops after S).

Head and rest clips carry `PAD` frames of what follows them (the rest, or S's own ring-out) after their length
(`info["frames"]`): Godot stops a WAV playback a few frames before its data ends, so the director plays each clip
for its length only and the padding is never heard.

A walk P -> S -> ... plays `S.from.P` + `S` + ...: exactly a linear render of that path, up to the -70 dB tail
trim and the limiter at clip edges. Every clip gets the linear song's normalisation gain, then the limiter.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

import numpy as np

from segan.analysis import frames_of
from segan.dsp import Signal
from segan.kitshow import context_for
from segan.mix import apply_crush, apply_room, apply_tone, gain_and_limit, room_tail, trim_tail
from segan.project import Project
from segan.render import Output
from segan.sequence import build_timeline, song_events
from segan.songrender import song_mix
from segan.song import Song, Variant
from segan.synth import Context
from segan.voices import NoteEvent, assign_cuts, event_end, render_events
from segan.wavio import to_pcm16

WALK_SECONDS = 180.0
PAD = 32


@dataclass(frozen=True)
class FlowSection:
    name: str
    events: list[NoteEvent]  # frames from the section's start
    length: int  # frames
    head: int  # frames of the head clip
    steps: int
    head_steps: int
    ring: int  # frames its notes and room ring past its end


def flow_id(variant: Variant | None, clip: str = "") -> str:
    """Output id of a flow clip: `flow:verse.head`, `flow.danger:verse` (variant)."""
    return f"flow{'.' + variant.name if variant is not None else ''}:{clip}"


def flow_sections(song: Song, project: Project, variant: Variant | None) -> tuple[dict[str, FlowSection], int]:
    """Each flow section on its own timeline, and the head length in bars."""
    assert song.flow is not None
    mix = song_mix(song, project)
    ctx = context_for(mix)
    rate = ctx.rate
    pieces: dict[str, tuple[list[NoteEvent], int, int, int]] = {}
    longest = 0.0
    for name in song.flow.sections:
        timeline = build_timeline(song, variant, [name])
        events = song_events(song, timeline, rate, variant)
        length = timeline.frame(timeline.total, rate)
        ring = max([length, *(event_end(e, ctx) for e in assign_cuts(events, ctx))]) - length
        pieces[name] = (events, length, timeline.total, ring)
        longest = max(longest, ring / rate + room_tail(mix) + 0.05)
    timeline = build_timeline(song, variant, [song.flow.sections[0]])
    bar_seconds = timeline.steps_per_bar * timeline.step_seconds
    bars = max(1, math.ceil(longest / bar_seconds))
    out: dict[str, FlowSection] = {}
    for name, (events, length, steps, ring) in pieces.items():
        head_steps = min(bars * song.steps_per_bar, steps)
        head = build_timeline(song, variant, [name]).frame(head_steps, rate)
        out[name] = FlowSection(name, events, length, head, steps, head_steps, ring)
    return out, bars


def _bus(events: list[NoteEvent], frames: int, project: Project, song: Song, gain_db: float) -> Signal:
    """Events -> mix bus -> the song's gain and the limiter, `frames` long."""
    mix = song_mix(song, project)
    ctx: Context = context_for(mix)
    channels = 2 if mix.music_channels == "stereo" else 1
    tracks = render_events(events, ctx, channels, frames)
    dry = np.sum(list(tracks.values()), axis=0) if tracks else np.zeros((frames, channels))
    wet = apply_crush(apply_tone(apply_room(dry, mix), mix)[:frames], mix)
    return gain_and_limit(wet, gain_db, mix.limiter, ctx.rate)


def render_flow(song: Song, project: Project, variant: Variant | None, gain_db: float) -> list[Output]:
    """Every flow clip of the song (or of one variant), at the linear song's normalisation gain."""
    assert song.flow is not None
    mix = song_mix(song, project)
    rate = context_for(mix).rate
    sections, bars = flow_sections(song, project, variant)
    room = round(room_tail(mix) * rate)
    prefix = song.name if variant is None else f"{song.name}.{variant.name}"
    outputs: list[Output] = []

    def emit(clip: str, audio: Signal, frames: int, info: dict[str, object]) -> Output | None:
        if not frames:
            return None  # a section no longer than its head has no rest; a dry section may have no tail
        out = Output(flow_id(variant, clip), f"{prefix}/{clip}", to_pcm16(frames_of(audio)), rate, None, [], {},
                     {"variant": variant.name if variant else None, "flow_clip": clip, "frames": frames, **info})  # fmt: skip
        outputs.append(out)
        return out

    for name, s in sections.items():
        cold = _bus(s.events, s.length + max(s.ring + room, PAD) + 1, project, song, gain_db)
        info = {"section": name, "length": s.length, "head": s.head, "steps": s.steps, "head_steps": s.head_steps, "head_bars": bars}
        head = emit(f"{name}.head", cold[: s.head + PAD], s.head, {**info, "part": "head"})
        emit(name, cold[s.head : s.length + PAD], s.length - s.head, {**info, "part": "rest"})
        tail = trim_tail(cold, s.length, rate, mix.tail_trim_db)[s.length :]
        emit(f"{name}.tail", tail, len(tail), {**info, "part": "tail"})
        for pred in song.flow.predecessors(name):
            p = sections[pred]
            later = [replace(e, start=e.start + p.length) for e in s.events if e.start < s.head + PAD]
            joined = _bus([*p.events, *later], p.length + s.head + PAD, project, song, gain_db)[p.length :]
            pcm = to_pcm16(frames_of(joined))
            if head is not None and np.array_equal(pcm, head.pcm):
                continue  # nothing of P rings into S: the cold head does
            emit(f"{name}.from.{pred}", joined, s.head, {**info, "part": "from", "from": pred, "cut": p.ring + room > s.head})
    return outputs


def flow_clip(outputs: list[Output], variant: Variant | None, clip: str) -> Output | None:
    wanted = flow_id(variant, clip)
    return next((o for o in outputs if o.id == wanted), None)


def walk(song: Song, seed: int, seconds: float = WALK_SECONDS) -> list[str]:
    """A random walk through the flow, as the director plays it: weighted successors, never the same section
    twice in a row when `no_repeat` (unless it's the only way on), until `seconds` of sections, then the ending."""
    assert song.flow is not None
    flow = song.flow
    rng = random.Random(seed)
    timeline = {name: build_timeline(song, None, [name]) for name in flow.sections}
    path = [rng.choice(flow.start)]
    played = timeline[path[0]].seconds(timeline[path[0]].total)
    while played < seconds:
        options = [(s, w) for s, w in flow.successors(path[-1]) if not (flow.no_repeat and s == path[-1])] or list(flow.successors(path[-1]))
        if not options:
            break
        pick = rng.random() * sum(w for _, w in options)
        for name, weight in options:
            pick -= weight
            if pick < 0:
                break
        path.append(name)
        played += timeline[name].seconds(timeline[name].total)
    if flow.end is not None and path[-1] != flow.end:
        path.append(flow.end)
    return path


def path_reference(song: Song, project: Project, variant: Variant | None, path: list[str], frames: int, gain_db: float) -> Signal:
    """A linear render of a walk's path (all its sections' notes on one timeline): what its clips must equal."""
    sections, _ = flow_sections(song, project, variant)
    events: list[NoteEvent] = []
    at = 0
    for name in path:
        events += [replace(e, start=e.start + at) for e in sections[name].events]
        at += sections[name].length
    return _bus(events, frames, project, song, gain_db)


def walk_audio(outputs: list[Output], variant: Variant | None, path: list[str]) -> tuple[Signal, list[tuple[str, int]]]:
    """The clips of a walk back to back (plus the last section's tail), and where each section starts."""
    pieces: list[Signal] = []
    starts: list[tuple[str, int]] = []
    at = 0
    for i, name in enumerate(path):
        head = (flow_clip(outputs, variant, f"{name}.from.{path[i - 1]}") if i else None) or flow_clip(outputs, variant, f"{name}.head")
        rest = flow_clip(outputs, variant, name)
        starts.append((name, at))
        for piece in (head, rest):
            if piece is not None:
                frames = int(piece.info["frames"])
                pieces.append(piece.audio[:frames])
                at += frames
    tail = flow_clip(outputs, variant, f"{path[-1]}.tail")
    if tail is not None:
        pieces.append(tail.audio)
    return np.concatenate(pieces), starts
