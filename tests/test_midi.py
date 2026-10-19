from __future__ import annotations

from pathlib import Path

import pytest

from segan.lint import lint_paths
from segan.midi import MidiError, estimate_key, import_midi, key_from_signature, read_midi, smf_bytes
from segan.project import Project

from conftest import make_project, run_json

Q = 480  # ticks per quarter


def on(ch: int, pitch: int, vel: int = 90) -> bytes:
    return bytes([0x90 | ch, pitch, vel])


def off(ch: int, pitch: int) -> bytes:
    return bytes([0x80 | ch, pitch, 0])


def song_file(key_sig: bool = True) -> bytes:
    meta = [(0, b"\xff\x51\x03" + (500000).to_bytes(3, "big")), (0, b"\xff\x58\x04\x04\x02\x18\x08")]
    if key_sig:
        meta.append((0, b"\xff\x59\x02\x00\x01"))  # 0 sharps, minor: A minor
    lead = [(0, b"\xff\x03\x04Lead"), (0, bytes([0xC0, 80]))]
    melody = [(0, 69), (Q, 72), (2 * Q, 76), (3 * Q + 7, 75)]  # the last one is late and off-key (D#5)
    for tick, pitch in melody:
        lead += [(tick, on(0, pitch)), (tick + Q - 10, off(0, pitch))]
    bass = [(0, b"\xff\x03\x04Bass"), (0, bytes([0xC1, 33]))]
    for bar in range(2):
        bass += [(bar * 4 * Q, on(1, 21)), (bar * 4 * Q + 2 * Q, off(1, 21))]  # A0: below the kit bass range -> octave up
    drums = [(0, b"\xff\x03\x05Drums")]
    for beat in range(8):
        drums += [(beat * Q, on(9, 36 if beat % 2 == 0 else 38, 110 if beat == 0 else 80)), (beat * Q + 60, off(9, 36 if beat % 2 == 0 else 38))]
        drums += [(beat * Q + Q // 2, on(9, 42, 40)), (beat * Q + Q // 2 + 30, off(9, 42))]
    drums += [(0, on(9, 81)), (30, off(9, 81))]  # a triangle: no kit drum
    return smf_bytes([meta, lead, bass, drums], Q)


def test_read_midi() -> None:
    midi = read_midi(song_file())
    assert midi.division == Q and midi.tempos == [(0, 120.0)] and midi.meters == [(0, 4, 4)] and midi.keys == [(0, 0, 1)]
    assert midi.track_names == {1: "Lead", 2: "Bass", 3: "Drums"}
    lead = [n for n in midi.notes if n.channel == 0]
    assert [n.pitch for n in lead] == [69, 72, 76, 75] and lead[0].program == 80 and lead[0].end == Q - 10
    with pytest.raises(MidiError):
        read_midi(b"RIFF....")


def test_running_status() -> None:
    data = smf_bytes([[(0, b"\x90\x3c\x40"), (100, b"\x3c\x00")]])  # note off as running-status note on, velocity 0
    notes = read_midi(data).notes
    assert len(notes) == 1 and notes[0].end == 100


def test_keys() -> None:
    assert key_from_signature(0, 1).describe() == "A minor"  # type: ignore[union-attr]
    assert key_from_signature(-1, 0).describe() == "F major"  # type: ignore[union-attr]
    midi = read_midi(song_file(key_sig=False))
    assert estimate_key([n for n in midi.notes if n.channel != 9]).scale in ("minor", "major")


def test_import_report_and_lint(project: Project) -> None:
    midi = read_midi(song_file())
    text, report = import_midi(midi, project.load_kit("t"), "t", "imported")
    path = project.music_dir / "imported.song.yaml"
    path.write_text(text)
    result = lint_paths(project, [path], render=False)
    assert not result.errors, ([f.format() for f in result.errors], text)
    r = report.as_dict()
    assert r["key"] == "A minor" and r["key_source"] == "key signature" and r["tempo"] == 120.0
    assert r["snapped_to_key"] == 1 and r["quantized"] == 1 and r["moved_by_octave"] == 2
    assert r["dropped"] == {"drum note 81 has no kit drum": 1}
    by_track = {t["track"]: t for t in r["tracks"]}
    assert by_track["lead"]["instrument"] == "p" and by_track["bass"]["instrument"] == "b" and by_track["drums"]["drums"] == ["k", "s", "h"]
    song = result.assets[0]
    assert song.tempo == 120 and song.loop == "main" and song.steps_per_beat == 4
    lead_pitches = sorted(song.tracks["lead"].rows[n.row] for p in song.patterns.values() for n in p.notes if n.track == "lead")
    assert lead_pitches == [69, 72, 74, 76]  # D#5 snapped down to D5
    accents = [n.velocity for p in song.patterns.values() for n in p.notes if n.key == "k"]
    assert 1.5 in accents and [n.velocity for p in song.patterns.values() for n in p.notes if n.key == "h"][0] == 0.35


def test_import_cli(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_project(in_tmp)
    (in_tmp / "tune.mid").write_bytes(song_file())
    code, data = run_json(["import", "midi", "tune.mid", "--quantize", "8"], capsys)
    assert code == 0, data
    assert Path(data["created"]).is_file() and data["report"]["notes_out"] > 10
    code, data = run_json(["import", "midi", "tune.mid"], capsys)
    assert code == 1 and "exists" in data["findings"][0]["message"]
    (in_tmp / "bad.mid").write_bytes(b"nope")
    code, data = run_json(["import", "midi", "bad.mid"], capsys)
    assert code == 1 and "MIDI" in data["findings"][0]["message"]
