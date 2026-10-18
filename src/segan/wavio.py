"""Deterministic WAV files: 16-bit PCM with a `smpl` chunk (loop points) and `cue `/`LIST adtl` (markers).

No timestamps, no software tag: the same samples always give the same bytes. Loop points in the `smpl`
chunk follow the RIFF spec (end = last sample of the loop, inclusive); SEGAN's manifest uses an exclusive
end (`loop.end` = the first sample after the loop), like Godot's `loop_end`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from segan.dsp import Signal

FULL_SCALE = 32767.0


def to_pcm16(samples: Signal) -> NDArray[np.int16]:
    """Float samples (-1..1) to int16, rounded half to even, clipped."""
    return np.clip(np.rint(samples * FULL_SCALE), -32768, 32767).astype(np.int16)


def _chunk(tag: bytes, payload: bytes) -> bytes:
    pad = b"\x00" if len(payload) % 2 else b""
    return tag + struct.pack("<I", len(payload)) + payload + pad


@dataclass(frozen=True)
class WavData:
    rate: int
    samples: NDArray[np.int16]  # (frames, channels)
    loop: tuple[int, int] | None = None  # start, end (exclusive)
    cues: list[tuple[str, int]] = field(default_factory=list)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])


def wav_bytes(samples: NDArray[np.int16], rate: int, loop: tuple[int, int] | None = None, cues: list[tuple[str, int]] | None = None) -> bytes:
    """A complete WAV file. `samples` is (frames,) or (frames, channels) int16."""
    data = samples.reshape(len(samples), -1) if samples.ndim == 1 else samples
    channels = data.shape[1]
    frames = data.shape[0]
    fmt = struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)
    body = _chunk(b"fmt ", fmt) + _chunk(b"data", np.ascontiguousarray(data, dtype="<i2").tobytes())
    if loop is not None:
        start, end = loop
        if not 0 <= start < end <= frames:
            raise ValueError(f"loop {loop} outside 0..{frames}")
        period = round(1e9 / rate)
        smpl = struct.pack("<9I", 0, 0, period, 60, 0, 0, 0, 1, 0)
        smpl += struct.pack("<6I", 0, 0, start, end - 1, 0, 0)  # id, forward, start, end (inclusive), fraction, infinite
        body += _chunk(b"smpl", smpl)
    if cues:
        points = b"".join(struct.pack("<II4sIII", i + 1, pos, b"data", 0, 0, pos) for i, (_, pos) in enumerate(cues))
        body += _chunk(b"cue ", struct.pack("<I", len(cues)) + points)
        labels = b"".join(_chunk(b"labl", struct.pack("<I", i + 1) + name.encode("utf-8") + b"\x00") for i, (name, _) in enumerate(cues))
        body += _chunk(b"LIST", b"adtl" + labels)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def read_wav(data: bytes) -> WavData:
    """Parse a 16-bit PCM WAV (as written by SEGAN, or any plain one)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos = 12
    rate = channels = bits = 0
    pcm = b""
    loop: tuple[int, int] | None = None
    cue_positions: dict[int, int] = {}
    labels: dict[int, str] = {}
    while pos + 8 <= len(data):
        tag = data[pos : pos + 4]
        size = struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        payload = data[pos + 8 : pos + 8 + size]
        if tag == b"fmt ":
            _, channels, rate, _, _, bits = struct.unpack("<HHIIHH", payload[:16])
        elif tag == b"data":
            pcm = payload
        elif tag == b"smpl" and size >= 60:
            count = struct.unpack("<I", payload[28:32])[0]
            if count:
                start, end = struct.unpack("<II", payload[44:52])
                loop = (start, end + 1)
        elif tag == b"cue ":
            count = struct.unpack("<I", payload[:4])[0]
            for i in range(count):
                cid, position = struct.unpack("<II", payload[4 + i * 24 : 12 + i * 24])
                cue_positions[cid] = position
        elif tag == b"LIST" and payload[:4] == b"adtl":
            sub = 4
            while sub + 8 <= len(payload):
                stag = payload[sub : sub + 4]
                ssize = struct.unpack("<I", payload[sub + 4 : sub + 8])[0]
                if stag == b"labl":
                    cid = struct.unpack("<I", payload[sub + 8 : sub + 12])[0]
                    labels[cid] = payload[sub + 12 : sub + 8 + ssize].rstrip(b"\x00").decode("utf-8")
                sub += 8 + ssize + (ssize % 2)
        pos += 8 + size + (size % 2)
    if bits != 16 or channels < 1:
        raise ValueError("only 16-bit PCM WAV is supported")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.int16).reshape(-1, channels)
    cues = [(labels.get(cid, str(cid)), position) for cid, position in sorted(cue_positions.items())]
    return WavData(rate, samples, loop, cues)
