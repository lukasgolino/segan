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


def test_dedupe_derive_and_comments(project: Project) -> None:
    """#11: identical patterns collapse, a variation of a pattern is written as a derived pattern, and comments."""
    key = "C major"
    lead = api.Track.roll("lead", key, "C5", "C6")
    drums = api.Track.drums("drums", ["k", "h"])

    def bar(start: str, lead_on: bool = True) -> api.Pattern:
        p = api.Pattern(8)
        if lead_on:
            p.note(lead, 0, start, 2, "p").note(lead, 4, "G5", 2, "p")
        return p.row(drums, "k", "x...x...")

    a, again, up, quiet = bar("C5"), bar("C5"), bar("D5"), bar("C5", lead_on=False)
    up.notes["lead"] = [(r - 1, s, n, c) for r, s, n, c in a.notes["lead"]]  # every lead note a scale step up
    patterns, sections = api.dedupe({"a": a, "a2": again, "up": up}, {"main": ["a", "a2", "up"]})
    assert list(patterns) == ["a", "up"] and sections == {"main": ["a", "a", "up"]}
    assert api.derive("a", a, up, [lead, drums]) == {"from": "a", "transpose": {"lead": 1}}
    assert api.derive("a", a, quiet, [lead, drums]) == {"from": "a", "mute": ["lead"]}
    late = api.Pattern(8).note(lead, 1, "C5", 2, "p").note(lead, 5, "G5", 2, "p").row(drums, "k", ".x...x..")
    assert api.derive("a", a, late, [lead, drums]) == {"from": "a", "shift": 1}
    assert api.derive("a", a, api.Pattern(8).note(lead, 3, "E5"), [lead, drums]) is None
    text = api.song_yaml("gen", tracks=[lead, drums], patterns={"a": a, "up": api.derive("a", a, up, [lead, drums]) or up},
                         sections=sections, arrangement=["main"], key=key, kit="t",
                         comments={"patterns.up": "the hook, a step higher", "sections": "one bar each\nthen again"})  # fmt: skip
    assert "  # the hook, a step higher\n  up:" in text and "# one bar each\n# then again\nsections:" in text
    song, findings = load(project, "song", "gen", text)
    assert song is not None, (findings, text)
    ups = sorted((n.step, song.tracks["lead"].rows[n.row]) for n in song.patterns["up"].notes if n.track == "lead")
    assert ups == [(0, 74), (4, 81)]  # D5 and A5: the derived pattern sounds like the built one
    assert "# the hook\nlayers:" in api.sfx_yaml("x", layers=[{"osc": "sine"}], comments={"layers": "the hook"})


def test_velocities_voicings_and_rng(project: Project) -> None:
    lead = api.Track.roll("lead", "A minor", "A4", "A5")
    p = api.Pattern(8).note(lead, 0, "A4", 2, "p", velocity=1.5).note(lead, 4, "C5", 2, "p", velocity=0.3)
    text = api.song_yaml("v", tracks=[lead], patterns={"a": p}, sections={"main": ["a"]}, arrangement=["main"], key="A minor")
    assert 'velocity: { lead: "X...|o..." }' in text
    song, findings = load(project, "song", "v", text)
    assert song is not None, findings
    assert sorted(n.velocity for n in song.patterns["a"].notes) == [0.35, 1.5]
    plain = api.Pattern(8).note(lead, 0, "A4", 2, "p").note(lead, 4, "C5", 2, "p")
    kept, _ = api.dedupe({"a": p, "b": plain}, {"m": ["a", "b"]})
    assert set(kept) == {"a", "b"} and api.derive("a", p, plain, [lead]) is None
    assert api.invert([57, 60, 64], 1) == [60, 64, 69] and api.invert([57, 60, 64], -1) == [52, 57, 60]
    assert api.voicing([57, 60, 64], spread="open") == [48, 57, 64] and api.voicing([57, 60, 64], bass=True)[0] == 45
    a, b = api.Rng(3, "verse"), api.Rng(3, "verse")
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)] and a.choice([1, 2, 3]) in (1, 2, 3)


def test_song_yaml_passes_any_song_field(project: Project) -> None:
    """#74: stems, lint, category, status... go in as keywords."""
    lead = api.Track.roll("lead", "A minor", "A4", "A5")
    drums = api.Track.drums("drums", ["k", "h"])
    p = api.Pattern(8).note(lead, 0, "A4", 4, "p").row(drums, "k", "x...x...")
    text = api.song_yaml("s", tracks=[lead, drums], patterns={"a": p}, sections={"main": ["a"]}, arrangement=["main"], key="A minor",
                         category="music_soft", status="draft", lint={"disable": ["W009"]},
                         stems={"groups": {"base": ["drums"], "top": ["lead"]}, "mixes": {"calm": ["base", "top"]}})  # fmt: skip
    song, findings = load(project, "song", "s", text)
    assert song is not None, findings
    assert song.category == "music_soft" and song.stems is not None and dict(song.stems.mixes) == {"calm": ("base", "top")}
    assert "W009" in song.meta.lint_disable
