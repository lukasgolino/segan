"""Recorded sounds: decoding sound files (WAV by hand; Ogg Vorbis, FLAC and MP3 through soundfile, the `ogg`
extra) and preparing them for an SFX recorded layer (trim, reverse, independent stretch and shift, fades).

A recorded layer plays its file as recorded (one-shot, mixed to mono); `pitch` keyframes still work as on any
sample (varispeed, C4 = as recorded), while `shift` and `stretch` change pitch and length independently
(stretch.py). The prepared sound is peak-normalised to full scale, so a layer's `gain` is its balance against the
other layers whatever level the file was recorded at, and every file of a list plays at the same level.

Decoded and prepared audio is cached per process (keyed on the file's size and mtime too, so an edited file
is read again).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from segan.dsp import Signal
from segan.samples import Processing, SampleError, _wav_audio, wav_info

RECORDED_SUFFIXES = (".wav", ".ogg", ".oga", ".flac", ".mp3")


def _stamp(path: str) -> tuple[int, int]:
    try:
        st = Path(path).stat()
    except OSError as exc:
        raise SampleError(f"{path}: {exc.strerror or exc}") from None
    return st.st_size, st.st_mtime_ns


def _soundfile(path: str):  # type: ignore[no-untyped-def]
    try:
        import soundfile
    except ImportError:
        raise SampleError(f"{Path(path).name}: decoding {Path(path).suffix} files needs the ogg extra: pip install \"segan[ogg]\"") from None
    return soundfile


def file_shape(path: str) -> tuple[int, int]:
    """(frames, sample rate) of a sound file, without decoding it."""
    return _file_shape(path, *_stamp(path))


@lru_cache(maxsize=256)
def _file_shape(path: str, size: int, mtime: int) -> tuple[int, int]:
    if Path(path).suffix.lower() == ".wav":
        info = wav_info(Path(path))
        return info.frames, info.rate
    sf = _soundfile(path)
    try:
        info = sf.info(path)
    except RuntimeError as exc:
        raise SampleError(f"{Path(path).name}: can't decode ({exc})") from None
    return int(info.frames), int(info.samplerate)


def decode(path: str) -> tuple[Signal, int]:
    """The file as mono float64 (channels averaged) and its sample rate."""
    return _decode(path, *_stamp(path))


@lru_cache(maxsize=32)
def _decode(path: str, size: int, mtime: int) -> tuple[Signal, int]:
    if Path(path).suffix.lower() == ".wav":
        return _wav_audio(path), wav_info(Path(path)).rate
    sf = _soundfile(path)
    try:
        data, rate = sf.read(path, dtype="float64", always_2d=True)
    except RuntimeError as exc:
        raise SampleError(f"{Path(path).name}: can't decode ({exc})") from None
    return np.ascontiguousarray(data.mean(axis=1)), int(rate)


def _trim_frames(frames: int, rate: int, process: Processing) -> tuple[int, int]:
    start = min(frames, round(process.trim_start * rate))
    end = frames if process.trim_end is None else min(frames, round(process.trim_end * rate))
    return start, max(start, end)


def processed_shape(path: str, process: Processing) -> tuple[int, int]:
    """(frames, rate) of the prepared sound, without decoding or processing it (lint reads this at parse time)."""
    frames, rate = file_shape(path)
    start, end = _trim_frames(frames, rate, process)
    if end - start <= 0:
        raise SampleError(f"{Path(path).name}: nothing left after trim (the file is {frames / rate:.3f} s long)")
    return round((end - start) * process.stretch), rate


def processed(path: str, process: Processing) -> Signal:
    return _processed(path, process, *_stamp(path))


@lru_cache(maxsize=64)
def _processed(path: str, process: Processing, size: int, mtime: int) -> Signal:
    from segan.stretch import stretch

    data, rate = decode(path)
    start, end = _trim_frames(len(data), rate, process)
    x = data[start:end]
    if process.reverse:
        x = x[::-1]
    x = stretch(x, rate, process.stretch, process.shift)
    x = np.array(x, dtype=np.float64)
    for seconds, head in ((process.fade_in, True), (process.fade_out, False)):
        n = min(len(x), round(seconds * rate))
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n, endpoint=False) ** 2
            if head:
                x[:n] *= ramp
            else:
                x[len(x) - n :] *= ramp[::-1]
    peak = float(np.abs(x).max()) if len(x) else 0.0
    return x / peak if peak > 0 else x


def inspect(path: str) -> dict[str, object]:
    """Numbers an agent that can't hear can compare candidates by: length, loudness, peak, brightness, pitch, onsets."""
    from segan.analysis import integrated_lufs, max_momentary_lufs, onsets, peak_db, spectral_centroid, yin
    from segan.notes import note_name

    frames, rate = file_shape(path)
    data, _ = decode(path)
    track = yin(data, rate, fmin=40.0, fmax=2000.0, hop=0.02, require_fundamental=True)
    voiced = track.hz[track.hz > 0]
    pitch: dict[str, object] | None = None
    if len(voiced) >= 0.2 * max(1, len(track.hz)):  # mostly unvoiced (noise, impacts): no pitch to speak of
        from segan.dsp import hz_to_midi

        hz = float(np.median(voiced))
        midi = hz_to_midi(hz)
        pitch = {"hz": round(hz, 1), "note": note_name(round(midi)), "cents": round((midi - round(midi)) * 100), "voiced": round(len(voiced) / len(track.hz), 2)}
    found = onsets(data, rate, max_count=32)
    return {
        "file": Path(path).name,
        "seconds": round(frames / rate, 3),
        "sample_rate": rate,
        "peak_dbfs": round(peak_db(data), 2),
        "lufs_max_momentary": round(max_momentary_lufs(data, rate), 2),
        "lufs_integrated": round(integrated_lufs(data, rate), 2),
        "centroid_hz": round(spectral_centroid(data, rate), 1),
        "pitch": pitch,
        "onsets_s": found,
    }
