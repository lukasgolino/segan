from __future__ import annotations

from pathlib import Path

import pytest

from segan.findings import SeganError
from segan.lint import WARNING_RULES, lint_paths
from segan.project import Project, load_project

from conftest import CONFIG, make_project, write

from test_song import SONG


def lint_rules(project: Project, kind: str, name: str, text: str) -> list[tuple[str, str | None]]:
    path = write(project, kind, name, text)
    return [(f.rule, f.where) for f in lint_paths(project, [path]).findings]


def test_clean_assets_have_no_findings(project: Project) -> None:
    assert lint_rules(project, "sfx", "c", "name: c\npreset: blip\n") == []


def test_w001_too_peaky_for_the_target(project: Project) -> None:
    text = "name: x\nduration: 0.05\nlayers:\n  - { osc: noise, env: [0, 0.004, 0, 0.001] }\n"
    assert ("W001", "x") in lint_rules(project, "sfx", "x", text)


def test_w002_w004_unused_and_empty(project: Project) -> None:
    text = SONG.replace("  intro: [c]\n", "  intro: [c]\n  spare: [a]\n").replace(
        "  c: { from: a,", "  d:\n    length: 8\n  c: { from: a,"
    )
    found = lint_rules(project, "song", "tune", text)
    assert ("W002", "sections.spare") in found and ("W002", "patterns.d") in found and ("W004", "patterns.d") in found


def test_w003_too_many_instruments(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG + "\n[lint]\nmax_instruments = 3\n")
    assert ("W003", "patterns") in lint_rules(project, "song", "tune", SONG)


def test_w005_leading_silence(project: Project) -> None:
    text = "name: x\nlayers:\n  - { osc: sine, start: 0.05, pitch: A4, env: [0.001, 0.1, 0, 0.05] }\n"
    assert ("W005", "x") in lint_rules(project, "sfx", "x", text)


def test_w006_older_style(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG.replace('default_kit = "t"', 'default_kit = "t"\nstyle_version = 2'))
    assert ("W006", "style_version") in lint_rules(project, "sfx", "c", "name: c\npreset: blip\nstyle_version: 1\n")


def test_w007_loop_click(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG.replace("[mix]", "[mix]\ndeclick = false"))  # declick would fade the edges
    text = "name: x\nloop: true\ncrossfade: 0\nduration: 0.2\nlayers:\n  - { osc: sine, pitch: 441.3, env: [0, 0, 1, 0] }\n"
    assert ("W007", "loop") in lint_rules(project, "sfx", "x", text)
    smooth = text.replace("crossfade: 0", "crossfade: 0.05")
    assert ("W007", "loop") not in lint_rules(project, "sfx", "x", smooth)


def test_w008_dc_offset(project: Project) -> None:
    text = "name: x\nduration: 0.02\nlayers:\n  - { osc: sine, pitch: 20, env: [0, 0, 1, 0] }\n"  # half a cycle of 20 Hz
    assert ("W008", "x") in lint_rules(project, "sfx", "x", text)


def test_w009_clash(project: Project) -> None:
    text = SONG.replace("      b---|b---  C3", "      b---|b---  C3").replace("      ....|....  B3\n", "      ....|....  B3\n", 1)
    # put a bass B3 under the lead's C5 on step 1: a minor 9th (minor 2nd class)
    text = text.replace("      ....|....  B3\n      ....|....  A3\n      ....|....  G3\n      ....|....  F3\n      ....|....  E3\n      ....|....  D3\n      b---|b---  C3",
                        "      b---|....  B3\n      ....|....  A3\n      ....|....  G3\n      ....|....  F3\n      ....|....  E3\n      ....|....  D3\n      ....|b---  C3")
    assert ("W009", "patterns.a") in lint_rules(project, "song", "tune", text)


def test_w010_aliasing(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG.replace("[mix]", "[mix]\noversample = 1"))
    text = "name: x\nlayers:\n  - { id: hi, osc: saw, pitch: C8, env: [0, 0.1, 0.5, 0.05] }\n"
    assert ("W010", "hi") in lint_rules(project, "sfx", "x", text)


def test_w011_cut_off_tail(project: Project) -> None:
    text = "name: x\nduration: 0.1\nlayers:\n  - { id: long, osc: sine, pitch: A4, length: 0.09, env: [0.001, 0.1, 0.5, 0.5] }\n"
    assert ("W011", "duration (long)") in lint_rules(project, "sfx", "x", text)


def test_w012_held_past_the_end(project: Project) -> None:
    assert ("W012", "patterns.c.shift") in lint_rules(project, "song", "tune", SONG)


def test_w013_unnormalised_level(project: Project) -> None:
    text = "name: x\nnormalize: false\nlayers:\n  - { osc: sine, pitch: A4, gain: -40, env: [0.001, 0.1, 0.5, 0.1] }\n"
    assert ("W013", "x") in lint_rules(project, "sfx", "x", text)


def test_e012_duplicate_names(project: Project) -> None:
    write(project, "sfx", "tune", "name: tune\npreset: blip\n")
    write(project, "song", "tune", SONG)
    assert "E012" in [f.rule for f in lint_paths(project, render=False).findings]


def test_per_asset_and_project_disable(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG + '\n[lint]\ndisable = ["W012"]\n')
    assert "W012" not in [r for r, _ in lint_rules(project, "song", "tune", SONG)]
    project = make_project(tmp_path, CONFIG)
    found = lint_rules(project, "song", "tune", SONG.replace("tempo: 120", "tempo: 120\nlint: { disable: [W012] }"))
    assert "W012" not in [r for r, _ in found]


