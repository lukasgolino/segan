"""Long-form music: section changes, flow (section graphs and their clips) and soundtracks."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import load, make_project, rules, write

from segan.build import build
from segan.findings import Finding
from segan.flowrender import _bus, flow_sections, walk, walk_audio
from segan.lint import lint_paths
from segan.notes import Key, parse_key
from segan.preview import write_preview
from segan.project import Project, load_project
from segan.render import render_asset
from segan.sequence import build_timeline, placed_notes
from segan.soundtrack import keys_clash

PATTERNS = """\
tempo: 133
key: A minor
tracks:
  lead: { roll: [A4, A5] }
  bass: { roll: [E2, E3] }
  drums: { drums: [k, s, h] }
patterns:
  a:
    length: 16
    lead: |
      ................  A5
      ................  G5
      ................  F5
      ........p-------  E5
      ................  D5
      ....p---........  C5
      ................  B4
      p---............  A4
    bass: |
      ................  E3
      ................  D3
      ................  C3
      ................  B2
      b---b---b---b---  A2
      ................  G2
      ................  F2
      ................  E2
    drums: |
      x.......x.......  k
      ....x.......x...  s
      x.x.x.x.x.x.x.x.  h
"""

FLOW_SONG = "name: f\n" + PATTERNS + """\
sections:
  intro: { patterns: [a], mute: [lead] }
  verse: [a, a]
  up: { from: verse, semitones: 2, velocity: 0.8 }
  outro: { patterns: [a], mute: [drums] }
arrangement: [intro, verse, up]
flow:
  start: intro
  next: { intro: [verse], verse: { up: 2, verse: 1 }, up: [verse] }
  end: outro
