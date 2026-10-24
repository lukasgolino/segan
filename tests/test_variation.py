"""#76 / #21 variety at authoring time and per-note dynamics: velocity marks, dynamics ramps, humanize, song and
project seeds, `segan kit roll`, `segan suggest song`, `segan new song` defaults, `segan init --style <words>`."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from segan.kit import load_kit_file
from segan.notes import parse_key
from segan.project import Project, load_project
from segan.sequence import build_timeline, placed_notes, song_events
from segan.suggest import roll_kit, suggest_song

from conftest import load, rules, run_json

SONG = """\
name: s
tempo: 120
key: A minor
tracks:
  lead: { roll: [A4, A5] }
  drums: { drums: [k, h] }
patterns:
  a:
    length: 8
    lead: |
      ........  A5
      ........  G5
      ........  F5
      ........  E5
      ........  D5
      ........  C5
      ........  B4
      p.p.p.p.  A4
    drums: |
      x...x...  k
      x.x.x.x.  h
    velocity: { lead: "X.o.5.x." }
    dynamics: { drums: [[1, -12], [5, 0]] }
  b: { from: a, velocity: { lead: "o.o.o.o." } }
sections: { main: [a, b] }
arrangement: [main]
loop: main
"""


def notes_of(song: Any, pattern: str, track: str) -> list[float]:
    return [n.velocity for n in sorted(song.patterns[pattern].notes, key=lambda n: n.step) if n.track == track]


def test_velocity_marks_and_dynamics(project: Project) -> None:
    song, findings = load(project, "song", "s", SONG)
    assert song is not None, findings
    assert notes_of(song, "a", "lead") == [1.5, 0.35, 1.0, 1.0]  # X, o, 5 (= 1.0), x
    kicks = [n.velocity for n in sorted(song.patterns["a"].notes, key=lambda n: n.step) if n.key == "k"]
    assert abs(kicks[0] - 10 ** (-12 / 20)) < 1e-6 and kicks[1] == 1.0  # the ramp: -12 dB at step 1, 0 dB from step 5
    hats = [n.velocity for n in sorted(song.patterns["a"].notes, key=lambda n: n.step) if n.key == "h"]
    assert abs(hats[1] - 10 ** (-6 / 20)) < 1e-6  # step 3: halfway up the ramp
    assert notes_of(song, "b", "lead") == [0.35] * 4  # a derived pattern sets its own


@pytest.mark.parametrize("bad", ['velocity: { lead: "X.o" }', 'velocity: { lead: "Z......." }', "velocity: { nope: x }",
                                 "dynamics: { lead: [[9, 0]] }", "dynamics: { lead: [[5, 0], [1, -3]] }", "dynamics: { lead: 3 }"])  # fmt: skip
def test_dynamics_errors(project: Project, bad: str) -> None:
    text = SONG.replace('    velocity: { lead: "X.o.5.x." }\n    dynamics: { drums: [[1, -12], [5, 0]] }\n', f"    {bad}\n")
    song, findings = load(project, "song", "s", text)
    assert song is None and "E003" in rules(findings)


def test_humanize_is_seeded_and_keeps_loops_whole(project: Project) -> None:
    plain, _ = load(project, "song", "s", SONG)
    loose, _ = load(project, "song", "s", SONG + "humanize: { timing: 12, velocity: 0.2 }\nseed: 7\n")
    other, _ = load(project, "song", "s", SONG + "humanize: { timing: 12, velocity: 0.2 }\nseed: 8\n")
    rate = 22050

    def events(song: Any) -> list[Any]:
        timeline = build_timeline(song)
        return song_events(song, timeline, rate, repeat_loop=True)

    a, b, c = events(plain), events(loose), events(other)
    assert len(a) == len(b) == len(c)
    moved = [y.start - x.start for x, y in zip(a, b, strict=True)]
    assert any(moved) and max(abs(m) for m in moved) <= round(0.012 * rate) + 1
    assert [e.start for e in b] != [e.start for e in c]  # another seed, another take
    assert [e.start for e in b] == [e.start for e in events(loose)]  # reproducible
    loop_len = sum(1 for e in b) // 2
    assert all(e2.start - e1.start == b[loop_len].start - b[0].start for e1, e2 in zip(b[:loop_len], b[loop_len:], strict=True))


def test_humanize_errors(project: Project) -> None:
    song, findings = load(project, "song", "s", SONG + "humanize: { timing: 100 }\n")
    assert song is None and "E001" in rules(findings)


# --- seeds and proposals --------------------------------------------------------------------------


def test_rolled_kits_differ_by_seed_and_are_valid(tmp_path: Path) -> None:
    texts = []
    for seed in (1, 2, 3):
        path = tmp_path / f"k{seed}.kit.yaml"
        rolled = roll_kit(f"k{seed}", "cold ship, warm crew", seed)
        path.write_text(rolled.yaml())
        kit = load_kit_file(path)
        assert len(kit.drums()) >= 3 and len(kit.melodic()) >= 4 and len(rolled.identity) == 3
        assert set(rolled.identity) <= set(kit.instruments) and kit.groups["identity"] == tuple(rolled.identity)
        texts.append(rolled.yaml().split("\n", 2)[2])
    assert len(set(texts)) == 3
    assert roll_kit("k1", "cold ship, warm crew", 1).yaml() == roll_kit("k1", "cold ship, warm crew", 1).yaml()


def test_roll_around_keeps_the_identity(tmp_path: Path) -> None:
    core = roll_kit("core", "dusty lo-fi jazz", 5)
    (tmp_path / "core.kit.yaml").write_text(core.yaml())
    around = yaml.safe_load(core.yaml())
    extra = roll_kit("battle", "hard aggressive combat", 5, around)
    for key in core.identity:
        assert extra.instruments[key] == core.instruments[key]
    assert extra.identity == core.identity
    (tmp_path / "battle.kit.yaml").write_text(extra.yaml())
    load_kit_file(tmp_path / "battle.kit.yaml")


def test_samples_only_when_asked() -> None:
    synth = roll_kit("x", "warm quiet electronics", 3)
    assert not synth.libraries
    assert any(roll_kit("x", "orchestral epic", seed).libraries for seed in range(5))
    assert not any(roll_kit("x", "orchestral epic", seed, samples=False).libraries for seed in range(5))


def test_suggestions_move_away_from_the_project(project: Project) -> None:
    from segan import similarity

    songs = []
    for i in range(6):
        song, _ = load(project, "song", f"s{i}", SONG.replace("name: s", f"name: s{i}").replace("tempo: 120", f"tempo: {66 + i}"))
        songs.append(similarity.fingerprint(song))
    used = {tuple(f.pitch_set) for f in songs}
    plans = [suggest_song("new", "", seed, songs, {}) for seed in range(12)]
    keys = [parse_key(p["key"]) for p in plans]
    assert sum(1 for k in keys if k is not None and tuple(sorted({(k.root + i) % 12 for i in k.intervals})) in used) <= 3
    assert all(abs(p["tempo"] - 68) > 3 or p["mood"] for p in plans[:4])
    assert len({p["key"] for p in plans}) > 6 and len({p["texture"] for p in plans}) > 4
    assert suggest_song("new", "tense boss fight", 1, songs, {})["mood"] == "tense" and 128 <= suggest_song("new", "tense boss fight", 1, songs, {})["tempo"] <= 176
    assert suggest_song("new", "", 4, songs, {}) == suggest_song("new", "", 4, songs, {})


def test_init_with_style_words_rolls_a_kit_and_a_seed(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seeds, kits = [], []
    for name in ("one", "two"):
        code, data = run_json(["init", name, "--style", "cold ship, warm crew"], capsys)
        assert code == 0 and data["default_kit"] == "core"
        project = load_project(in_tmp / name)
        seeds.append(project.config.seed)
        kits.append((in_tmp / name / "kits" / "core.kit.yaml").read_text().split("\n", 2)[2])
        load_kit_file(in_tmp / name / "kits" / "core.kit.yaml")
    assert seeds[0] != seeds[1] and None not in seeds and kits[0] != kits[1]
    code, data = run_json(["init", "chip", "--style", "chiptune"], capsys)
    assert code == 0 and data["default_kit"] == "chip" and load_project(in_tmp / "chip").config.seed is not None


def test_commands(in_tmp: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    run_json(["init", "game", "--style", "warm quiet electronics"], capsys)
    monkeypatch.chdir(in_tmp / "game")
    code, data = run_json(["kit", "roll", "battle", "--style", "hard combat", "--around", "core"], capsys)
    assert code == 0 and (in_tmp / "game" / "kits" / "battle.kit.yaml").is_file() and data["identity"]
    code, data = run_json(["kit", "roll", "battle", "--style", "hard combat"], capsys)
    assert code == 1  # exists
    code, data = run_json(["kit", "roll", "battle", "--style", "hard combat", "--dry-run", "--take", "2"], capsys)
    assert code == 0 and data["path"] is None and "instruments:" in data["text"]
    code, data = run_json(["suggest", "song", "title", "--mood", "quiet title screen"], capsys)
    plan = data["plan"]
    assert code == 0 and plan["mood"] == "calm" and plan["instruments"]["kit"] in ("core", "battle") and plan["command"].startswith("segan new song title")
    code, data = run_json(["new", "song", "title"], capsys)
    assert code == 0
    title = yaml.safe_load((in_tmp / "game" / "music" / "title.song.yaml").read_text())
    assert parse_key(title["key"]) is not None and isinstance(title["tempo"], int) and len(title["meter"]) == 2
    code, data = run_json(["new", "song", "plain", "--key", "C major", "--tempo", "100"], capsys)
    assert code == 0 and "meter: [4, 4]" in (in_tmp / "game" / "music" / "plain.song.yaml").read_text()
    code, data = run_json(["lint", "--no-render"], capsys)
    assert data["errors"] == 0, data