def test_kit_aliasing_warning(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG.replace("[mix]", "[mix]\noversample = 1"))
    (project.kits_dir / "hi.kit.yaml").write_text("name: hi\ninstruments:\n  p: { osc: saw, range: [C4, C8] }\n")
    assert ("W010", "instruments.p") in [(f.rule, f.where) for f in lint_paths(project, [project.kits_dir / "hi.kit.yaml"]).findings]


@pytest.mark.parametrize("rule", sorted(WARNING_RULES))
def test_every_warning_is_documented(rule: str) -> None:
    reference = (Path(__file__).parent.parent / "src" / "segan" / "skill" / "reference.md")
    if reference.exists():
        assert rule in reference.read_text()


CLASH = """\
name: clash
tempo: 120
key: C major
meter: {meter}
steps_per_beat: 1
tracks:
  lead: {{ roll: [C5, C5] }}
  bass: {{ roll: [B4, B4] }}
patterns:
  a:
    length: 6
    lead: |
      {lead}  C5
    bass: |
      {bass}  B4
sections:
  main: [a]
arrangement: [main]
"""


def test_w009_uses_the_felt_beat_in_compound_meters(project: Project) -> None:
    """#2: in 6/8 the beat is the dotted quarter (every 3 eighths), not every eighth."""
    off_beat = CLASH.format(meter="[6, 8]", lead=".p....", bass=".q....")  # together on eighth 2 only
    assert not [r for r in lint_rules(project, "song", "clash", off_beat) if r[0] in ("W009",) or r[0].startswith("E")]
    assert ("W009", "patterns.a") in lint_rules(project, "song", "clash", off_beat.replace("[6, 8]", "[6, 4]"))  # simple: every unit
    on_beat = CLASH.format(meter="[6, 8]", lead="...p..", bass="...q..")  # eighth 4 = the second dotted beat
    assert ("W009", "patterns.a") in lint_rules(project, "song", "clash", on_beat)


def test_w009_ignores_a_note_that_has_decayed(project: Project) -> None:
    """#2: a sustain-0 bell held for the whole bar no longer sounds when the other note comes in."""
    kit = (project.root / "kits" / "t.kit.yaml").read_text()
    (project.root / "kits" / "t.kit.yaml").write_text(kit.replace("groups:", "  e: { name: bell, osc: sine, env: [0.001, 0.2, 0, 0.1] }\ngroups:"))
    held = CLASH.format(meter="[3, 4]", lead="e-----", bass="...q..").replace("tempo: 120", "tempo: 60")  # 1 s per step
    assert not [r for r in lint_rules(project, "song", "clash", held) if r[0] in ("W009",) or r[0].startswith("E")]
    sustained = held.replace("e-----", "p-----")  # the lead's sustain (0.6) keeps it audible: still a clash
    assert ("W009", "patterns.a") in lint_rules(project, "song", "clash", sustained)


def test_w018_narrow_band_pass_noise(project: Project) -> None:
    """#7: noise through a narrow band-pass loses most of its level: say so (pitched waves through a band-pass don't count)."""
    text = "name: w\nduration: 0.5\nlayers:\n  - { id: whistle, osc: noise, filter: { type: bp, cutoff: 2000, resonance: 0.95 }, env: [0.01, 0.1, 0.8, 0.1] }\n"
    assert ("W018", "whistle") in lint_rules(project, "sfx", "w", text)
    assert ("W018", "whistle") not in lint_rules(project, "sfx", "w", text.replace("osc: noise", "osc: saw, pitch: D3"))
    assert ("W018", "whistle") not in lint_rules(project, "sfx", "w", text.replace("resonance: 0.95", "resonance: 0"))


def test_category_lint_disable(tmp_path: Path) -> None:
    """#19: `[lint.<category>] disable` turns warnings off for every asset of that category only."""
    text = "name: x\ncategory: {category}\nduration: 0.02\nlayers:\n  - {{ osc: sine, pitch: 20, env: [0, 0, 1, 0] }}\n"  # W008
    project = make_project(tmp_path, CONFIG + '\n[lint.quiet_sfx]\ndisable = ["W008"]\n')
    assert ("W008", "x") not in lint_rules(project, "sfx", "x", text.format(category="quiet_sfx"))
    assert ("W008", "x") in lint_rules(project, "sfx", "x", text.format(category="sfx"))
    (tmp_path / "bad").mkdir()
    with pytest.raises(SeganError, match=r"lint\.loud"):  # only `disable` can differ per category
        make_project(tmp_path / "bad", CONFIG + '\n[lint.loud]\nmax_instruments = 3\n')


def test_w019_long_loop_offset(project: Project) -> None:
    """#25: a looping song whose last notes ring for bars makes a much longer file: W019, fixed by `max_ring`."""
    kit = (project.root / "kits" / "t.kit.yaml").read_text()
    ring = "  r: {{ name: gong, osc: sine, env: [0, 0, 1, 12], voices: 4{extra} }}\ngroups:"  # voices: the next pass doesn't cut it
    song = ("name: g\ntempo: 240\ntracks:\n  lead: { roll: [C5, C5] }\npatterns:\n  a:\n    length: 16\n    lead: |\n"
            "      r...............  C5\nsections:\n  main: [a, a, a, a]\narrangement: [main]\nloop: main\n")  # fmt: skip
    (project.root / "kits" / "t.kit.yaml").write_text(kit.replace("groups:", ring.format(extra="")))
    assert ("W019", "loop") in lint_rules(project, "song", "g", song)
    (project.root / "kits" / "t.kit.yaml").write_text(kit.replace("groups:", ring.format(extra=", max_ring: 0.5")))
    assert ("W019", "loop") not in lint_rules(load_project(project.root), "song", "g", song)  # a fresh project reloads the kit