"""


def song_with(project: Project, sections: str, extra: str = "", name: str = "s") -> tuple[Any, list[Finding]]:
    return load(project, "song", name, f"name: {name}\n" + PATTERNS + sections + extra)


# --- section changes -----------------------------------------------------------------------------


def test_section_changes_apply_at_play_time(project: Project) -> None:
    song, findings = song_with(project, "sections:\n  verse: [a]\n  up: { from: verse, semitones: 2, velocity: 0.5, mute: [drums] }\narrangement: [verse, up]\n")
    assert song is not None, findings
    timeline = build_timeline(song)
    placed = placed_notes(song, timeline)
    first = [p for p in placed if p.step < 16]
    second = [p for p in placed if p.step >= 16]
    assert not any(p.note.track == "drums" for p in second)
    lead1 = sorted(p.midi for p in first if p.note.track == "lead")
    lead2 = sorted(p.midi for p in second if p.note.track == "lead")
    assert lead2 == [m + 2 for m in lead1]  # off the roll's rows: fine at play time
    assert all(p.note.velocity == 0.5 for p in second)


def test_section_key_and_swap(project: Project) -> None:
    song, findings = song_with(project, "sections:\n  verse: [a]\n  major: { patterns: [a], key: A major, instrument_swap: { p: q } }\narrangement: [verse, major]\n")
    assert song is not None, findings
    second = [p for p in placed_notes(song, build_timeline(song)) if p.step >= 16 and p.note.track == "lead"]
    assert {p.key for p in second} == {"q"}
    assert 73 in {int(p.midi) for p in second}  # C5 -> C#5 in A major


@pytest.mark.parametrize(("sections", "rule"), [
    ("sections:\n  verse: { patterns: [a], from: verse }\n", "E004"),
    ("sections:\n  verse: { pattern: [a] }\n", "E004"),
    ("sections:\n  x: { from: y }\n  y: { from: x }\n", "E004"),
    ("sections:\n  verse: { patterns: [a], mute: [nope] }\n", "E004"),
    ("sections:\n  verse: { patterns: [a], velocity: 3 }\n", "E004"),
    ("sections:\n  verse: { patterns: [a], semitones: 24 }\n", "E007"),
])  # fmt: skip
def test_section_change_errors(project: Project, sections: str, rule: str) -> None:
    first = sections.splitlines()[1].split(":")[0].strip()
    song, findings = song_with(project, f"{sections}arrangement: [{first}]\n")
    assert song is None and rule in rules(findings), findings


def test_template_and_flow_sections_are_not_unused(project: Project) -> None:
    write(project, "song", "f", FLOW_SONG.replace("  verse: [a, a]\n", "  base: [a, a]\n  verse: { from: base }\n"))
    found = lint_paths(project, render=False).findings
    assert "W002" not in rules(found), found


# --- flow ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("flow", "needle"), [
    ("{ start: nope, next: { verse: [verse] } }", "unknown section"),
    ("{ start: intro, next: { intro: [verse], verse: { up: 0 } } }", "weight"),
    ("{ start: intro, next: { intro: [verse] } }", "no next section"),
    ("{ start: intro, next: { intro: [intro], verse: [intro] } }", "can't be reached"),
    ("{ start: intro, next: { intro: [verse], verse: [intro] }, end: verse }", "can't have next"),
    ("{ start: intro, next: { intro: [verse], verse: [intro] }, variants: [nope] }", "unknown variant"),
    ("{ start: intro, next: { intro: [verse], verse: [intro] }, wat: 1 }", "flow must be"),
])  # fmt: skip
def test_flow_errors(project: Project, flow: str, needle: str) -> None:
    song, findings = song_with(project, "sections:\n  intro: [a]\n  verse: [a, a]\n  up: [a]\narrangement: [intro, verse]\n", f"flow: {flow}\n")
    assert song is None
    assert any(f.rule == "E017" and needle in f.message for f in findings), findings


def test_flow_sections_must_be_whole_bars(project: Project) -> None:
    text = "name: s\n" + PATTERNS + "  half:\n    length: 8\n    drums: |\n      x.......  k\n      ........  s\n      x.x.x.x.  h\n"
    song, findings = load(project, "song", "s", text + "sections:\n  a1: [a]\n  h: [half]\narrangement: [a1]\nflow: { start: a1, next: { a1: [h], h: [a1] } }\n")
    assert song is None and any(f.rule == "E017" and "whole bars" in f.message for f in findings), findings


def test_walk_of_clips_equals_a_linear_render_of_the_path(project: Project) -> None:
    song, findings = load(project, "song", "f", FLOW_SONG)
    assert song is not None, findings
    render = render_asset(song, project)
    path = walk(song, 3, 30.0)
    assert path[0] == "intro" and path[-1] == "outro" and len(path) > 5
    assert all(not (a == b == "verse") for a, b in zip(path, path[1:], strict=False))  # no_repeat: verse has another way on
    audio, starts = walk_audio(render.outputs, None, path)
    sections, _ = flow_sections(song, project, None)
    events, at = [], 0
    for name in path:
        events += [replace(e, start=e.start + at) for e in sections[name].events]
        at += sections[name].length
    assert [s for _, s in starts] == list(np.cumsum([0] + [sections[n].length for n in path[:-1]]))
    reference = _bus(events, len(audio), project, song, float(render.main.level["gain_db"] or 0.0))
    assert np.abs(reference - audio).max() < 1e-3  # 16-bit rounding, the tail trim and the limiter at clip edges


def test_flow_clips_and_manifest(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write(project, "song", "f", FLOW_SONG)
    result = build(project)
    assert not result.errors, result.errors
    manifest = json.loads((project.output_dir / "manifest.json").read_text())
    flow = manifest["assets"]["f"]["flow"]
    assert flow["start"] == ["intro"] and flow["end"] == "outro" and flow["next"]["verse"] == {"up": 2.0, "verse": 1.0}
    verse = flow["sections"]["verse"]
    assert set(verse["from"]) == {"intro", "verse", "up"} and verse["head_samples"] < verse["samples"]
    assert flow["sections"]["intro"]["rest"] is None  # one bar: all head
    assert set(flow["sections"]["outro"]["from"]) == {"intro", "verse", "up"}  # the ending follows anything
    for clip in [verse["head"], verse["rest"], verse["tail"], *verse["from"].values()]:
        assert (project.output_dir / clip).is_file()
    assert manifest["soundtracks"] == {}
    assert not (project.output_dir / "segan_music.gd").exists()  # only with the Godot export


def test_short_section_after_a_long_ring_warns(tmp_path: Path) -> None:
    config = (Path(__file__).parent / "conftest.py").read_text().split('CONFIG = """\\\n')[1].split('"""')[0].replace("room_decay = 0.2", "room_decay = 3.0")
    project = make_project(tmp_path, config)
    song = FLOW_SONG.replace("  outro: { patterns: [a], mute: [drums] }\n", "  outro: { patterns: [a], mute: [drums] }\n  short: [a]\n")
    song = song.replace("up: [verse] }", "up: [short], short: [verse] }")
    write(project, "song", "f", song)
    found = lint_paths(project).findings
    assert "W015" in rules(found), found


def test_preview_walk(project: Project) -> None:
    song, _ = load(project, "song", "f", FLOW_SONG)
    result = write_preview(song, render_asset(song, project), project, only=["walk:2"])
    [entry] = result.files
    assert entry["wav"].is_file() and entry["sheet"].is_file()
    assert entry["analysis"]["walk"][0] == "intro" and entry["analysis"]["join_error"] < 1e-3


# --- soundtracks ---------------------------------------------------------------------------------

SOUNDTRACK = """\
name: main
start: calm
states:
  calm: { songs: [f], play: 30, gap: [1, 2] }
  tense: { songs: { g: 2, f.night: 1 } }
