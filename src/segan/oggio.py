"""Ogg Vorbis output (`export = [..., "ogg"]`, needs the `ogg` extra: soundfile/libsndfile).

libsndfile gives every Ogg stream a random serial number, so the bytes would differ on every build; the serial is
replaced by one derived from the file's name and each page's CRC recomputed, so a rebuild on the same machine is
byte-identical. Measured in Godot 4.7.2: its decoder matches libvorbis's to 1.5e-7, a new playback is late by the
same 2 frames as a WAV, and a loop restarts exactly at frame floor(loop_offset * rate) after the file's last frame.
"""

from __future__ import annotations

import hashlib
import io
import struct

import numpy as np

_CRC_TABLE: list[int] = []
for _i in range(256):
    _r = _i << 24
    for _ in range(8):
        _r = ((_r << 1) ^ 0x04C11DB7) if _r & 0x80000000 else (_r << 1)
    _CRC_TABLE.append(_r & 0xFFFFFFFF)


def available() -> bool:
    try:
        import soundfile  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _crc(data: bytes | bytearray) -> int:
    crc = 0
    table = _CRC_TABLE
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ table[(crc >> 24) ^ byte]
    return crc


def _fix_serial(raw: bytes, serial: int) -> bytes:
    """Every page's stream serial set to `serial`, its CRC recomputed."""
    out = bytearray(raw)
    at = 0
    while at < len(out):
        if out[at : at + 4] != b"OggS":
            raise ValueError(f"not an Ogg page at byte {at}")
        segments = out[at + 26]
        size = 27 + segments + sum(out[at + 27 : at + 27 + segments])
        out[at + 14 : at + 18] = struct.pack("<I", serial)
        out[at + 22 : at + 26] = b"\0\0\0\0"
        out[at + 22 : at + 26] = struct.pack("<I", _crc(out[at : at + size]))
        at += size
    return bytes(out)


def encode_ogg(pcm: np.ndarray, rate: int, quality: float, name: str) -> bytes:
    """int16 frames -> Ogg Vorbis bytes at `quality` (0-1, Vorbis q0-q10 / 10)."""
    import soundfile

    buffer = io.BytesIO()
    soundfile.write(buffer, pcm.astype(np.float32) / 32768.0, rate, format="OGG", subtype="VORBIS", compression_level=1.0 - quality)
    serial = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:4], "little")
    return _fix_serial(buffer.getvalue(), serial)


def decode_ogg(data: bytes) -> tuple[np.ndarray, int]:
    """Ogg Vorbis bytes -> float frames (libvorbis's decode, what Godot plays), rate."""
    import soundfile

    audio, rate = soundfile.read(io.BytesIO(data), dtype="float32", always_2d=True)
    return audio, int(rate)
