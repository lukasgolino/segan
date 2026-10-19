"""`segan import midi`: a standard MIDI file -> a song source (SEGAN's `pagan import png`).

The SMF reader is hand-written (no dependency): format 0/1, running status, tempo, time and key signatures,
program changes. The importer quantizes notes to the step grid, snaps pitches to the key (like snapping
colours to a palette), maps GM programs and drums to kit instruments, splits the song into patterns (identical
bars are reused) and reports every change it made: notes moved, snapped, moved by an octave, merged, dropped.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field
from typing import Any

from segan.kit import Kit
from segan.notes import Key, parse_key

# --- reading ----------------------------------------------------------------------------------


class MidiError(ValueError):
    pass


@dataclass(frozen=True)
class MidiNote:
    track: int
    channel: int
    program: int
    start: int  # ticks
    end: int
    pitch: int
    velocity: int


@dataclass
class MidiFile:
    division: int  # ticks per quarter note
    notes: list[MidiNote]
    tempos: list[tuple[int, float]]  # (tick, bpm)
    meters: list[tuple[int, int, int]]  # (tick, numerator, denominator)
    keys: list[tuple[int, int, int]]  # (tick, sharps (-7..7), minor 0/1)
    track_names: dict[int, str] = field(default_factory=dict)


def _varlen(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise MidiError("truncated variable-length number")
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, pos
    raise MidiError("variable-length number longer than 4 bytes")


def read_midi(data: bytes) -> MidiFile:
    if data[:4] != b"MThd" or len(data) < 14:
        raise MidiError("not a standard MIDI file (no MThd header)")
    length, fmt, ntracks, division = struct.unpack(">IHHH", data[4:14])
    if fmt not in (0, 1):
        raise MidiError(f"MIDI format {fmt} isn't supported (only 0 and 1)")
    if division & 0x8000:
        raise MidiError("SMPTE time division isn't supported (only ticks per quarter note)")
    pos = 8 + length
    notes: list[MidiNote] = []
    tempos: list[tuple[int, float]] = []
    meters: list[tuple[int, int, int]] = []
    keys: list[tuple[int, int, int]] = []
    names: dict[int, str] = {}
    for index in range(ntracks):
        if data[pos : pos + 4] != b"MTrk":
            raise MidiError(f"track {index}: no MTrk chunk")
        size = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
        chunk = data[pos + 8 : pos + 8 + size]
        pos += 8 + size
        tick = 0
        i = 0
        status = 0
        programs = [0] * 16
        sounding: dict[tuple[int, int], list[tuple[int, int, int]]] = {}  # (channel, pitch) -> [(start, velocity, program)]
        while i < len(chunk):
            delta, i = _varlen(chunk, i)
            tick += delta
            if i >= len(chunk):
                break
            byte = chunk[i]
            if byte == 0xFF:
                kind = chunk[i + 1]
                size_, i = _varlen(chunk, i + 2)
                payload = chunk[i : i + size_]
                i += size_
                if kind == 0x51 and size_ == 3:
                    micros = (payload[0] << 16) | (payload[1] << 8) | payload[2]
                    tempos.append((tick, 60_000_000 / micros))
                elif kind == 0x58 and size_ >= 2:
                    meters.append((tick, payload[0], 2 ** payload[1]))
                elif kind == 0x59 and size_ == 2:
                    keys.append((tick, struct.unpack("b", payload[:1])[0], payload[1]))
                elif kind == 0x03:
                    names[index] = payload.decode("latin-1").strip()
                elif kind == 0x2F:
                    break
                continue
            if byte in (0xF0, 0xF7):
                size_, i = _varlen(chunk, i + 1)
                i += size_
                continue
            if byte & 0x80:
                status = byte
                i += 1
            elif not status:
                raise MidiError(f"track {index}: data byte without a status (running status before any event)")
            command, channel = status & 0xF0, status & 0x0F
            width = 1 if command in (0xC0, 0xD0) else 2
            args = chunk[i : i + width]
            i += width
            if command == 0xC0:
                programs[channel] = args[0]
            elif command == 0x90 and args[1] > 0:
                sounding.setdefault((channel, args[0]), []).append((tick, args[1], programs[channel]))
            elif command in (0x80, 0x90):
                started = sounding.get((channel, args[0]))
                if started:
                    start, velocity, program = started.pop(0)
                    notes.append(MidiNote(index, channel, program, start, tick, args[0], velocity))
        for (channel, pitch), started in sounding.items():  # never released: end at the track's end
            notes.extend(MidiNote(index, channel, program, start, max(tick, start + 1), pitch, velocity) for start, velocity, program in started)
    notes.sort(key=lambda n: (n.start, n.track, n.channel, n.pitch))
    return MidiFile(division, notes, sorted(tempos), sorted(meters), sorted(keys), names)


def smf_bytes(tracks: list[list[tuple[int, bytes]]], division: int = 480) -> bytes:
    """A format-1 MIDI file from per-track (absolute tick, event bytes) lists (for tests and generator scripts)."""

    def varlen(value: int) -> bytes:
        out = [value & 0x7F]
        value >>= 7
        while value:
            out.insert(0, 0x80 | (value & 0x7F))
            value >>= 7
        return bytes(out)

    body = b""
    for events in tracks:
        chunk = b""
        last = 0
        for tick, event in sorted(events, key=lambda e: e[0]):
            chunk += varlen(tick - last) + event
            last = tick
        chunk += b"\x00\xff\x2f\x00"
        body += b"MTrk" + struct.pack(">I", len(chunk)) + chunk
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), division) + body


# --- importing --------------------------------------------------------------------------------

_MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
_SHARP_ROOTS = ("C", "G", "D", "A", "E", "B", "F#", "C#")
_FLAT_ROOTS = ("C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb")
_NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")

GM_DRUMS: dict[int, str] = {35: "kick", 36: "kick", 37: "snare", 38: "snare", 40: "snare", 39: "clap", 41: "tom", 43: "tom", 45: "tom",
                            47: "tom", 48: "tom", 50: "tom", 42: "hat", 44: "hat", 46: "open_hat", 49: "cymbal", 52: "cymbal", 55: "cymbal",
                            57: "cymbal", 51: "ride", 53: "ride", 59: "ride", 54: "hat", 56: "hat", 69: "hat", 70: "hat"}  # fmt: skip
DRUM_FALLBACK = {"open_hat": ("hat", "cymbal"), "ride": ("cymbal", "hat"), "clap": ("snare",), "tom": ("kick",), "cymbal": ("hat",)}


def key_from_signature(sharps: int, minor: int) -> Key | None:
    if not -7 <= sharps <= 7:
        return None
    major_root = _SHARP_ROOTS[sharps] if sharps >= 0 else _FLAT_ROOTS[-sharps]
    if not minor:
        return parse_key(f"{major_root} major")
    major = parse_key(f"{major_root} major")
    assert major is not None
    return parse_key(f"{_NAMES[(major.root + 9) % 12]} minor")  # the relative minor


def estimate_key(notes: list[MidiNote]) -> Key:
    """Krumhansl-Schmuckler: correlate the duration-weighted pitch-class histogram with the major/minor profiles."""
    weights = [0.0] * 12
    for n in notes:
        weights[n.pitch % 12] += n.end - n.start
    best: tuple[float, str] = (-2.0, "C major")
    for root in range(12):
        for profile, mode in ((_MAJOR_PROFILE, "major"), (_MINOR_PROFILE, "minor")):
            rotated = [profile[(pc - root) % 12] for pc in range(12)]
            score = _correlation(weights, rotated)
            if score > best[0]:
                best = (score, f"{_NAMES[root]} {mode}")
    key = parse_key(best[1])
    assert key is not None
    return key


def _correlation(a: list[float], b: list[float]) -> float:
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def _snap(pitch: int, key: Key) -> int:
    if key.contains(pitch):
        return pitch
    for distance in range(1, 7):
        if key.contains(pitch - distance):
            return pitch - distance
        if key.contains(pitch + distance):
            return pitch + distance
    return pitch


_FAMILY_HINTS = [
    (range(32, 40), ("bass",)),
    (range(88, 96), ("pad", "warm", "string")),
    (range(40, 56), ("pad", "string", "soft")),
    (range(0, 8), ("piano", "key", "epiano", "lead")),
    (range(8, 16), ("bell", "glock", "key")),
    (range(16, 24), ("organ", "pad", "key")),
    (range(24, 32), ("guitar", "pluck", "lead")),
    (range(56, 80), ("lead", "flute", "brass", "soft")),
    (range(80, 88), ("lead", "saw", "pulse")),
]


def _pick_instrument(kit: Kit, program: int, pitches: list[int], used: set[str]) -> str | None:
    """The kit instrument for a melodic MIDI part: name hints from the GM family, then range fit."""
    melodic = [k for k, i in kit.instruments.items() if not i.is_drum]
    if not melodic:
        return None
    hints = next((h for r, h in _FAMILY_HINTS if program in r), ("lead",))
    low, high = min(pitches), max(pitches)
    if program not in range(32, 40) and high <= 52:
        hints = ("bass", *hints)

    def score(key: str) -> tuple[float, ...]:
        inst = kit.instruments[key]
        name = (inst.name or "").lower()
        hint = next((len(hints) - i for i, h in enumerate(hints) if h in name), 0)
        if inst.range is None:
            inside = 1.0
        else:
            inside = sum(inst.range[0] <= p <= inst.range[1] for p in pitches) / len(pitches)
        is_bass = "bass" in name or (inst.range is not None and inst.range[1] <= 64)
        wants_bass = "bass" in hints[:2]
        return (hint, 1.0 if is_bass == wants_bass else 0.0, round(inside, 2), 0.5 if key not in used else 0.0, -melodic.index(key))

    del low
    return max(melodic, key=score)


def _drum_key(kit: Kit, kind: str) -> str | None:
    drums = {k: i for k, i in kit.instruments.items() if i.is_drum}

    def find(wave: str, open_hat: bool = False) -> str | None:
        matches = [k for k, i in drums.items() if i.wave == wave]
        if wave == "hat" and len(matches) > 1:
            ordered = sorted(matches, key=lambda k: drums[k].drum_param("decay"))
            return ordered[-1] if open_hat else ordered[0]
        return matches[0] if matches else None

    if kind == "open_hat":
        found = find("hat", open_hat=True)
        if found is not None:
            return found
    found = find(kind) if kind not in ("open_hat", "ride") else None
    if found is not None:
        return found
    for alternative in DRUM_FALLBACK.get(kind, ()):
        found = find(alternative)
        if found is not None:
            return found
    return None


@dataclass
class ImportReport:
    notes_in: int = 0
    notes_out: int = 0
    quantized: int = 0  # start or end moved to the grid
    snapped: int = 0  # pitch moved into the key
    octave_moved: int = 0  # moved by octaves into an instrument's range
    merged: int = 0  # overlapping notes on one row joined
    dropped: dict[str, int] = field(default_factory=dict)
    tempo: float = 120.0
    tempo_changes_ignored: int = 0
    key: str = ""
    key_source: str = ""
    meter: tuple[int, int] = (4, 4)
    tracks: list[dict[str, Any]] = field(default_factory=list)
    patterns: int = 0
    bars: int = 0

    def drop(self, reason: str, count: int = 1) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + count

    def as_dict(self) -> dict[str, Any]:
        return {"notes_in": self.notes_in, "notes_out": self.notes_out, "quantized": self.quantized, "snapped_to_key": self.snapped,
                "moved_by_octave": self.octave_moved, "merged": self.merged, "dropped": dict(sorted(self.dropped.items())),
                "tempo": self.tempo, "tempo_changes_ignored": self.tempo_changes_ignored, "key": self.key, "key_source": self.key_source,
                "meter": list(self.meter), "tracks": self.tracks, "patterns": self.patterns, "bars": self.bars}  # fmt: skip


def import_midi(midi: MidiFile, kit: Kit, kit_name: str | None, name: str, quantize: int = 16, key_text: str | None = None,
                bars_per_pattern: int = 2, loop: bool = True) -> tuple[str, ImportReport]:  # fmt: skip
    """Song source text + report. `quantize` = grid notes per whole note (16 = sixteenths)."""
    from segan import api

    report = ImportReport(notes_in=len(midi.notes))
    if not midi.notes:
        raise MidiError("the MIDI file has no notes")
    report.tempo = round(midi.tempos[0][1], 3) if midi.tempos else 120.0
    report.tempo_changes_ignored = max(0, len({round(t, 3) for _, t in midi.tempos}) - 1)
    numerator, denominator = (midi.meters[0][1], midi.meters[0][2]) if midi.meters else (4, 4)
    report.meter = (numerator, denominator)
    if quantize % denominator:
        raise MidiError(f"--quantize {quantize} doesn't divide into {denominator}th-note beats; use a multiple of {denominator}")
    steps_per_beat = quantize // denominator
    ticks_per_step = midi.division * 4 / quantize
    steps_per_bar = numerator * steps_per_beat
    melodic_notes = [n for n in midi.notes if n.channel != 9]
    if key_text is not None:
        key = api.key_of(key_text)
        report.key_source = "given"
    elif midi.keys and (signature := key_from_signature(midi.keys[0][1], midi.keys[0][2])) is not None:
        key = signature
        report.key_source = "key signature"
    else:
        key = estimate_key(melodic_notes or midi.notes)
        report.key_source = "estimated from the notes"
    report.key = key.describe()

    groups: dict[tuple[int, int], list[MidiNote]] = {}
    for n in midi.notes:
        groups.setdefault((n.track, n.channel), []).append(n)
    tracks: list[api.Track] = []
    placed: dict[str, list[tuple[int, int, int | str, str]]] = {}  # track -> (step, length, pitch or drum key, char)
    used: set[str] = set()
    total_steps = 0
    for (track_index, channel), notes in sorted(groups.items()):
        base = re.sub(r"[^a-z0-9_]", "_", midi.track_names.get(track_index, "").lower()).strip("_")
        tname = (base if base and base[0].isalpha() else "") or ("drums" if channel == 9 else f"part{len(tracks) + 1}")
        while any(t.name == tname for t in tracks):
            tname += "_2"
        events: list[tuple[int, int, int | str, str]] = []
        for n in notes:
            start = round(n.start / ticks_per_step)
            end = max(start + 1, round(n.end / ticks_per_step))
            late_or_early = abs(start * ticks_per_step - n.start) > 1
            if late_or_early or (channel != 9 and abs(end * ticks_per_step - n.end) > ticks_per_step / 4):
                report.quantized += 1
            if channel == 9:
                kind = GM_DRUMS.get(n.pitch)
                drum = _drum_key(kit, kind) if kind else None
                if drum is None:
                    report.drop(f"drum note {n.pitch} has no kit drum")
                    continue
                mark = "X" if n.velocity >= 100 else "o" if n.velocity < 50 else "x"
                events.append((start, 1, drum, mark))
            else:
                events.append((start, end - start, n.pitch, ""))
            total_steps = max(total_steps, end)
        if not events:
            continue
        if channel == 9:
            keys = sorted({str(e[2]) for e in events}, key=lambda k: list(kit.instruments).index(k))
            track = api.Track.drums(tname, keys)
            info = {"midi_track": track_index, "channel": channel + 1, "track": tname, "drums": keys}
        else:
            program = notes[0].program
            pitches = [int(e[2]) for e in events]
            inst_key = _pick_instrument(kit, program, pitches, used)
            if inst_key is None:
                report.drop("melodic notes but the kit has no melodic instrument", len(events))
                continue
            used.add(inst_key)
            inst = kit.instruments[inst_key]
            moved: list[tuple[int, int, int | str, str]] = []
            for step, length, pitch, _ in events:
                p = int(pitch)
                snapped = _snap(p, key)
                if snapped != p:
                    report.snapped += 1
                if inst.range is not None:
                    low, high = inst.range
                    shifted = snapped
                    while shifted < low:
                        shifted += 12
                    while shifted > high:
                        shifted -= 12
                    if not low <= shifted <= high or not key.contains(shifted):
                        report.drop("outside the instrument's range")
                        continue
                    if shifted != snapped:
                        report.octave_moved += 1
                    snapped = shifted
                moved.append((step, length, snapped, inst_key))
            events = moved
            if not events:
                continue
            low, high = min(int(e[2]) for e in events), max(int(e[2]) for e in events)
            track = api.Track.roll(tname, key, key.name(low), key.name(high))
            info = {"midi_track": track_index, "channel": channel + 1, "program": program, "track": tname, "instrument": inst_key,
                    "instrument_name": inst.name, "range": [key.name(low), key.name(high)]}  # fmt: skip
        tracks.append(track)
        placed[tname] = events
        report.tracks.append(info)

    pattern_steps = steps_per_bar * bars_per_pattern
    count = max(1, math.ceil(total_steps / pattern_steps))
    report.bars = count * bars_per_pattern
    patterns: dict[str, api.Pattern] = {}
    sequence: list[str] = []
    signatures: dict[tuple[str, ...], str] = {}
    builders = [api.Pattern(pattern_steps) for _ in range(count)]
    for track in tracks:
        events = sorted(placed[track.name], key=lambda e: (e[0], -e[1]))
        voices = 64 if track.percussion else kit.instruments[str(events[0][3])].voices
        busy: dict[int | str, int] = {}  # row -> step it's busy until
        sounding: list[int] = []  # end steps of notes playing now (polyphony)
        for step, length, pitch, char in events:
            index, local = divmod(step, pattern_steps)
            if index >= count:
                continue
            length = min(length, pattern_steps - local)
            if busy.get(pitch, -1) > step:
                report.merged += 1
                continue
            sounding = [end for end in sounding if end > step]
            if not track.percussion and len(sounding) >= voices:
                report.drop("more notes at once than the instrument's voices")
                continue
            builder = builders[index]
            try:
                if track.percussion:
                    builder.hit(track, local, str(pitch), char)
                else:
                    builder.note(track, local, int(pitch), length, char)
            except ValueError:
                report.merged += 1
                continue
            busy[pitch] = step + length
            sounding.append(step + length)
            report.notes_out += 1
    for builder in builders:
        lanes = tuple(builder.lane(t) for t in tracks)
        if lanes not in signatures:
            pname = _pattern_name(len(signatures))
            signatures[lanes] = pname
            patterns[pname] = builder
        sequence.append(signatures[lanes])
    report.patterns = len(patterns)
    text = api.song_yaml(name, tracks=tracks, patterns=dict(patterns), sections={"main": sequence}, arrangement=["main"], key=key,
                         tempo=report.tempo, loop="main" if loop else None,
                         description=f"Imported from MIDI ({report.notes_out} of {report.notes_in} notes); TODO: describe it",
                         kit=kit_name, meter=[numerator, denominator], steps_per_beat=steps_per_beat,
                         status="draft")  # fmt: skip
    return text, report


def _pattern_name(index: int) -> str:
    letters = "abcdefghijklmnopqrstuvwxyz"
    return letters[index] if index < 26 else f"p{index}"
