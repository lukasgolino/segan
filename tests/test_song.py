from __future__ import annotations

import numpy as np
import pytest

from segan.analysis import seam_click
from segan.project import Project
from segan.render import render_asset
from segan.sequence import build_timeline, placed_notes
from segan.wavio import read_wav

from conftest import load

SONG = """\
name: tune
tempo: 120
key: C major
tracks:
  lead: { roll: [C5, C6] }
  bass: { roll: [C3, C4], gain: -2 }
  drums: { drums: [k, s, h] }
patterns:
  a:
    length: 8
    lead: |
      ....|....  C6
      ....|....  B5
      ....|..p-  A5
      ....|....  G5
      ..p-|....  F5
      ....|p-..  E5
      ....|....  D5
      p-..|....  C5
    bass: |
      ....|....  C4
      ....|....  B3
      ....|....  A3
      ....|....  G3
      ....|....  F3
      ....|....  E3
      ....|....  D3
      b---|b---  C3
    drums: |
      x...|x...  k
      ..X.|..o.  s
      xxxx|xxxx  h
  b: { from: a, transpose: { lead: 1 } }
  c: { from: a, mute: [lead, drums], shift: 1 }
sections:
  intro: [c]
  main: [a, b]
arrangement: [intro, main]
loop: main
markers:
  top: [main, 1]
variants:
  fast: { tempo: 150, instrument_swap: { p: q } }
  other: { kit: u }
  minor: { key: C minor }
"""


def test_song_parses(project: Project) -> None:
    song, findings = load(project, "song", "tune", SONG)
    assert song is not None, findings
    assert [(f.rule, f.where) for f in findings] == [("W012", "patterns.c.shift")]  # the shifted bass note is cut at the end
    assert song.tracks["lead"].rows[0] == 84 and len(song.tracks["lead"].rows) == 8
    a = song.patterns["a"]
    lead = sorted((n.step, n.length, song.tracks["lead"].rows[n.row]) for n in a.notes if n.track == "lead")
    assert lead == [(0, 2, 72), (2, 2, 77), (4, 2, 76), (6, 2, 81)]
    b = song.patterns["b"]
    assert sorted(song.tracks["lead"].rows[n.row] for n in b.notes if n.track == "lead") == [74, 77, 79, 83]
    c = song.patterns["c"]
    assert not [n for n in c.notes if n.track == "lead"] and min(n.step for n in c.notes) == 1
    snare = [n for n in a.notes if n.key == "s"]
    assert [n.velocity for n in snare] == [1.5, 0.35]


def test_timeline_and_loop(project: Project) -> None:
    song, _ = load(project, "song", "tune", SONG)
    timeline = build_timeline(song)
    assert timeline.total == 24 and timeline.loop == (8, 24) and timeline.markers == {"top": 8}
    assert abs(timeline.seconds(4) - 0.5) < 1e-12
    placed = placed_notes(song, timeline)
    assert min(p.step for p in placed if p.note.track == "lead") == 8


def test_song_render_loops_seamlessly(project: Project) -> None:
    song, _ = load(project, "song", "tune", SONG)
    render = render_asset(song, project)
    main = render.main
    assert main.channels == 2 and main.loop is not None
    start, end = main.loop
    assert end == main.frames
    bar = round(2.0 * 22050)  # one 4/4 bar at 120 bpm
    assert start == round(1.0 * 22050) + bar and end - start == round(2.0 * 22050)
    assert seam_click(main.audio, start, end) < 0.02
    assert main.cues == [("top", 22050)]
    wav = read_wav(main.wav())
    assert wav.loop == main.loop and wav.cues == main.cues
    assert [o.id for o in render.outputs] == ["", "variant:fast", "variant:other", "variant:minor"]
    fast = render.output("variant:fast")
    assert fast.loop is not None and fast.loop[1] - fast.loop[0] < end - start


def test_variant_axes(project: Project) -> None:
    text = SONG.replace("variants:", "variant_axes:\n  mood: { calm: { tempo: 100 }, tense: { tempo: 140 } }\n  colour: { warm: { kit: u }, cold: { semitones: -2 } }\nvariants:")
    song, findings = load(project, "song", "tune", text)
    assert song is not None, findings
    assert {"calm+warm", "calm+cold", "tense+warm", "tense+cold", "fast"} <= set(song.all_variants())
    combo = song.all_variants()["tense+cold"]
    assert combo.tempo == 140 and combo.semitones == -2


