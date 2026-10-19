"""Sampled instruments: WAV files, SFZ maps and SoundFont 2 (`.sf2`) banks, read by hand-written parsers.

A sampled instrument is a list of zones (a sample + the keys and velocities it covers, its root pitch, loop
and level). A note picks its zones by key and velocity (round robins by the note's seed, so renders stay
deterministic), and each zone is read at a variable rate (`2 ** ((pitch - root) / 12)`, so pitch curves,
vibrato and SFX keyframes work as on oscillators) with 4-point cubic Hermite interpolation at the
oversampled rate. Samples are mixed to mono: tracks are panned and roomed like every other voice.

Zone metadata (SFZ text, SF2 preset tables, WAV headers) is cheap and read at parse time, so lint can say a
sample is missing; audio is decoded on first use and cached for the process.

Supported SFZ: <control> <global> <master> <group> <region> headers; `default_path`, `sample`, `key`, `lokey`,
`hikey`, `pitch_keycenter`, `lovel`, `hivel`, `tune`, `transpose`, `volume`, `amplitude`, `offset`, `end`,
`loop_mode`, `loop_start`/`loop_end`, `seq_length`, `seq_position`, `lorand`/`hirand`, `trigger` (release
regions are skipped), `ampeg_attack/decay/sustain/release`, `#define`. Other opcodes are ignored and listed.
Supported SF2 generators: key/velocity ranges, sample, root key, coarse/fine tune, scale tuning, sample and
loop address offsets, sample modes, initial attenuation, volume envelope (attack/hold/decay/sustain/release).
Modulators, filters and effects sends are ignored.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from segan.dsp import Signal

SAMPLE_KINDS = ("wav", "sfz", "sf2", "library")
DEFAULT_RELEASE = 0.3


class SampleError(ValueError):
    """A sample file that can't be used (the message says which file and why)."""


@dataclass(frozen=True)
class SampleSpec:
    """What an instrument's `sample:` field names (paths resolved; `stamp` = file sizes and mtimes, so
    render caches notice a replaced file)."""

    kind: str  # wav | sfz | sf2 | library
    path: str
    root: int = 60  # wav: the pitch it was recorded at
    loop: bool | None = None  # wav: None = the smpl chunk's loop if it has one
    one_shot: bool | None = None  # None: from the file (SFZ loop_mode=one_shot); wav default false
    preset: int | str | None = None  # sf2: program number or preset name
    bank: int = 0
    velocity: int | None = None  # always play this velocity layer (1-127); None = from the note
    base: str = ""  # sfz sample folder (library: the download cache)
    stamp: tuple[tuple[str, int, int], ...] = ()


@dataclass(frozen=True)
class ZoneEnv:
    attack: float = 0.0
    hold: float = 0.0
    decay: float = 0.0
    sustain: float = 1.0
    release: float = DEFAULT_RELEASE


@dataclass(frozen=True)
class Zone:
    source: str  # file path
    fmt: str  # "wav" or "sf2"
    rate: int
    start: int  # first frame (after offsets)
    end: int  # frame after the last
    root: float  # MIDI pitch of the recording (tuning applied)
    lokey: int = 0
    hikey: int = 127
    lovel: int = 1
    hivel: int = 127
    loop: tuple[int, int] | None = None  # [start, end) frames, absolute in the file's frames
    gain: float = 1.0
    seq_length: int = 1
    seq_position: int = 1
    lorand: float = 0.0
    hirand: float = 1.0
    one_shot: bool = False
    env: ZoneEnv = field(default_factory=ZoneEnv)
    scale_tuning: float = 1.0  # semitones per key (SF2 scaleTuning / 100)
    sf2_data: tuple[int, int, int] | None = None  # sf2: (smpl chunk offset, sm24 offset or 0, total frames)

    @property
    def seconds(self) -> float:
        return (self.end - self.start) / self.rate