transitions:
  "*": { at: bar, fade: 1 }
  calm>tense: { at: beat, fade: 0.5, stinger: hit, start: verse }
"""

G_SONG = "name: g\n" + PATTERNS + "sections:\n  verse: [a]\narrangement: [verse]\nloop: verse\n"


def soundtrack_project(tmp_path: Path, text: str = SOUNDTRACK, g: str = G_SONG) -> Project:
    project = make_project(tmp_path)
    write(project, "song", "f", FLOW_SONG + "variants:\n  night: { semitones: -2 }\n")
    write(project, "song", "g", g)
    write(project, "sfx", "hit", "name: hit\npreset: hit\n")
    (project.music_dir / "main.soundtrack.yaml").write_text(text)
    return project


def test_soundtrack_lints_and_lands_in_the_manifest(tmp_path: Path) -> None:
    project = soundtrack_project(tmp_path)
    result = lint_paths(project, render=False)
    assert not result.errors, result.errors
    [st] = result.soundtracks
    assert st.transition("calm", "tense").stinger == "hit"
    assert st.transition("tense", "calm").fade == 1.0  # "*"
    assert st.states["tense"].play == (120.0, 240.0)  # default for a pool of songs
    built = build(project)
    assert not built.errors
    entry = json.loads((project.output_dir / "manifest.json").read_text())["soundtracks"]["main"]
    assert entry["states"]["tense"]["songs"][1] == {"song": "f", "variant": "night", "weight": 1.0, "family": "f.night"}  # its own family
    assert entry["states"]["calm"]["crossfade"] == 0.0 and entry["families"] == {}
    assert entry["transitions"]["calm>tense"]["start"] == "verse"


POOL = """\
name: main
states:
  calm: { songs: [f, g, f.night], play: 60, gap: 30, crossfade: 2 }
families:
  a_minor: [f, g]
