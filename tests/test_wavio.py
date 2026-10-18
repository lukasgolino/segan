import numpy as np

from segan.wavio import read_wav, to_pcm16, wav_bytes


def test_round_trip_with_loop_and_cues() -> None:
    samples = to_pcm16(np.stack([np.linspace(-1, 1, 1000), np.linspace(1, -1, 1000)], axis=1))
    data = wav_bytes(samples, 44100, loop=(100, 900), cues=[("drop", 500), ("end", 999)])
    wav = read_wav(data)
    assert wav.rate == 44100 and wav.channels == 2 and wav.frames == 1000
    assert np.array_equal(wav.samples, samples)
    assert wav.loop == (100, 900)
    assert wav.cues == [("drop", 500), ("end", 999)]
    assert data == wav_bytes(samples, 44100, loop=(100, 900), cues=[("drop", 500), ("end", 999)])


def test_smpl_chunk_end_is_inclusive_per_spec() -> None:
    data = wav_bytes(np.zeros(100, dtype=np.int16), 22050, loop=(10, 50))
    i = data.index(b"smpl")
    start, end = np.frombuffer(data[i + 8 + 44 : i + 8 + 52], dtype="<u4")
    assert (start, end) == (10, 49)


def test_pcm_conversion_clips() -> None:
    assert to_pcm16(np.array([2.0, -2.0, 0.5])).tolist() == [32767, -32768, 16384]
