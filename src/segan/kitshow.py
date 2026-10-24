"""`segan kit show`: every instrument of a kit playing a test phrase, as one listen sheet + WAVs.

Melodic instruments play a C-major arpeggio and a held note (moved by octaves into their `range`);
drums play a hit, an accent and a ghost. The whole kit shares one gain, so relative levels are the kit's.
It's the `palette show` of SEGAN: the first thing an owner signs off on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from segan.analysis import harmonic_aliasing_db, peak_db, yin
from segan.dsp import Signal, midi_to_hz_scalar, seed_of
from segan.kit import Kit
from segan.listen import BAD, GOOD, TEXT, Block, SheetSpec, listen_sheet
from segan.mix import bus, finish, room_tail
from segan.notes import note_name
from segan.patch import Env, Instrument
from segan.project import MixConfig, Project
from segan.synth import Context, render_note
from segan.voices import NoteEvent, render_events
from segan.wavio import to_pcm16, wav_bytes

PHRASE = (0, 4, 7, 12)  # C E G C
STEP = 0.25
GAP = 0.35
DRUM_HITS = ((0.0, 1.0), (0.45, 1.5), (0.8, 0.35))  # time, velocity (x, X, o)


def context_for(mix: MixConfig) -> Context:
    return Context(rate=mix.sample_rate, oversample=mix.oversample, tuning=mix.tuning, declick=mix.declick)


def phrase_root(inst: Instrument) -> int:
    """C4, moved by octaves so the phrase (root to root + 12) sits inside the instrument's range."""
    root = 60
    if inst.range is None:
        return root
    low, high = inst.range
    while root + 12 > high and root - 12 >= low - 0:
        root -= 12
    while root < low:
        root += 12
    return root


def aliasing_of(inst: Instrument, midi: int, ctx: Context) -> float | None:
    """Aliasing of a steady tone (modulation off) at `midi`; None for noise/unpitched/inharmonic sources."""
    fm = inst.fm
    inharmonic_fm = inst.wave == "fm" and fm is not None and any(r != round(r) for r in ([op.ratio for op in fm.ops] if fm.ops else [fm.ratio]))
    if inst.is_drum or inst.is_sample or inst.wave in ("noise", "bitnoise", "pluck", "modal", "additive", "supersaw") or inharmonic_fm:
        return None  # noise, inharmonic or detuned by design: nothing to measure against a harmonic series
    steady = replace(inst, env=Env(0.0, 0.0, 1.0, 0.0), pitch_env=(), vibrato=None, tremolo=None, arp=(), pwm=None,
                     unison=1, detune=0.0, filter=None, crush=None, fm=replace(inst.fm, env=None) if inst.fm else None)  # fmt: skip
    tone = render_note(steady, replace(ctx, measure=True), midi, 0.5, length=0.5)
    f0 = midi_to_hz_scalar(midi + (12 * inst.sub.octave if inst.sub is not None else 0), ctx.tuning)  # a sub-oscillator's harmonics include the note's
    return harmonic_aliasing_db(tone[2048:], ctx.rate, f0)


@dataclass
class KitShow:
    kit: Kit
    audio: Signal
    rate: int
    segments: list[tuple[str, int, int]]  # key, start, end frame
    targets: list[tuple[float, float, float]] = field(default_factory=list)
    aliasing: dict[str, float | None] = field(default_factory=dict)
    lufs: float = 0.0


def render_kit_show(kit: Kit, project: Project) -> KitShow:
    mix = project.config.mix
    ctx = context_for(mix)
    events: list[NoteEvent] = []
    segments: list[tuple[str, int, int]] = []
    targets: list[tuple[float, float, float]] = []
    aliasing: dict[str, float | None] = {}
    t = 0.0
    for key, inst in kit.instruments.items():
        start = t
        if inst.is_drum:
            for at, velocity in DRUM_HITS:
                events.append(NoteEvent(key, key, inst, round((t + at) * ctx.rate), 0.05, float(inst.note), velocity, seed_of(kit.name, key)))
            t += 1.0 + inst.tail()
        else:
            root = phrase_root(inst)
            for i, step in enumerate(PHRASE):
                note = root + step
                events.append(NoteEvent(key, key, inst, round((t + i * STEP) * ctx.rate), STEP * 0.8, float(note), 1.0, seed_of(kit.name, key)))
                targets.append((t + i * STEP, t + (i + 1) * STEP * 0.95, midi_to_hz_scalar(note, ctx.tuning)))
            held = len(PHRASE) * STEP
            events.append(NoteEvent(key, key, inst, round((t + held) * ctx.rate), 0.8, float(root), 1.0, seed_of(kit.name, key)))
            targets.append((t + held, t + held + 0.8, midi_to_hz_scalar(root, ctx.tuning)))
            t += held + 0.8 + inst.env.release
            top = inst.range[1] if inst.range else root + 12
            aliasing[key] = aliasing_of(inst, top, ctx)
        segments.append((key, round(start * ctx.rate), round(t * ctx.rate)))
        t += GAP
    channels = 2 if mix.music_channels == "stereo" else 1
    frames = round((t + room_tail(mix)) * ctx.rate)
    tracks = render_events(events, ctx, channels, frames)
    dry = np.sum(list(tracks.values()), axis=0) if tracks else np.zeros((frames, channels))
    wet = bus(dry, mix)[:frames]
    audio, level, _ = finish(wet, ctx.rate, project.config.target("music"), "integrated", mix.limiter)
    return KitShow(kit, audio, ctx.rate, segments, targets, aliasing, level.lufs)


