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
from dataclasses import replace

import numpy as np

from segan.analysis import frames_of, integrated_lufs, true_peak_db
from segan.dsp import Signal
from segan.kitshow import context_for
from segan.mix import apply_crush, apply_room, apply_tone, finish, room_tail, trim_tail
from segan.project import MixConfig, Project
from segan.render import Output, Render, level_dict
from segan.sequence import Timeline, build_timeline, song_events
from segan.song import Song, Variant
from segan.voices import assign_cuts, event_end, render_events
from segan.wavio import to_pcm16


def song_mix(song: Song, project: Project) -> MixConfig:
    """The shared mix for this song, at its own sample rate and channels when it sets them."""
    mix = project.config.mix_for(song.category)
    return replace(mix, sample_rate=song.sample_rate or mix.sample_rate, music_channels=song.channels or mix.music_channels)


def used_instruments(song: Song) -> tuple[tuple[str, object], ...]:
    """The kit instruments a song can play: keys in its notes, plus the targets of variant and section swaps. The
    render cache is keyed on these, so editing an instrument the song never plays doesn't re-render it."""
    keys = set(song.used_keys())
    for variant in song.all_variants().values():
        keys.update(b for _, b in variant.swaps)
    for change in song.section_changes.values():
        keys.update(b for _, b in change.pitch.swaps)
    return tuple((k, song.kit.instruments[k]) for k in sorted(keys) if k in song.kit.instruments)


def song_cache_parts(song: Song, project: Project) -> tuple[object, ...]:
    patterns = sorted((name, p.length, tuple(p.notes)) for name, p in song.patterns.items())
    return ("song", song.name, used_instruments(song), song.tempo, song.meter, song.steps_per_beat, song.swing, song.key, sorted(song.tracks.items()),
            patterns, sorted(song.sections.items()), song.arrangement, song.loop, sorted(song.markers.items()),
            sorted(song.all_variants().items()), song.normalize, song.category, song_mix(song, project),
            project.config.target(song.category), project.config.lint.max_limiting_db, wants_stems(song, project), song.stems,
            sorted(song.section_changes.items()), song.flow, song.seed, song.humanize)  # fmt: skip


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
    mix = song_mix(song, project)
    ctx = context_for(mix)
    rate = ctx.rate
    channels = 2 if mix.music_channels == "stereo" else 1
    timeline = build_timeline(song, variant)
    end_frame = timeline.frame(timeline.total, rate)
    events = song_events(song, timeline, rate, variant, repeat_loop=timeline.loop is not None)
    # how long the song's last notes really ring past its end (voice cuts included), plus the room
    ring = max([end_frame, *(event_end(e, ctx) for e in assign_cuts(events, ctx) if e.start < end_frame)]) - end_frame
    tail = ring / rate + room_tail(mix) + 0.05
    offset_steps = loop_offset_steps(song, timeline, tail)
    file_end = timeline.frame(timeline.total + offset_steps, rate) if timeline.loop is not None else None
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
            # what the game adds to every stem's volume while it plays this mix to bring it to the target, kept
            # under the limiter's ceiling (the stems are already limited as the loudest mix)
            trim = round(max(0.0, min(target - lufs, mix.limiter - true_peak_db(audio))), 1) if target is not None else 0.0
            mix_info = {**info, "mix": mname, "stems": list(members), "tracks": [t for g in members for t in groups[g]], "normalised_over": loudest, "trim_db": trim}
            stem_outputs.append(Output(f"mix:{mname}", f"{song.name}/mix.{mname}", to_pcm16(audio), rate, loop, [], {"target": target, "lufs": lufs}, mix_info))
            main.info.setdefault("mixes", {})[mname] = round(lufs, 2)
            main.info.setdefault("mix_trims", {})[mname] = trim
    return main, stem_outputs


def render_song(song: Song, project: Project) -> Render:
    main, stems = render_variant(song, project, None, wants_stems(song, project))
    outputs = [main]
    for variant in song.all_variants().values():
        outputs.append(render_variant(song, project, variant)[0])
    flow: list[Output] = []
    if song.flow is not None:
        from segan.flowrender import render_flow

        flow += render_flow(song, project, None, float(main.level.get("gain_db") or 0.0))
        for name in song.flow.variants:
            variant = song.all_variants()[name]
            level = next(o for o in outputs if o.id == f"variant:{name}").level
            flow += render_flow(song, project, variant, float(level.get("gain_db") or 0.0))
    return Render(song.name, "song", outputs + stems + flow)