@dataclass(frozen=True)
class SampleSet:
    zones: tuple[Zone, ...]
    ignored: tuple[str, ...] = ()  # SFZ opcodes / SF2 generators read but not supported

    @property
    def env(self) -> ZoneEnv:
        return self.zones[0].env if self.zones else ZoneEnv()

    @property
    def one_shot(self) -> bool:
        return bool(self.zones) and all(z.one_shot for z in self.zones)

    def longest(self) -> float:
        """Seconds the longest zone stays audible (one-shots: how long a note rings)."""
        return max((audible_seconds(z) for z in self.zones), default=0.0)

    def key_span(self) -> tuple[int, int]:
        return (min(z.lokey for z in self.zones), max(z.hikey for z in self.zones)) if self.zones else (0, 127)

    def pick(self, key: int, velocity: int, seed: int) -> list[Zone]:
        """Zones for one note: matching key and velocity (nearest key if none), one round robin by seed."""
        matching = [z for z in self.zones if z.lokey <= key <= z.hikey and z.lovel <= velocity <= z.hivel]
        if not matching:
            on_key = [z for z in self.zones if z.lokey <= key <= z.hikey] or list(self.zones)
            if not on_key:
                return []
            nearest = min(abs(_vel_mid(z) - velocity) for z in on_key) if any(z.lokey <= key <= z.hikey for z in on_key) else None
            if nearest is not None:
                matching = [z for z in on_key if abs(_vel_mid(z) - velocity) == nearest]
            else:
                distance = min(_key_distance(z, key) for z in on_key)
                matching = [z for z in on_key if _key_distance(z, key) == distance]
        out = []
        for z in matching:
            if z.seq_length > 1 and (seed % z.seq_length) + 1 != z.seq_position:
                continue
            if z.lorand > 0.0 or z.hirand < 1.0:
                r = ((seed * 0x9E3779B1) & 0xFFFFFFFF) / 2**32
                if not z.lorand <= r < z.hirand:
                    continue
            out.append(z)
        return out or matching[:1]


def _vel_mid(z: Zone) -> float:
    return (z.lovel + z.hivel) / 2


def _key_distance(z: Zone, key: int) -> int:
    return z.lokey - key if key < z.lokey else key - z.hikey


# --- loading ---------------------------------------------------------------------------------------


