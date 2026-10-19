"""Song rendering: events -> one buffer per track -> each track through the room and tone (linear, so the
tracks still add up to the mix) -> crush -> loudness (integrated) -> PCM, plus sample-aligned stems.

Looping songs: the file is the whole song plus the first bar(s) of the loop played again, and the loop
points sit that far (`loop_offset`, whole bars, at least the longest release + room tail) after the loop
section's boundaries. So the intro rings naturally into the first pass, and at the loop point the player
hears the loop's own end ringing into its start: seamless, with sample-exact loop points (`smpl` chunk,
manifest `loop`).
"""

from __future__ import annotations

import math

import numpy as np

from segan.analysis import frames_of, integrated_lufs
from segan.dsp import Signal
from segan.kitshow import context_for
from segan.mix import apply_crush, apply_room, apply_tone, finish, room_tail, trim_tail
from segan.project import Project
from segan.render import Output, Render, level_dict
from segan.sequence import Timeline, build_timeline, song_events
from segan.song import Song, Variant
from segan.voices import event_end, render_events
from segan.wavio import to_pcm16


def song_cache_parts(song: Song, project: Project) -> tuple[object, ...]:
    patterns = sorted((name, p.length, tuple(p.notes)) for name, p in song.patterns.items())
    return ("song", song.name, song.kit, song.tempo, song.meter, song.steps_per_beat, song.swing, song.key, sorted(song.tracks.items()),
            patterns, sorted(song.sections.items()), song.arrangement, song.loop, sorted(song.markers.items()),
            sorted(song.all_variants().items()), song.normalize, song.category, project.config.mix_for(song.category),
            project.config.target(song.category), project.config.lint.max_limiting_db, wants_stems(song, project), song.stems)  # fmt: skip


def wants_stems(song: Song, project: Project) -> bool:
    """Stems for every song when `export` has "stems", and for any song with a `stems:` block."""
    return "stems" in project.config.export or song.stems is not None


def loop_offset_steps(song: Song, timeline: Timeline, tail: float) -> int:
    """Whole bars covering `tail` seconds (at most the loop's length)."""
    if timeline.loop is None:
        return 0
    bar = timeline.steps_per_bar * timeline.step_seconds
    bars = max(1, math.ceil(tail / bar))
    return min(bars * timeline.steps_per_bar, timeline.loop[1] - timeline.loop[0])


def render_variant(song: Song, project: Project, variant: Variant | None, stems: bool = False) -> tuple[Output, list[Output]]:
    mix = project.config.mix_for(song.category)
    ctx = context_for(mix)
    rate = ctx.rate
    channels = 2 if mix.music_channels == "stereo" else 1
    timeline = build_timeline(song, variant)
    kit = variant.kit if variant is not None and variant.kit is not None else song.kit
    tail = max([0.0, *(i.tail() for i in kit.instruments.values())]) + room_tail(mix) + 0.05
    offset_steps = loop_offset_steps(song, timeline, tail)
    end_frame = timeline.frame(timeline.total, rate)
    file_end = timeline.frame(timeline.total + offset_steps, rate) if timeline.loop is not None else None
    events = song_events(song, timeline, rate, variant, repeat_loop=timeline.loop is not None)
    if file_end is not None:
        events = [e for e in events if e.start < file_end]
    total = max([end_frame, *(event_end(e, ctx) for e in events)]) + round(room_tail(mix) * rate) + 1
    total = max(total, file_end or 0)  # a sparse loop can end sounding before the file does
    tracks = render_events(events, ctx, channels, total)
    wet: dict[str, Signal] = {}
    if stems:  # the room and tone are linear: per-stem buses still add up to the mix
        for name, members in song.stem_groups().items():
            buffer = np.sum([tracks.get(t, np.zeros((total, channels))) for t in members], axis=0)
            wet[name] = apply_tone(apply_room(buffer, mix), mix)[:total]
        summed = np.sum(list(wet.values()), axis=0)
    else:
        dry = np.sum(list(tracks.values()), axis=0) if tracks else np.zeros((total, channels))
        summed = apply_tone(apply_room(dry, mix), mix)[:total]

    def cut(signal: Signal) -> Signal:
        return signal[:file_end] if file_end is not None else trim_tail(signal, end_frame, rate, mix.tail_trim_db)

    mixed = cut(apply_crush(summed, mix))
    target = project.config.target(song.category) if song.normalize else None
    final, level, curve = finish(mixed, rate, target, "integrated", mix.limiter, project.config.lint.max_limiting_db)
    loop: tuple[int, int] | None = None
    if timeline.loop is not None and file_end is not None:
        shift = file_end - end_frame
        loop = (timeline.frame(timeline.loop[0], rate) + shift, file_end)
    cues = sorted(((name, timeline.frame(step, rate)) for name, step in timeline.markers.items()), key=lambda c: (c[1], c[0]))
    stem_name = song.name if variant is None else f"{song.name}.{variant.name}"
    info = {"variant": variant.name if variant else None, "end_frame": end_frame, "loop_offset": (file_end - end_frame) if file_end else 0}
    main = Output("" if variant is None else f"variant:{variant.name}", stem_name, to_pcm16(frames_of(final)), rate, loop, cues, level_dict(level), info)
    stem_outputs: list[Output] = []
    if variant is None and stems:
        crushed: dict[str, Signal] = {}
        for name, buffer in wet.items():
            stem = cut(apply_crush(buffer, mix))[: len(curve)]
            crushed[name] = np.pad(stem, ((0, len(curve) - len(stem)), (0, 0))) if len(stem) < len(curve) else stem
        mixes = dict(song.stems.mixes) if song.stems is not None else {}
        loudest = ""
        if mixes:  # normalise over the loudest stem combination the game plays, not the full mix it never does
            sums = {m: np.sum([crushed[g] for g in groups], axis=0) for m, groups in mixes.items()}
            loudest = max(sums, key=lambda m: (integrated_lufs(sums[m], rate), m))
            _, _, curve = finish(sums[loudest], rate, target, "integrated", mix.limiter, project.config.lint.max_limiting_db)
        groups = song.stem_groups()
        for name, stem in crushed.items():
            stem_outputs.append(Output(f"stem:{name}", f"{song.name}/{name}", to_pcm16(stem * curve[:, None]), rate, loop, [], {},
                                       {**info, "track": name, "tracks": list(groups[name])}))  # fmt: skip
        for mname, members in mixes.items():
            audio = np.sum([crushed[g] for g in members], axis=0) * curve[:, None]
            lufs = integrated_lufs(audio, rate)
            mix_info = {**info, "mix": mname, "stems": list(members), "tracks": [t for g in members for t in groups[g]], "normalised_over": loudest}
            stem_outputs.append(Output(f"mix:{mname}", f"{song.name}/mix.{mname}", to_pcm16(audio), rate, loop, [], {"target": target, "lufs": lufs}, mix_info))
            main.info.setdefault("mixes", {})[mname] = round(lufs, 2)
    return main, stem_outputs


def render_song(song: Song, project: Project) -> Render:
    main, stems = render_variant(song, project, None, wants_stems(song, project))
    outputs = [main]
    for variant in song.all_variants().values():
        outputs.append(render_variant(song, project, variant)[0])
    return Render(song.name, "song", outputs + stems)
