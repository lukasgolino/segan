"""#76 sameness checks: fingerprints, W021-W026, `segan similarity`, shipped and local fingerprint stores."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from segan import api, similarity
from segan.lint import lint_paths
from segan.project import Project, load_project

from conftest import CONFIG, rules, run_json
from conftest import make_project as _make_project


def make_project(root: Path, config: str = CONFIG) -> Project:
    root.mkdir(parents=True, exist_ok=True)
    return _make_project(root, config)

ROOT = Path(__file__).resolve().parent.parent
KIT = """\
name: ship
instruments:
  a: { name: pad, osc: saw, unison: 3, detune: 14, filter: { type: lp, cutoff: 950 }, env: [0.4, 0.5, 0.85, 0.5], voices: 5 }
  l: { name: arp, osc: pulse, duty: 0.3, env: [0.004, 0.35, 0.0, 0.2], voices: 2 }
  m: { name: sub, osc: triangle, env: [0.03, 0.3, 0.9, 0.35] }
  g: { name: pluck, osc: pluck, voices: 4 }
  k: { name: kick, drum: kick }
  h: { name: hat, drum: hat }
"""


def song(name: str, key: str = "D minor", tempo: float = 66, chords: tuple[int, ...] = (50, 46, 48, 45), keys: str = "alm", busy: bool = False,
         kit: str = "ship") -> str:  # fmt: skip
    pad = api.Track.roll("pad", key, "A2", "C5", chromatic=True)
    arp = api.Track.roll("arp", key, "A2", "C6", chromatic=True)
    bass = api.Track.roll("bass", key, "A1", "C3", chromatic=True)
    drums = api.Track.drums("drums", ["k", "h"])
    patterns = {}
    for i, root in enumerate(chords):
        p = api.Pattern(16)
        for m in (root, root + 7, root + 15):
            p.note(pad, 0, m, 16, keys[0])
        for step, midi, length in api.arpeggiate([root + 12, root + 19, root + 24], 16, rate=2 if busy else 4):
            p.note(arp, step, midi, length, keys[1])
        p.note(bass, 0, root - 12, 4, keys[2]).note(bass, 8, root - 12, 4, keys[2])
        if busy:
            p.row(drums, "k", "x...x...x...x...").row(drums, "h", "..x...x...x...x.")
        patterns[f"p{i}"] = p
    return api.song_yaml(name, kit=kit, key=key, tempo=tempo, tracks=[pad, arp, bass, drums], patterns=patterns, sections={"main": list(patterns)},
                         arrangement=["main"], loop="main")  # fmt: skip


@pytest.fixture
def ship(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    monkeypatch.setenv("SEGAN_FINGERPRINTS", str(tmp_path / "store"))
    project = make_project(tmp_path / "game")
    (project.kits_dir / "ship.kit.yaml").write_text(KIT)
    return project


def lint_music(project: Project) -> list[Any]:
    return lint_paths(load_project(project.root), [project.music_dir], render=False).findings


def test_fingerprint_reads_the_opening_harmony_and_rhythm(ship: Project) -> None:
    (ship.music_dir / "a.song.yaml").write_text(song("a"))
    from segan.asset import load_asset

    loaded, _ = load_asset(ship.music_dir / "a.song.yaml", ship)
    fp = similarity.fingerprint(loaded)
    assert fp.opening == [38, 50, 57, 62, 65]  # bass D2, pad D3 A3 F4, arp D4
    assert fp.pitch_set == [0, 2, 4, 5, 7, 9, 10] and fp.kit == "ship" and fp.tempo == 66
    assert abs(sum(fp.chroma[0]) - 1.0) < 1e-3 and fp.chroma[0][2] > 0.3  # bar 1 is mostly D
    assert fp.onsets[0][0] == 3 + 2 and fp.chroma[4] == [0.0] * 12  # five notes start on step 1; the song is 4 bars


def test_alike_songs_warn_and_different_ones_dont(ship: Project) -> None:
    (ship.music_dir / "a.song.yaml").write_text(song("a"))
    (ship.music_dir / "b.song.yaml").write_text(song("b", tempo=70))
    found = lint_music(ship)
    assert rules(found).count("W021") == 2 and rules(found).count("W024") == 2
    assert "opens on the same notes as b" in next(f.message for f in found if f.rule == "W021" and f.path.name == "a.song.yaml")
    (ship.music_dir / "b.song.yaml").write_text(song("b", key="E phrygian", tempo=132, chords=(52, 53, 55, 57), keys="gga", busy=True))
    assert not {"W021", "W024"} & set(rules(lint_music(ship)))


def test_project_wide_sameness(ship: Project) -> None:
    for i, (key, tempo) in enumerate((("D minor", 62), ("F major", 66), ("D minor", 70), ("A minor", 120))):
        (ship.music_dir / f"s{i}.song.yaml").write_text(song(f"s{i}", key=key, tempo=tempo, chords=(50 + i, 46, 48 + i, 45)))
    found = [f for f in lint_music(ship) if f.rule in ("W022", "W023")]
    messages = " | ".join(f.message for f in found)
    assert "3 of 4 songs use the same notes" in messages and "3 of 4 songs are within 10 bpm" in messages and "one kit (ship)" in messages
    assert all(f.path is not None and f.path.name == "segan.toml" for f in found)


def test_a_song_can_turn_a_warning_off(ship: Project) -> None:
    (ship.music_dir / "a.song.yaml").write_text(song("a") + "lint: { disable: [W021, W024] }\n")
    (ship.music_dir / "b.song.yaml").write_text(song("b"))
    found = lint_music(ship)
    assert {f.path.name for f in found if f.rule in ("W021", "W024")} == {"b.song.yaml"}


def test_shipped_fingerprints_are_current() -> None:
    """Regenerate with `python scripts/make_fingerprints.py` after changing the demo's songs or reference.md's example."""
    stored = json.loads((ROOT / "src" / "segan" / "fingerprints" / "shipped.json").read_text())
    assert stored == json.loads(json.dumps(similarity.make_shipped(ROOT), sort_keys=True))


def test_a_copy_of_an_example_is_flagged(tmp_path: Path) -> None:
    project = make_project(tmp_path / "game", CONFIG)
    demo = ROOT / "examples" / "demo"
    for kit in (demo / "kits").glob("*.kit.yaml"):
        shutil.copy(kit, project.kits_dir)
    shutil.copy(demo / "music" / "overworld.song.yaml", project.music_dir)
    found = lint_music(project)
    assert any(f.rule == "W025" and "segan:demo/overworld" in f.message for f in found)


def test_local_store_compares_projects_on_one_machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SEGAN_FINGERPRINTS", str(tmp_path / "store"))
    config = CONFIG + "\n[similarity]\nlocal_store = true\n"
    first, second = make_project(tmp_path / "one", config), make_project(tmp_path / "two", config)
    for p in (first, second):
        (p.kits_dir / "ship.kit.yaml").write_text(KIT)
    (first.music_dir / "theme.song.yaml").write_text(song("theme"))
    (second.music_dir / "title.song.yaml").write_text(song("title", tempo=68))
    monkeypatch.chdir(first.root)
    code, data = run_json(["similarity"], capsys)
    assert code == 0 and data["songs"] == ["theme"] and list((tmp_path / "store").glob("*.json"))
    found = lint_music(second)
    assert any(f.rule == "W026" and "one/theme" in f.message for f in found)
    off = make_project(tmp_path / "three")  # local_store off: no comparison with other projects
    (off.kits_dir / "ship.kit.yaml").write_text(KIT)
    (off.music_dir / "x.song.yaml").write_text(song("x"))
    assert "W026" not in rules(lint_music(off))


def test_similarity_command(ship: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (ship.music_dir / "a.song.yaml").write_text(song("a"))
    (ship.music_dir / "b.song.yaml").write_text(song("b", tempo=70))
    (ship.music_dir / "c.song.yaml").write_text(song("c", key="E phrygian", tempo=132, chords=(52, 53, 55, 57), keys="gga", busy=True))
    monkeypatch.chdir(ship.root)
    code, data = run_json(["similarity"], capsys)
    assert code == 0 and len(data["pairs"]) == 3
    top = data["pairs"][0]
    assert {top["a"], top["b"]} == {"a", "b"} and top["same_opening"] and top["overall"] > 0.9
    assert data["closest"]["c"]["overall"] < 0.7
    code, data = run_json(["similarity", "c", "--shipped"], capsys)
    assert code == 0 and all("c" in (p["a"], p["b"]) for p in data["pairs"]) and any(p["b"].startswith("segan:") for p in data["pairs"])
    code, data = run_json(["similarity", "nope"], capsys)
    assert code == 1


def test_preview_names_the_closest_song(ship: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (ship.music_dir / "a.song.yaml").write_text(song("a"))
    (ship.music_dir / "b.song.yaml").write_text(song("b", tempo=70))
    monkeypatch.chdir(ship.root)
    code, data = run_json(["preview", "a"], capsys)
    assert code == 0
    closest = data["outputs"][0]["outputs"][0]["analysis"]["closest_song"]
    assert closest["project"]["song"] == "b" and closest["project"]["same_opening"] and "segan" in closest