def file_stamp(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return (str(path), st.st_size, st.st_mtime_ns)


@lru_cache(maxsize=64)
def load_set(spec: SampleSpec) -> SampleSet:
    """Zone metadata for a spec (raises SampleError)."""
    path = Path(spec.path)
    if spec.kind == "wav":
        info = wav_info(path)
        loop = info.loop if spec.loop is None else ((0, info.frames) if spec.loop else None)
        if spec.loop and info.loop is not None:
            loop = info.loop
        zone = Zone(str(path), "wav", info.rate, 0, info.frames, float(spec.root), loop=loop, one_shot=bool(spec.one_shot))
        return SampleSet((zone,))
    if spec.kind in ("sfz", "library"):
        result = parse_sfz(path.read_text(encoding="utf-8", errors="replace"), Path(spec.base) if spec.base else path.parent)
    elif spec.kind == "sf2":
        result = read_sf2(path, spec.preset, spec.bank)
    else:
        raise SampleError(f"unknown sample kind {spec.kind!r}")
    if spec.one_shot is not None:
        result = SampleSet(tuple(_with(z, one_shot=spec.one_shot) for z in result.zones), result.ignored)
    return result


def _with(zone: Zone, **changes: object) -> Zone:
    from dataclasses import replace

    return replace(zone, **changes)  # type: ignore[arg-type]


AUDIBLE_DB = -40.0  # under the rest of a mix by then; a -60 dB tail made loops twice as long for nothing


@lru_cache(maxsize=4096)
def audible_seconds(zone: Zone) -> float:
    """Seconds from the zone's start until it falls below AUDIBLE_DB of its peak for good (a one-shot's ring;
    sample files often carry seconds of near-silence)."""
    if zone.loop is not None:
        return zone.seconds
    data = np.abs(zone_audio(zone)[zone.start : zone.end])
    peak = float(data.max()) if len(data) else 0.0
    if peak <= 0:
        return 0.0
    loud = np.flatnonzero(data > peak * 10 ** (AUDIBLE_DB / 20))
    return (int(loud[-1]) + 1) / zone.rate


def zone_audio(zone: Zone) -> Signal:
    """The zone's frames [0, end) as mono float64 (decoded once per process)."""
    if zone.fmt == "sf2":
        assert zone.sf2_data is not None
        return _sf2_audio(zone.source, *zone.sf2_data)
    return _wav_audio(zone.source)


# --- WAV ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WavInfo:
    rate: int
    channels: int
    bits: int
    fmt: int  # 1 PCM, 3 float
    frames: int
    data_offset: int
    loop: tuple[int, int] | None  # [start, end)


@lru_cache(maxsize=4096)
def wav_info(path: Path) -> WavInfo:
    """Header and loop of any PCM (8/16/24/32-bit) or float WAV, without reading the audio."""
    try:
        with path.open("rb") as f:
            head = f.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                raise SampleError(f"{path}: not a WAV file")
            rate = channels = bits = fmt = 0
            data_offset = data_size = -1
            loop: tuple[int, int] | None = None
            while True:
                chunk = f.read(8)
                if len(chunk) < 8:
                    break
                tag, size = chunk[:4], struct.unpack("<I", chunk[4:])[0]
                if tag == b"fmt ":
                    payload = f.read(size)
                    fmt, channels, rate, _, _, bits = struct.unpack("<HHIIHH", payload[:16])
                    if fmt == 0xFFFE and len(payload) >= 26:  # WAVE_FORMAT_EXTENSIBLE: the real format is in the GUID
                        fmt = struct.unpack("<H", payload[24:26])[0]
                elif tag == b"data":
                    data_offset, data_size = f.tell(), size
                    f.seek(size, 1)
                elif tag == b"smpl" and size >= 60:
                    payload = f.read(size)
                    if struct.unpack("<I", payload[28:32])[0]:
                        start, end = struct.unpack("<II", payload[44:52])
                        loop = (start, end + 1)  # smpl end is inclusive
                else:
                    f.seek(size, 1)
                if size % 2:
                    f.seek(1, 1)
    except OSError as exc:
        raise SampleError(f"{path}: {exc.strerror or exc}") from None
    if data_offset < 0 or channels < 1 or fmt not in (1, 3) or (fmt == 1 and bits not in (8, 16, 24, 32)) or (fmt == 3 and bits not in (32, 64)):
        raise SampleError(f"{path}: unsupported WAV (need PCM 8/16/24/32-bit or float 32/64, got format {fmt}, {bits} bits)")
    frames = data_size // (channels * bits // 8)
    if loop is not None and not 0 <= loop[0] < loop[1] <= frames:
        loop = None
    return WavInfo(rate, channels, bits, fmt, frames, data_offset, loop)


@lru_cache(maxsize=256)
def _wav_audio(source: str) -> Signal:
    path = Path(source)
    info = wav_info(path)
    width = info.bits // 8
    with path.open("rb") as f:
        f.seek(info.data_offset)
        raw = f.read(info.frames * info.channels * width)
    if info.fmt == 3:
        data = np.frombuffer(raw, dtype="<f4" if info.bits == 32 else "<f8").astype(np.float64)
    elif info.bits == 8:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif info.bits == 16:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif info.bits == 24:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        data = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float64) / float(1 << 23)
    else:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / float(1 << 31)
    frames = data.reshape(-1, info.channels)
    return np.ascontiguousarray(frames.mean(axis=1) if info.channels > 1 else frames[:, 0])


# --- SFZ ---------------------------------------------------------------------------------------------