"""


def test_families_and_crossfade(tmp_path: Path) -> None:
    project = soundtrack_project(tmp_path, POOL)
    result = lint_paths(project, render=False)
    assert not result.errors and "W016" not in rules(result.findings), result.findings
    [st] = result.soundtracks
    assert [st.family(r) for r in st.states["calm"].songs] == ["a_minor", "a_minor", "f.night"]  # `f` is the main version only
    built = build(project)
    assert not built.errors
    entry = json.loads((project.output_dir / "manifest.json").read_text())["soundtracks"]["main"]
    assert entry["families"] == {"a_minor": ["f", "g"]} and entry["states"]["calm"]["crossfade"] == 2.0


def test_crossfade_in_a_family_of_clashing_keys_warns(tmp_path: Path) -> None:
    project = soundtrack_project(tmp_path, POOL.replace("[f, g]", "[g, f.night]"))
    found = [f for f in lint_paths(project, render=False).findings if f.rule == "W016"]
    assert found and "g (A minor) and f.night (G minor)" in found[0].message, found


@pytest.mark.parametrize(("text", "needle"), [
    (POOL.replace("[f, g]", "[f, nope]"), "no song 'nope'"),
    (POOL.replace("[f, g]", "[f, g.day]"), "no song 'g.day'"),
    (POOL + "  other: [g]\n", "already in family"),
    (POOL.replace("crossfade: 2", "crossfade: -1"), "crossfade must be"),
    (POOL.replace("a_minor: [f, g]", "a_minor: f"), "must list songs"),
])  # fmt: skip
def test_family_errors(tmp_path: Path, text: str, needle: str) -> None:
    found = lint_paths(soundtrack_project(tmp_path, text), render=False).findings
    assert any(f.rule == "E018" and needle in f.message for f in found), found


def test_one_song_without_gap_plays_forever(tmp_path: Path) -> None:
    project = soundtrack_project(tmp_path, "name: main\nstates:\n  menu: [g]\n")
    [st] = lint_paths(project, render=False).soundtracks
    assert st.states["menu"].play is None and st.start == "menu"


@pytest.mark.parametrize(("text", "needle"), [
    (SOUNDTRACK.replace("songs: [f]", "songs: [nope]"), "no song 'nope'"),
    (SOUNDTRACK.replace("f.night", "f.day"), "no variant 'day'"),
    (SOUNDTRACK.replace("stinger: hit", "stinger: boom"), "isn't an SFX"),
    (SOUNDTRACK.replace("start: verse", "start: bridge"), "isn't played by"),
    (SOUNDTRACK.replace("at: beat", "at: soon"), "at must be"),
    (SOUNDTRACK.replace("calm>tense", "calm>war"), "with state names"),
    (SOUNDTRACK.replace("start: calm", "start: war"), "start must be"),
    (SOUNDTRACK.replace("play: 30", "play: 0"), "play must be"),
])  # fmt: skip
def test_soundtrack_errors(tmp_path: Path, text: str, needle: str) -> None:
    project = soundtrack_project(tmp_path, text)
    found = lint_paths(project, render=False).findings
    assert any(f.rule == "E018" and needle in f.message for f in found), found


def test_cross_fade_between_clashing_keys_warns(tmp_path: Path) -> None:
    found = lint_paths(soundtrack_project(tmp_path), render=False).findings
    clashes = [f for f in found if f.rule == "W016"]
    assert clashes and all("f.night (G minor)" in f.message for f in clashes), found  # A minor -> G minor; g is in A minor too
    project = soundtrack_project(tmp_path, SOUNDTRACK.replace("{ g: 2, f.night: 1 }", "[g]"))
    assert "W016" not in rules(lint_paths(project, render=False).findings)


def test_key_clash() -> None:
    def k(text: str) -> Key:
        key = parse_key(text)
        assert key is not None
        return key

    assert not keys_clash(k("A minor"), k("C major"))  # relative
    assert not keys_clash(k("C major"), k("G major"))  # a fifth apart
    assert keys_clash(k("C major"), k("F# major"))


def test_director_is_written_for_godot_and_removed_when_unused(tmp_path: Path) -> None:
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text("config_version=5\n")
    (tmp_path / "src").mkdir()
    project = soundtrack_project(tmp_path / "src")
    config = project.config_path
    assert config is not None
    config.write_text(config.read_text().replace('mode = "strict"', 'mode = "strict"\noutput_dir = "../game/audio"\nexport = ["wav", "godot"]'))
    project = load_project(project.root)
    assert not build(project).errors
    director = tmp_path / "game" / "audio" / "segan_music.gd"
    assert director.is_file() and "func play_soundtrack" in director.read_text()
    (project.music_dir / "main.soundtrack.yaml").unlink()
    (project.music_dir / "f.song.yaml").write_text(G_SONG.replace("name: g", "name: f"))
    assert not build(load_project(project.root)).errors
    assert not director.exists()
