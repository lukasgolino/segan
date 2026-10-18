"""Golden renders: decoded samples must match the committed WAVs within 1 LSB (float results can differ by
an ulp across machines); the same machine must produce byte-identical files.

After an intended rendering change: listen/look at the new output, then regenerate with
SEGAN_UPDATE_GOLDEN=1 pytest tests/test_golden.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from segan.dsp import seed_of
from segan.kitshow import context_for, render_kit_show
from segan.synth import render_note
from segan.project import load_project
from segan.wavio import read_wav, to_pcm16, wav_bytes

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
EXPECTED = GOLDEN / "expected"
UPDATE = bool(os.environ.get("SEGAN_UPDATE_GOLDEN"))


def check_golden(name: str, data: bytes) -> None:
    path = EXPECTED / name
    if UPDATE or not path.exists():
        if not UPDATE:
            pytest.fail(f"missing golden file {path}; run with SEGAN_UPDATE_GOLDEN=1 to create it")
        path.write_bytes(data)
        return
    expected, actual = read_wav(path.read_bytes()), read_wav(data)
    assert actual.rate == expected.rate and actual.samples.shape == expected.samples.shape
    assert actual.loop == expected.loop and actual.cues == expected.cues
    diff = np.abs(actual.samples.astype(np.int32) - expected.samples.astype(np.int32))
    assert int(diff.max()) <= 1, f"{name}: {int((diff > 1).sum())} samples differ by more than 1 LSB (max {int(diff.max())})"


def note_wav(key: str) -> bytes:
    project = load_project(GOLDEN)
    ctx = context_for(project.config.mix)
    inst = project.load_kit("golden").instruments[key]
    audio = render_note(inst, ctx, 72.0 if not inst.is_drum else float(inst.note), 0.25, 1.0, seed_of("golden", key))
    return wav_bytes(to_pcm16(audio), ctx.rate)


@pytest.mark.parametrize("key", list("pwtfankshcmy"))
def test_golden_notes(key: str) -> None:
    check_golden(f"note_{key}.wav", note_wav(key))


def test_kit_show_is_byte_identical_on_rerun() -> None:
    project = load_project(GOLDEN)
    kit = project.load_kit("golden")
    first, second = render_kit_show(kit, project), render_kit_show(kit, project)
    assert wav_bytes(to_pcm16(first.audio), first.rate) == wav_bytes(to_pcm16(second.audio), second.rate)
