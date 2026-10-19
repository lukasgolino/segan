from __future__ import annotations

from pathlib import Path

import pytest

from segan.build import build
from segan.manage import MixAdjustment, adjust_mix, bump_style, catalogue
from segan.project import load_project
from segan.render import render_asset

from conftest import load, make_project, run_json, write
from test_song import SONG


@pytest.fixture
def proj(in_tmp: Path) -> Path:
    project = make_project(in_tmp)
    (in_tmp / "SOUND.md").write_text("# Sound bible\n\n## Changelog\n\n- v1: first version.\n")
    write(project, "song", "tune", SONG)
    write(project, "sfx", "coin", "name: coin\n# a comment that must survive\npreset: coin\nstatus: draft\nstyle_version: 1\n")
    return in_tmp


def test_status_lists_assets_and_needs(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["status"], capsys)
    assert code == 0
    by_name = {a["name"]: a for a in data["assets"]}
    assert set(by_name) == {"coin", "tune"}
    assert by_name["coin"]["category"] == "pickup" and by_name["coin"]["seconds"] > 0.3
    assert "a human listen + approve" in by_name["coin"]["needs"] and "describe" in by_name["coin"]["needs"]
    assert by_name["tune"]["outputs"] == 4


def test_mark_keeps_comments(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["mark", "coin", "--status", "approved"], capsys)
    assert code == 0
    text = (proj / "sfx" / "coin.sfx.yaml").read_text()
    assert "status: approved" in text and "# a comment that must survive" in text
    code, data = run_json(["mark", "coin"], capsys)
    assert code == 1


def test_style_bump_flags_every_asset(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["style", "bump", "punchier drums"], capsys)
    assert code == 0 and data["style_version"] == 2 and data["outdated"] == 2
    assert "- v2 (" in (proj / "SOUND.md").read_text() and "punchier drums" in (proj / "SOUND.md").read_text()
    code, data = run_json(["lint", "--no-render"], capsys)
    assert sorted(f["path"] for f in data["findings"] if f["rule"] == "W006") == ["music/tune.song.yaml", "sfx/coin.sfx.yaml"]
    code, data = run_json(["mark", "--outdated", "--current"], capsys)
    assert code == 0 and len(data["marked"]) == 2
    code, data = run_json(["lint", "--no-render"], capsys)
    assert not [f for f in data["findings"] if f["rule"] == "W006"]


def test_config_set_room_rerenders_everything(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = load_project(proj)
    before = build(project)
    assert not before.errors
    code, data = run_json(["config", "set", "mix.room", "0.3"], capsys)
    assert code == 0 and data["refreshes"] == "all" and data["new"] == 0.3
    after = build(load_project(proj))
    wavs = {p.name for p in after.written if p.suffix == ".wav"}
    assert {"tune.wav", "tune.fast.wav", "coin.wav"} <= wavs and not [p for p in after.unchanged if p.suffix == ".wav"]
    code, data = run_json(["config", "set", "mix.room", "3"], capsys)
    assert code == 1 and "room" in data["findings"][0]["message"]
    code, data = run_json(["config", "set", "loudness.boss", "-12"], capsys)
    assert code == 0 and load_project(proj).config.target("boss") == -12


def test_mix_adjust(proj: Path) -> None:
    project = load_project(proj)
    changes = adjust_mix(project, MixAdjustment(brightness=2, room=0.05, loudness=-1, crush=8), dry_run=True)
    assert changes["mix.brightness"] == (0.0, 2.0) and changes["mix.crush_bits"] == (0, 8)
    assert changes["loudness.music"] == (-16.0, -17.0)
    assert load_project(proj).config.mix.brightness == 0.0  # dry run: nothing written
    adjust_mix(project, MixAdjustment(brightness=2, loudness=-1))
    config = load_project(proj).config
    assert config.mix.brightness == 2.0 and config.target("music") == -17.0 and config.target("ui") == -21.0
    song, _ = load(load_project(proj), "song", "tune", SONG)
    assert abs(float(render_asset(song, load_project(proj)).main.level["lufs"]) + 17.0) < 0.3  # type: ignore[arg-type]


def test_mix_adjust_cli(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["mix", "adjust"], capsys)
    assert code == 1
    code, data = run_json(["mix", "adjust", "--warmth", "3", "--dry-run"], capsys)
    assert code == 0 and data["changes"]["mix.warmth"] == {"from": 0.0, "to": 3.0} and data["written"] is False


def test_catalogue_without_render(proj: Path) -> None:
    entries = catalogue(load_project(proj), render=False)
    assert [e.seconds for e in entries] == [None, None]


def test_bump_style_without_changelog(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    assert bump_style(project, "first change") == 2
    assert "## Changelog" in (tmp_path / "SOUND.md").read_text()