def write_kit_show(show: KitShow, folder: Path, threshold: float) -> tuple[Path, list[Path]]:
    """kit sheet PNG + kit.wav + one WAV per instrument."""
    folder.mkdir(parents=True, exist_ok=True)
    kit = show.kit
    blocks = [Block(f"{key} {kit.instruments[key].name or kit.instruments[key].describe()}", a / show.rate, b / show.rate) for key, a, b in show.segments]
    worst = {k: v for k, v in show.aliasing.items() if v is not None}
    stats: list[tuple[str, str, tuple[int, int, int]]] = [
        ("instruments", str(len(kit.instruments)), TEXT),
        ("duration", f"{len(show.audio) / show.rate:.2f}s", TEXT),
        ("LUFS", f"{show.lufs:.1f}", TEXT),
        ("peak", f"{peak_db(show.audio):.1f} dBFS", TEXT),
    ]
    if worst:
        key, value = max(worst.items(), key=lambda kv: kv[1])
        stats.append(("worst aliasing", f"{value:.0f} dB ({key} at its top note)", BAD if value > threshold else GOOD))
    lines = []
    for key, inst in kit.instruments.items():
        alias = show.aliasing.get(key)
        rng = f" range {note_name(inst.range[0])}-{note_name(inst.range[1])}" if inst.range else ""
        lines.append(f"{key}: {inst.name or '-'} ({inst.describe()}{rng}, gain {inst.gain:+g} dB)" + (f", aliasing {alias:.0f} dB" if alias is not None else ""))
    pitch = yin(show.audio, show.rate)
    drum_spans = [(a / show.rate, b / show.rate) for key, a, b in show.segments if kit.instruments[key].is_drum]
    keep = np.array([not any(a <= t <= b for a, b in drum_spans) for t in pitch.times], dtype=bool)
    pitch = type(pitch)(pitch.times[keep], pitch.hz[keep]) if len(pitch.times) else pitch
    spec = SheetSpec(f"kit {kit.name}" + (f" - {kit.description}" if kit.description else ""), stats, show.audio, show.rate,
                     blocks=blocks, pitch=pitch, pitch_targets=show.targets, notes=lines)  # fmt: skip
    sheet = folder / f"{kit.name}.listen.png"
    listen_sheet(spec).save(sheet)
    wavs = [folder / f"{kit.name}.wav"]
    wavs[0].write_bytes(wav_bytes(to_pcm16(show.audio), show.rate))
    for key, a, b in show.segments:
        inst = kit.instruments[key]
        label = inst.name or f"key_{ord(key):x}"
        path = folder / f"{kit.name}.{label}.wav"
        path.write_bytes(wav_bytes(to_pcm16(show.audio[a:b]), show.rate))
        wavs.append(path)
    return sheet, wavs


def library_needs(path: Path, library: str = "vsco2") -> list[str]:
    """Instruments of one library (`vsco2/<name>`) a kit file names, in order (what `segan samples fetch` needs).

    `path` may also be a project folder: then every YAML under it (kits, songs and sfx; hidden folders
    skipped) is scanned, so samples named directly by sfx layers or songs are included too.
    """
    import re

    if path.is_dir():
        files = sorted(f for f in path.rglob("*.yaml") if not any(part.startswith(".") for part in f.relative_to(path).parts))
    else:
        files = [path]
    found = [m for f in files for m in re.findall(rf"sample:\s*{re.escape(library)}/(\w+)", f.read_text(encoding="utf-8"))]
    return list(dict.fromkeys(found))


def all_library_needs(path: Path) -> dict[str, list[str]]:
    """Every sample library a kit (or a project folder) uses -> its instruments in use."""
    from segan import libraries

    return {name: needs for name in libraries.names() if (needs := library_needs(path, name))}
