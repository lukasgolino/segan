"""Song listen sheets (arrangement strip, piano roll per track from the source, beat grid) and the per-note
pitch check (detected pitch of each note on its stem vs. the written note)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from segan.analysis import yin
from segan.dsp import midi_to_hz_scalar
from segan.listen import TEXT, TRACK_COLOURS, Block, RollNote, RollTrack, SheetSpec
from segan.preview import level_stats
from segan.project import Project
from segan.render import Output
from segan.sequence import Timeline, build_timeline, placed_notes
from segan.song import Song, Variant


def variant_of(song: Song, output: Output) -> Variant | None:
    name = output.info.get("variant")
    return song.all_variants().get(name) if name else None


def _colours(song: Song) -> dict[str, tuple[int, int, int]]:
    return {key: TRACK_COLOURS[i % len(TRACK_COLOURS)] for i, key in enumerate(song.kit.instruments)}


def roll_tracks(song: Song, timeline: Timeline, variant: Variant | None, only: list[str] | None = None) -> list[RollTrack]:
    colours = _colours(song)
    placed = placed_notes(song, timeline, variant)
    out: list[RollTrack] = []
    for track in song.tracks.values():
        if only is not None and track.name not in only:
            continue
        mine = [p for p in placed if p.note.track == track.name]
        if track.drums:
            rows = [str(k) for k in track.rows]
            notes = [RollNote(p.note.row, timeline.seconds(p.step), timeline.seconds(p.step + 1), p.key, p.note.velocity) for p in mine]
        else:
            pitches = sorted({int(r) for r in track.rows} | {int(p.midi) for p in mine}, reverse=True)
            rows = [song.key.name(m) if song.key.contains(m) else song.key.name(m) + "*" for m in pitches]
            notes = [RollNote(pitches.index(int(p.midi)), timeline.seconds(p.step), timeline.seconds(p.step + p.note.length), p.key) for p in mine]
        out.append(RollTrack(track.name, rows, notes, track.drums, colours))
    return out


def song_sheet(song: Song, output: Output, analysis: dict[str, Any], project: Project, threshold_click: float) -> SheetSpec:
    variant = variant_of(song, output)
    timeline = build_timeline(song, variant)
    sections = [Block(s.name, timeline.seconds(s.start), timeline.seconds(s.end), f"bars {timeline.bar_of(s.start):g}-{timeline.bar_of(s.end) - 1:g}") for s in timeline.sections]
    patterns = [Block(p.name, timeline.seconds(p.start), timeline.seconds(p.start + p.length)) for s in timeline.sections for p in s.patterns]
    beats = [timeline.seconds(step) for step in range(0, timeline.total + 1, timeline.steps_per_beat)]
    file_steps = math.ceil(output.seconds / timeline.step_seconds)
    bars = [(timeline.seconds(step), step // timeline.steps_per_bar + 1) for step in range(0, file_steps + 1, timeline.steps_per_bar)]
    tempo = variant.tempo if variant is not None and variant.tempo else song.tempo
    key = variant.key.describe() if variant is not None and variant.key else song.key.describe()
    stats = [("tempo", f"{tempo:g} bpm", TEXT), ("key", key, TEXT), ("meter", f"{song.meter[0]}/{song.meter[1]}", TEXT),
             ("bars", f"{timeline.total / timeline.steps_per_bar:g}", TEXT), *level_stats(analysis, threshold_click)]  # fmt: skip
    title = f"song {output.stem}" + (f"  - {song.meta.description}" if song.meta.description else "")
    notes = []
    if timeline.loop is not None:
        offset_bars = round((output.info.get("loop_offset", 0) / output.rate) / (timeline.steps_per_bar * timeline.step_seconds), 3)  # whole bars, up to frame rounding
        notes.append(f"loop = section {song.loop!r} (bar {timeline.bar_of(timeline.loop[0]):g}) to the end, played from {offset_bars:g} bar(s) later "
                     f"(bars {timeline.bar_of(timeline.loop[0]) + offset_bars:g}-{timeline.bar_of(timeline.total) + offset_bars:g}) so its own tail rings "
                     "into its start; yellow lines = the loop points in the file")
    if variant is not None:
        notes.append(f"variant {variant.name}: piano roll shows the notes as played (* = off the song's key)")
    checks = analysis.get("pitch_check", {})
    off = [f"{t}: {len(c['off'])} off" for t, c in checks.items() if c.get("off")]
    if checks:
        notes.append(f"pitch check (one-note-at-a-time tracks: {', '.join(checks)}): " + (", ".join(off) if off else "every checked note within 50 cents"))
    loop = (output.loop[0] / output.rate, output.loop[1] / output.rate) if output.loop else None
    markers = [(name, timeline.seconds(step)) for name, step in timeline.markers.items()]
    return SheetSpec(title[:150], stats, output.audio, output.rate, beats=beats, bars=bars, blocks=sections, sub_blocks=patterns,
                     tracks=roll_tracks(song, timeline, variant, output.info.get("tracks")), loop=loop, markers=markers, loudness_curve=True, notes=notes)  # fmt: skip


LOW_NOTE_HZ = 131.0  # below C3, pitch trackers lock on the 3rd/5th harmonic of plucked and bowed notes
DETUNE_MIN_NOTES = 3  # notes of one instrument needed to call a shared offset the sample's own tuning


def _cents_off(detected: float, expected: float) -> float:
    """Detected vs. written pitch in cents, octaves folded; for low notes also read as the 3rd or 5th harmonic
    (whichever is closest), since that's what the tracker often follows there."""
    def fold(c: float) -> float:
        return (c + 600) % 1200 - 600

    candidates = [detected] + ([detected / 3, detected / 5] if expected < LOW_NOTE_HZ else [])
    return min((fold(1200 * math.log2(c / expected)) for c in candidates), key=abs)