_SFZ_HEADERS = ("control", "global", "master", "group", "region")
_SFZ_SUPPORTED = {"sample", "default_path", "key", "lokey", "hikey", "pitch_keycenter", "lovel", "hivel", "tune", "transpose",
                  "volume", "amplitude", "offset", "end", "loop_mode", "loopmode", "loop_start", "loopstart", "loop_end",
                  "loopend", "seq_length", "seq_position", "lorand", "hirand", "trigger", "ampeg_attack", "ampeg_hold",
                  "ampeg_decay", "ampeg_sustain", "ampeg_release", "pitch_keytrack"}  # fmt: skip
_NOTE_RE = re.compile(r"^([a-gA-G])([#b]?)(-?\d+)$")


def sfz_key(value: str) -> int | None:
    """An SFZ key: a MIDI number or a note name (c4 = 60, c#4, db4)."""
    value = value.strip()
    if re.fullmatch(r"-?\d+", value):
        n = int(value)
        return n if -1 <= n <= 127 else None
    m = _NOTE_RE.match(value)
    if not m:
        return None
    letter, accidental, octave = m.groups()
    pitch = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}[letter.lower()] + {"#": 1, "b": -1, "": 0}[accidental]
    n = pitch + (int(octave) + 1) * 12
    return n if 0 <= n <= 127 else None