def test_stems_add_up_to_the_mix(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from conftest import CONFIG, make_project

    project = make_project(tmp_path, CONFIG.replace('default_kit = "t"', 'default_kit = "t"\nexport = ["wav", "stems"]'))
    song, _ = load(project, "song", "tune", SONG)
    render = render_asset(song, project)
    stems = [o for o in render.outputs if o.id.startswith("stem:")]
    assert [o.id for o in stems] == ["stem:lead", "stem:bass", "stem:drums"]
    total = np.sum([o.audio for o in stems], axis=0)
    main = render.main.audio
    assert all(o.frames == render.main.frames and o.loop == render.main.loop for o in stems)
    assert float(np.max(np.abs(total - main))) < 0.002


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (("      ....|....  C6\n", ""), "E003"),  # a missing row
        (("p-..|....  C5", "p-..|.....  C5"), "E003"),  # a row too long
        (("p-..|....  C5", "p-..|....  D5"), "E011"),  # wrong label
        (("p-..|....  C5", "z-..|....  C5"), "E002"),  # unknown key
        (("..X.|..o.  s", "..X.|..q.  s"), "E002"),  # bad drum mark
        (("p-..|....  C5", "-p..|....  C5"), "E015"),  # hold without a note
        (("main: [a, b]", "main: [a, nope]"), "E004"),
        (("arrangement: [intro, main]", "arrangement: [intro, outro]"), "E004"),
        (("loop: main", "loop: outro"), "E008"),
        (("top: [main, 1]", "top: [main, 9]"), "E004"),
        (("b: { from: a, transpose: { lead: 1 } }", "b: { from: zz }"), "E010"),
        (("b: { from: a, transpose: { lead: 1 } }", "b: { from: b }"), "E010"),
        (("b: { from: a, transpose: { lead: 1 } }", "b: { from: a, transpose: { lead: 5 } }"), "E010"),
        (("b: { from: a, transpose: { lead: 1 } }", "b: { from: a, shift: 7 }"), "E010"),
        (("fast: { tempo: 150, instrument_swap: { p: q } }", "fast: { instrument_swap: { p: z } }"), "E006"),
        (("fast: { tempo: 150, instrument_swap: { p: q } }", "fast: { group_swap: { leads: nope } }"), "E006"),
        (("b---|b---  C3", "p---|b---  C3"), "E007"),  # p's range is C4-C6
        (("other: { kit: u }", "other: { semitones: 24 }"), "E007"),
        (("      ..p-|....  F5", "      p-p-|....  F5"), "E014"),  # p has voices: 1 and C5 sounds too
        (("tempo: 120", "tempo: 1000"), "E001"),
        (("key: C major", "key: C weird"), "E001"),
        (("tracks:", "trax: 1\ntracks:"), "E001"),
    ],
)
def test_song_errors(project: Project, change: tuple[str, str], rule: str) -> None:
    old, new = change
    assert old in SONG
    song, findings = load(project, "song", "tune", SONG.replace(old, new, 1))
    assert song is None and rule in [f.rule for f in findings], [(f.rule, f.message) for f in findings]


def test_row_errors_point_at_the_row(project: Project) -> None:
    _, findings = load(project, "song", "tune", SONG.replace("p-..|....  C5", "p-..|....  D5"))
    e011 = [f for f in findings if f.rule == "E011"][0]
    assert e011.line == SONG.split("\n").index("      p-..|....  C5") + 1 and e011.where == "patterns.a.lead row 8"


def test_open_mode_song(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from conftest import make_project

    project = make_project(tmp_path, 'mode = "open"\n')
    text = "name: s\ninstruments:\n  z: { osc: sine }\ntracks:\n  t: { roll: [C4, C5] }\npatterns:\n  a:\n    length: 4\n    t: |\n" + \
        "".join(f"      {'z---' if i == 7 else '....'}\n" for i in range(8)) + "sections: { main: [a] }\narrangement: [main]\n"
    song, findings = load(project, "song", "s", text)
    assert song is not None, findings


SPARSE = """\
name: sparse
tempo: 120
tracks:
  lead: { roll: [C5, D5] }
patterns:
  a:
    length: 16
    lead: |
      ....|....|....|....  D5
      p...|....|....|....  C5
sections:
  main: [a, a]
arrangement: [main]
loop: main
"""


def test_sparse_looping_song_renders_to_the_loop_end(project: Project) -> None:
    song, findings = load(project, "song", "sparse", SPARSE)
    assert song is not None, findings
    main = render_asset(song, project).main
    assert main.loop is not None and main.loop[1] == main.frames
    assert read_wav(main.wav()).loop == main.loop


GROUPED = SONG.replace("variants:", """stems:
  groups: { base: [bass, drums], top: [lead] }
  mixes: { calm: [base], full: [base, top] }
variants:""")


def test_stem_groups_and_mixes(project: Project) -> None:
    from segan.analysis import integrated_lufs

    song, findings = load(project, "song", "tune", GROUPED)
    assert song is not None, findings
    render = render_asset(song, project)  # a stems: block renders stems without "stems" in export
    ids = [o.id for o in render.outputs if o.id.startswith(("stem:", "mix:"))]
    assert ids == ["stem:base", "stem:top", "mix:calm", "mix:full"]
    base, top, full = render.output("stem:base"), render.output("stem:top"), render.output("mix:full")
    assert base.info["tracks"] == ["bass", "drums"] and base.info["loop_offset"] == render.main.info["loop_offset"]
    assert float(np.max(np.abs(base.audio + top.audio - full.audio))) < 0.002
    assert abs(integrated_lufs(full.audio, full.rate) + 16.0) < 0.5  # the loudest mix is on target
    assert render.main.info["mixes"]["calm"] < render.main.info["mixes"]["full"]


@pytest.mark.parametrize(
    ("stems", "message"),
    [
        ("{ groups: { base: [bass, drums] } }", "no stem group"),
        ("{ groups: { a: [lead, z*], b: [bass, drums] } }", "matches no track"),
        ("{ groups: { a: [lead, bass], b: [bass, drums] } }", "is in stem groups"),
        ("{ mixes: { calm: [lead, nope] } }", "unknown stem"),
        ("{ main_mix: maybe }", "main_mix"),
        ("{ grups: {} }", "stems must be"),
    ],
)
def test_stem_errors(project: Project, stems: str, message: str) -> None:
    song, findings = load(project, "song", "tune", SONG.replace("variants:", f"stems: {stems}\nvariants:"))
    assert song is None and any(f.rule == "E016" and message in f.message for f in findings), findings
