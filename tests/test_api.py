from __future__ import annotations

import pytest

from segan import api
from segan.project import Project

from conftest import load


def test_notes_scales_chords() -> None:
    assert api.note("A4") == 69 and api.note(60) == 60
    assert api.scale("C major", "C4", "C5") == [60, 62, 64, 65, 67, 69, 71, 72]
    assert api.chord(1, "A minor", octave=3) == [57, 60, 64]  # A C E
    assert api.chord(5, "C major", octave=4, size=4) == [67, 71, 74, 77]  # G7
    assert api.progression("i VI III VII", "A minor", octave=3)[1] == [65, 69, 72]  # F A C
    with pytest.raises(ValueError):
        api.progression("i X", "A minor")


def test_euclid_and_arpeggiate_and_humanize() -> None:
    assert api.euclid(3, 8) == [True, False, False, True, False, False, True, False]
    assert sum(api.euclid(5, 16)) == 5 and api.euclid(1, 4, rotate=1) == [False, True, False, False]
    assert api.arpeggiate([64, 60, 67], 8, rate=2) == [(0, 60, 2), (2, 64, 2), (4, 67, 2), (6, 60, 2)]
    assert [m for _, m, _ in api.arpeggiate([60, 64, 67], 8, order="updown")][:5] == [60, 64, 67, 64, 60]
    row = "x.x.x.x.x.x.x.x."
    assert api.humanize(row, 1, 0.5) == api.humanize(row, 1, 0.5) and set(api.humanize(row, 1, 1.0)) <= set("xXo.")


def test_generated_song_parses_and_matches(project: Project) -> None:
    key = "A minor"
    lead = api.Track.roll("lead", key, "C5", "C6")
    bass = api.Track.roll("bass", key, "C3", "C4", gain=-2)
    drums = api.Track.drums("drums", ["k", "s", "h"])
    a = api.Pattern(16)
    for step, midi, length in api.arpeggiate(api.chord(3, key, octave=4), 16, rate=4):
        a.note(lead, step, midi, length, "p")
    a.note(bass, 0, "A3", 8, "b").note(bass, 8, "E3", 8, "b")
    for step, hit in enumerate(api.euclid(4, 16)):
        if hit:
            a.hit(drums, step, "k")
    a.row(drums, "h", api.humanize("x.x.x.x.x.x.x.x.", 2))
    text = api.song_yaml("gen", tracks=[lead, bass, drums], patterns={"a": a, "b": {"from": "a", "mute": ["lead"]}},
                         sections={"main": ["a", "b"]}, arrangement=["main"], key=key, tempo=110, loop="main", kit="t",
                         description="generated")  # fmt: skip
    song, findings = load(project, "song", "gen", text)
    assert song is not None, (findings, text)
    leads = sorted((n.step, song.tracks["lead"].rows[n.row]) for n in song.patterns["a"].notes if n.track == "lead")
    assert leads == [(0, 72), (4, 76), (8, 79), (12, 72)]
    with pytest.raises(ValueError):
        api.Pattern(4).note(lead, 0, "C#5")


def test_generated_sfx_parses(project: Project) -> None:
    text = api.sfx_yaml("pew", category="sfx", duration=0.2, layers=[
        {"id": "tone", "osc": "pulse", "pitch": [[0, "C6"], [0.15, "C4"]], "slide": True, "env": [0.001, 0.05, 0.5, 0.05]}])  # fmt: skip
    sfx, findings = load(project, "sfx", "pew", text)
    assert sfx is not None, (findings, text)
    assert sfx.layers[0].slide and sfx.layers[0].pitch == ((0.0, 84.0), (0.15, 60.0))