def _sfz_tokens(text: str) -> list[tuple[bool, str, str]]:
    """(is_header, name, value) in order. Values run to the next opcode (sample paths may have spaces)."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    defines: dict[str, str] = {}
    lines = []
    for line in text.splitlines():
        line = line.split("//", 1)[0]
        stripped = line.strip()
        if stripped.startswith("#define"):
            parts = stripped.split(None, 2)
            if len(parts) == 3:
                defines[parts[1]] = parts[2].strip()
            continue
        if stripped.startswith("#include"):
            raise SampleError("#include in SFZ isn't supported: inline the included file")
        for name in sorted(defines, key=len, reverse=True):
            line = line.replace(name, defines[name])
        lines.append(line)
    out: list[tuple[bool, str, str]] = []
    for line in lines:
        pos = 0
        for m in re.finditer(r"<(\w+)>", line):
            out += _sfz_opcodes(line[pos : m.start()])
            out.append((True, m.group(1).lower(), ""))
            pos = m.end()
        out += _sfz_opcodes(line[pos:])
    return out


def _sfz_opcodes(chunk: str) -> list[tuple[bool, str, str]]:
    matches = list(re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)=", chunk))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chunk)
        value = chunk[m.end() : end].strip()
        if m.group(1) != "sample":
            value = value.split()[0] if value else ""
        out.append((False, m.group(1).lower(), value))
    return out


def parse_sfz(text: str, base: Path) -> SampleSet:
    """Zones of an SFZ file; sample paths are relative to `base` (+ <control> default_path)."""
    levels: dict[str, dict[str, str]] = {h: {} for h in _SFZ_HEADERS}
    current: str | None = None
    regions: list[dict[str, str]] = []
    ignored: set[str] = set()

    def close() -> None:
        if current == "region":
            merged: dict[str, str] = {}
            for h in _SFZ_HEADERS:
                merged.update(levels[h])
            regions.append(merged)

    order = list(_SFZ_HEADERS)
    for is_header, name, value in _sfz_tokens(text):
        if is_header:
            close()
            current = name if name in _SFZ_HEADERS else None  # <curve>, <effect>, <midi>...: skipped
            if current is not None:
                for lower in order[order.index(current) :]:  # a new header resets itself and everything below it
                    levels[lower] = {}
            continue
        if name not in _SFZ_SUPPORTED:
            ignored.add(name)
        if current is not None:
            levels[current][name] = value
    close()
    zones = [_sfz_zone(r, base) for r in regions if r.get("trigger", "attack") in ("attack", "first", "legato") and r.get("sample")]
    if not zones:
        raise SampleError("the SFZ has no playable <region> with a sample=")
    return SampleSet(tuple(zones), tuple(sorted(ignored)))


def _num(region: dict[str, str], key: str, default: float) -> float:
    try:
        return float(region[key]) if key in region else default
    except ValueError:
        raise SampleError(f"SFZ {key}={region[key]!r} isn't a number") from None


def _sfz_zone(r: dict[str, str], base: Path) -> Zone:
    rel = (r.get("default_path", "") + r["sample"]).replace("\\", "/")
    path = (base / rel).resolve()
    if not path.is_file():
        raise SampleError(f"sample {rel!r} not found (looked in {base})")
    info = wav_info(path)

    def key(name: str, default: int) -> int:
        if name not in r:
            return default
        k = sfz_key(r[name])
        if k is None:
            raise SampleError(f"SFZ {name}={r[name]!r} isn't a key (60 or c4)")
        return k

    k = key("key", -1)
    lokey, hikey = key("lokey", k if k >= 0 else 0), key("hikey", k if k >= 0 else 127)
    center = key("pitch_keycenter", k if k >= 0 else 60)
    keytrack = _num(r, "pitch_keytrack", 100.0) / 100.0
    root = center - _num(r, "tune", 0.0) / 100.0 - _num(r, "transpose", 0.0)
    gain = 10 ** (_num(r, "volume", 0.0) / 20) * _num(r, "amplitude", 100.0) / 100.0
    start = int(_num(r, "offset", 0))
    end = min(info.frames, int(_num(r, "end", info.frames - 1)) + 1)  # SFZ end is the last frame
    mode = r.get("loop_mode", r.get("loopmode", "loop_continuous" if info.loop else "no_loop"))
    loop: tuple[int, int] | None = None
    if mode in ("loop_continuous", "loop_sustain"):
        ls = int(_num(r, "loop_start", _num(r, "loopstart", info.loop[0] if info.loop else start)))
        le = int(_num(r, "loop_end", _num(r, "loopend", (info.loop[1] - 1) if info.loop else end - 1))) + 1
        loop = (ls, le) if start <= ls < le <= end else None
    env = ZoneEnv(_num(r, "ampeg_attack", 0.0), _num(r, "ampeg_hold", 0.0), _num(r, "ampeg_decay", 0.0),
                  _num(r, "ampeg_sustain", 100.0) / 100.0, _num(r, "ampeg_release", DEFAULT_RELEASE))  # fmt: skip
    return Zone(str(path), "wav", info.rate, start, end, root, lokey, hikey, int(_num(r, "lovel", 1)), int(_num(r, "hivel", 127)),
                loop, gain, int(_num(r, "seq_length", 1)), int(_num(r, "seq_position", 1)), _num(r, "lorand", 0.0),
                _num(r, "hirand", 1.0), mode == "one_shot", env, keytrack)  # fmt: skip


# --- SoundFont 2 -------------------------------------------------------------------------------------

_SF2_SUPPORTED = {0, 1, 2, 3, 4, 12, 33, 34, 35, 36, 37, 38, 41, 43, 44, 45, 48, 50, 51, 52, 53, 54, 56, 58}
_SF2_NAMES = {8: "initialFilterFc", 9: "initialFilterQ", 17: "pan", 15: "chorusEffectsSend", 16: "reverbEffectsSend",
              5: "modLfoToPitch", 6: "vibLfoToPitch", 7: "modEnvToPitch", 11: "modEnvToFilterFc", 25: "delayModEnv",
              26: "attackModEnv", 28: "decayModEnv", 29: "sustainModEnv", 30: "releaseModEnv", 22: "freqModLFO",
              24: "freqVibLFO", 21: "delayModLFO", 23: "delayVibLFO", 13: "modLfoToVolume", 39: "keynumToVolEnvHold",
              40: "keynumToVolEnvDecay", 46: "keynum", 47: "velocity", 57: "exclusiveClass"}  # fmt: skip
_ADDITIVE_EXCLUDED = {0, 1, 2, 3, 4, 12, 45, 50, 54, 58, 43, 44, 46, 47, 57}  # preset level can't change these


@dataclass(frozen=True)
class _Sf2:
    presets: list[tuple[str, int, int, int]]  # name, program, bank, bag index
    pbag: list[int]
    pgen: list[tuple[int, int]]
    insts: list[tuple[str, int]]
    ibag: list[int]
    igen: list[tuple[int, int]]
    shdr: list[tuple[str, int, int, int, int, int, int, int, int]]  # name, start, end, loop start, loop end, rate, pitch, corr, type
    smpl_offset: int
    sm24_offset: int
    smpl_frames: int


def _riff_chunks(f: object, start: int, end: int) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    pos = start
    while pos + 8 <= end:
        f.seek(pos)  # type: ignore[attr-defined]
        head = f.read(8)  # type: ignore[attr-defined]
        tag, size = head[:4].decode("latin-1"), struct.unpack("<I", head[4:])[0]
        if tag == "LIST":
            kind = f.read(4).decode("latin-1")  # type: ignore[attr-defined]
            out[kind] = (pos + 12, pos + 8 + size)
            for sub, span in _riff_chunks(f, pos + 12, pos + 8 + size).items():
                out[sub] = span
        else:
            out[tag] = (pos + 8, pos + 8 + size)
        pos += 8 + size + (size % 2)
    return out


@lru_cache(maxsize=16)
def _sf2_tables(source: str) -> _Sf2:
    path = Path(source)
    try:
        with path.open("rb") as f:
            head = f.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"sfbk":
                raise SampleError(f"{path}: not a SoundFont 2 file")
            size = struct.unpack("<I", head[4:8])[0]
            chunks = _riff_chunks(f, 12, 8 + size)

            def table(tag: str, fmt: str) -> list[tuple[Any, ...]]:
                if tag not in chunks:
                    raise SampleError(f"{path}: SoundFont is missing its {tag} table")
                a, b = chunks[tag]
                f.seek(a)
                raw = f.read(b - a)
                width = struct.calcsize(fmt)
                return [struct.unpack(fmt, raw[i : i + width]) for i in range(0, len(raw) - width + 1, width)]

            phdr = table("phdr", "<20sHHHIII")
            pbag = table("pbag", "<HH")
            pgen = table("pgen", "<HH")
            inst = table("inst", "<20sH")
            ibag = table("ibag", "<HH")
            igen = table("igen", "<HH")
            shdr = table("shdr", "<20sIIIIIBbHH")
    except OSError as exc:
        raise SampleError(f"{path}: {exc.strerror or exc}") from None
    if "smpl" not in chunks:
        raise SampleError(f"{path}: SoundFont has no sample data")
    smpl = chunks["smpl"]
    sm24 = chunks.get("sm24", (0, 0))

    def name(raw: bytes) -> str:
        return raw.split(b"\x00", 1)[0].decode("latin-1").strip()

    return _Sf2(
        [(name(p[0]), int(p[1]), int(p[2]), int(p[3])) for p in phdr],
        [int(b[0]) for b in pbag],
        [(int(g[0]), int(g[1])) for g in pgen],
        [(name(i[0]), int(i[1])) for i in inst],
        [int(b[0]) for b in ibag],
        [(int(g[0]), int(g[1])) for g in igen],
        [(name(s[0]), int(s[1]), int(s[2]), int(s[3]), int(s[4]), int(s[5]), int(s[6]), int(s[7]), int(s[8])) for s in shdr],
        smpl[0], sm24[0], (smpl[1] - smpl[0]) // 2,
    )  # fmt: skip


def sf2_presets(path: Path) -> list[tuple[int, int, str]]:
    """(bank, program, name) of every preset (`segan samples list` shows them)."""
    t = _sf2_tables(str(path))
    return sorted((bank, program, name) for name, program, bank, _ in t.presets[:-1])


def _s16(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def _zones(bags: list[int], gens: list[tuple[int, int]], first: int, last: int, terminal: int) -> tuple[dict[int, int], list[dict[int, int]]]:
    """(global zone, local zones) of one preset or instrument; a first zone without `terminal` is global."""
    zones = []
    for b in range(first, last):
        zone: dict[int, int] = {}
        for op, amount in gens[bags[b] : bags[b + 1]]:
            zone[op] = amount
        zones.append(zone)
    glob: dict[int, int] = {}
    if zones and terminal not in zones[0]:
        glob = zones.pop(0)
    return glob, [z for z in zones if terminal in z]


def _range(zone: dict[int, int], op: int) -> tuple[int, int]:
    value = zone.get(op)
    return (0, 127) if value is None else (value & 0xFF, value >> 8)


def read_sf2(path: Path, preset: int | str | None, bank: int = 0) -> SampleSet:
    t = _sf2_tables(str(path))
    headers = t.presets[:-1]  # the last one is the terminal record
    if isinstance(preset, str):
        found = [i for i, p in enumerate(headers) if p[0].lower() == preset.lower()]
    else:
        found = [i for i, p in enumerate(headers) if p[1] == (preset or 0) and p[2] == bank]
    if not found:
        names = ", ".join(f"{p[2]}:{p[1]} {p[0]}" for p in sorted(headers, key=lambda p: (p[2], p[1]))[:12])
        raise SampleError(f"{path.name}: no preset {preset!r} in bank {bank} (presets: {names}...; `segan samples list {path}` shows all)")
    index = found[0]
    pglob, pzones = _zones(t.pbag, t.pgen, t.presets[index][3], t.presets[index + 1][3], 41)
    zones: list[Zone] = []
    ignored: set[str] = set()
    for pz in pzones:
        pgen = {**pglob, **pz}
        inst_index = pgen[41]
        if inst_index + 1 >= len(t.insts):
            continue
        iglob, izones = _zones(t.ibag, t.igen, t.insts[inst_index][1], t.insts[inst_index + 1][1], 53)
        pk, pv = _range(pgen, 43), _range(pgen, 44)
        for iz in izones:
            gen = {**iglob, **iz}
            ignored |= {_SF2_NAMES.get(op, str(op)) for op in (*gen, *pgen) if op not in _SF2_SUPPORTED}
            ik, iv = _range(gen, 43), _range(gen, 44)
            lokey, hikey = max(pk[0], ik[0]), min(pk[1], ik[1])
            lovel, hivel = max(pv[0], iv[0]), min(pv[1], iv[1])
            if lokey > hikey or lovel > hivel:
                continue

            def value(op: int, default: int) -> int:
                v = _s16(gen[op]) if op in gen else default
                if op in pgen and op not in _ADDITIVE_EXCLUDED:
                    v += _s16(pgen[op])
                return v

            zones.append(_sf2_zone(t, str(path), gen, value, lokey, hikey, lovel, hivel))
    if not zones:
        raise SampleError(f"{path.name}: preset {headers[index][0]!r} has no sample zones")
    return SampleSet(tuple(zones), tuple(sorted(ignored)))


def _timecents(tc: int) -> float:
    return 0.0 if tc <= -12000 else 2.0 ** (tc / 1200.0)


def _sf2_zone(t: _Sf2, source: str, gen: dict[int, int], value: object, lokey: int, hikey: int, lovel: int, hivel: int) -> Zone:
    val = value  # (op, default) -> combined generator value
    sample = t.shdr[gen[53]]
    _, s_start, s_end, s_ls, s_le, rate, pitch, corr, _ = sample

    def v(op: int, default: int = 0) -> int:
        return int(val(op, default))  # type: ignore[operator]

    start = s_start + v(0) + 32768 * v(4)
    end = s_end + v(1) + 32768 * v(12)
    ls = s_ls + v(2) + 32768 * v(45)
    le = s_le + v(3) + 32768 * v(50)
    root_key = v(58, -1)
    root = float(root_key if 0 <= root_key <= 127 else (pitch if pitch <= 127 else 60))
    root -= v(51) + (v(52) + corr) / 100.0
    mode = v(54) & 3
    loop = (ls - start, le - start) if mode in (1, 3) and start <= ls < le <= end else None
    attenuation = max(0, v(48)) * 0.04  # dB; 0.4 x cB as most players do
    sustain = 10 ** (-min(1440, max(0, v(37))) / 200.0)
    env = ZoneEnv(_timecents(v(34, -12000)), _timecents(v(35, -12000)), _timecents(v(36, -12000)), sustain, _timecents(v(38, -12000)))
    total = end - start
    if total <= 0:
        raise SampleError(f"SoundFont sample {sample[0]!r} has no frames")
    return Zone(source, "sf2", rate, 0, total, root, lokey, hikey, lovel, hivel, loop, 10 ** (-attenuation / 20), one_shot=False, env=env,
                scale_tuning=v(56, 100) / 100.0, sf2_data=(t.smpl_offset + 2 * start, (t.sm24_offset + start) if t.sm24_offset else 0, total))  # fmt: skip


@lru_cache(maxsize=1024)
def _sf2_audio(source: str, offset: int, offset24: int, frames: int) -> Signal:
    with Path(source).open("rb") as f:
        f.seek(offset)
        data = np.frombuffer(f.read(2 * frames), dtype="<i2").astype(np.float64) / 32768.0
        if offset24:
            f.seek(offset24)
            low = np.frombuffer(f.read(frames), dtype=np.uint8).astype(np.float64)
            data = data + low / (32768.0 * 256.0)
    return data


# --- playback ----------------------------------------------------------------------------------------


def hermite(data: Signal, pos: Signal) -> Signal:
    """4-point cubic Hermite (Catmull-Rom) read of `data` at fractional positions (0 outside)."""
    padded = np.concatenate([[0.0], data, [0.0, 0.0, 0.0]])
    i = np.floor(pos).astype(np.int64)
    frac = pos - i
    valid = (i >= 0) & (i < len(data))
    j = np.clip(i, 0, len(data) - 1) + 1
    y0, y1, y2, y3 = padded[j - 1], padded[j], padded[j + 1], padded[j + 2]
    c1 = 0.5 * (y2 - y0)
    c2 = y0 - 2.5 * y1 + 2.0 * y2 - 0.5 * y3
    c3 = 0.5 * (y3 - y0) + 1.5 * (y1 - y2)
    out = ((c3 * frac + c2) * frac + c1) * frac + y1
    return np.where(valid, out, 0.0)


def play(sset: SampleSet, semis: Signal, key: int, velocity: int, seed: int, os_rate: int, tuning: float = 440.0) -> Signal:
    """Sum of the note's zones, each read at the rate its pitch curve (`semis`, MIDI per sample) asks for."""
    from segan.dsp import exp2

    n = len(semis)
    out = np.zeros(n)
    detune = 12.0 * math.log2(tuning / 440.0)
    for zone in sset.pick(key, velocity, seed):
        data = zone_audio(zone)[: zone.end]
        offset = (key - zone.root) * zone.scale_tuning + detune
        if n and semis[0] == semis[-1] and not np.any(semis != semis[0]):  # steady pitch: one rate
            step = 2.0 ** ((float(semis[0]) - key + offset) / 12.0) * (zone.rate / os_rate)
            pos = zone.start + np.arange(n) * step
        else:
            inc = exp2((semis - key + offset) / 12.0) * (zone.rate / os_rate)
            pos = zone.start + np.concatenate([[0.0], np.cumsum(inc[:-1])])
        if zone.loop is None:  # past the sample's end is silence: don't interpolate it
            n_live = int(np.searchsorted(pos, zone.end, side="left"))  # pos only grows (rates are positive)
            if n_live < n:
                out[:n_live] += hermite(data, pos[:n_live]) * zone.gain
                continue
        if zone.loop is not None:
            ls, le = zone.loop
            span = le - ls
            pos = np.where(pos >= le, ls + np.mod(pos - ls, span), pos)
        out += hermite(data, pos) * zone.gain
    return out


def blob_sha1(data: bytes) -> str:
    """Git's blob id of `data` (how the library lock files pin downloaded samples)."""
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