def pitch_check(song: Song, project: Project) -> dict[str, Any]:
    """`measure_pitch`, cached next to the song's render (it renders every track dry: minutes for a long song, #69)."""
    import json

    from segan.render import RENDERER_VERSION, cache_key
    from segan.songrender import song_cache_parts

    path = project.cache_dir / "pitch" / f"{cache_key('pitch', RENDERER_VERSION, *song_cache_parts(song, project))}.json"
    if path.is_file():
        try:
            cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return cached
        except (OSError, ValueError):
            pass
    result = measure_pitch(song, project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return result


def measure_pitch(song: Song, project: Project) -> dict[str, Any]:
    """Each roll note of a monophonic track: median detected pitch on the track's dry render vs. the written
    pitch (cents, octaves folded; low notes also as the 3rd/5th harmonic). Instruments with arpeggios and one-shot
    samples (they ring over the next notes) are skipped; pitch envelopes, sample attacks and the previous note's
    release are waited out. An instrument whose notes share one offset (a sample recorded a bit sharp or flat) gets
    `detune_cents`, and its notes count as off only when they're more than 50 cents from that."""
    from segan.synth import is_one_shot
    from segan.kitshow import context_for
    from segan.sequence import song_events
    from segan.voices import render_events

    ctx = context_for(project.config.mix)
    timeline = build_timeline(song)
    placed = placed_notes(song, timeline)
    dry = render_events(song_events(song, timeline, ctx.rate), ctx, 1)
    result: dict[str, Any] = {}
    for track in song.tracks.values():
        if track.drums or track.name not in dry:
            continue
        mine = sorted((p for p in placed if p.note.track == track.name), key=lambda p: p.step)
        if not mine:
            continue
        if any(a.step + a.note.length > b.step for a, b in zip(mine, mine[1:], strict=False)):  # one pitch per moment only
            result[track.name] = {"notes_checked": 0, "notes_skipped": len(mine), "skipped_because": {"chords or overlapping notes": len(mine)}}
            continue
        audio = dry[track.name][:, 0]
        notes: list[tuple[Any, str, float, float]] = []  # (placed note, instrument key, detected Hz, cents)
        skipped: dict[str, int] = {}

        def skip(reason: str) -> None:
            skipped[reason] = skipped.get(reason, 0) + 1

        previous_end = -1.0
        for p in mine:
            inst = song.kit.instruments.get(p.key)
            ringing_until = previous_end + (inst.env.release if inst is not None else 0.0)
            previous_end = timeline.seconds(p.step + p.note.length)
            if inst is None or inst.arp or inst.is_drum or inst.wave in ("noise", "bitnoise", "impulses") or is_one_shot(inst):
                skip("arpeggio, noise or one-shot instrument" if inst is not None else "no instrument")
                continue
            settle = max([0.08 if inst.is_sample else 0.015, *(t for t, _ in inst.pitch_env)])
            start = max(timeline.seconds(p.step) + settle, ringing_until)
            end = min(timeline.seconds(p.step + p.note.length), start + 0.2)
            if end - start < 0.05:
                skip("under 50 ms left to measure after the attack and the previous note's release")
                continue
            a, b = int(start * ctx.rate), int(end * ctx.rate)
            track_pitch = yin(audio[a:b], ctx.rate, hop=0.01)
            voiced = track_pitch.hz[track_pitch.hz > 0]
            if len(voiced) == 0:
                skip("no pitch detected")
                continue
            detected = float(np.median(voiced))
            notes.append((p, p.key, detected, _cents_off(detected, midi_to_hz_scalar(p.midi, ctx.tuning))))
        detune: dict[str, float] = {}
        for key in sorted({k for _, k, _, _ in notes}):
            own = [c for _, k, _, c in notes if k == key]
            if len(own) >= DETUNE_MIN_NOTES and abs(shared := float(np.median(own))) > 10:
                detune[key] = round(shared, 1)
        off: list[dict[str, Any]] = []
        worst = 0.0
        for p, key, detected, cents in notes:
            relative = cents - detune.get(key, 0.0)
            worst = max(worst, abs(relative))
            if abs(relative) > 50 and len(off) < 10:
                off.append({"bar": round(timeline.bar_of(p.step), 2), "note": song.key.name(int(p.midi)), "detected_hz": round(detected, 1), "cents": round(cents)})
        result[track.name] = {"notes_checked": len(notes), "notes_skipped": sum(skipped.values()), **({"skipped_because": skipped} if skipped else {}),
                              "max_abs_cents": round(worst, 1), "off": off,
                              **({"detune_cents": {(song.kit.instruments[k].name or k): v for k, v in detune.items()}} if detune else {})}  # fmt: skip
    return result
