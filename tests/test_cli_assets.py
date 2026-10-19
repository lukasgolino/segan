from __future__ import annotations

from pathlib import Path

import pytest

from segan.cli import main

from conftest import make_project, run_json, write
from test_song import SONG


@pytest.fixture
def proj(in_tmp: Path) -> Path:
    make_project(in_tmp)
    return in_tmp


def test_new_song_scaffold_parses(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["new", "song", "theme", "--key", "D dorian", "--tempo", "100", "--bars", "1"], capsys)
    assert code == 0, data
    text = Path(data["created"]).read_text()
    assert "key: D dorian" in text and "length: 16" in text
    code, data = run_json(["lint", "--no-render", data["created"]], capsys)
    assert code == 0 and data["errors"] == 0, data
    code, data = run_json(["new", "song", "theme"], capsys)
    assert code == 1
    code, data = run_json(["new", "sfx", "theme"], capsys)
    assert code == 1 and "unique" in data["findings"][0]["message"]


@pytest.mark.parametrize("preset", [None, "laser"])
def test_new_sfx_scaffold_lints(proj: Path, capsys: pytest.CaptureFixture[str], preset: str | None) -> None:
    code, data = run_json(["new", "sfx", "pew", *(["--preset", preset] if preset else [])], capsys)
    assert code == 0, data
    code, data = run_json(["lint", data["created"]], capsys)
    assert code == 0 and data["errors"] == 0, data["findings"]


def test_preview_writes_wav_sheet_and_analysis(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(make_project(proj), "song", "tune", SONG)
    code, data = run_json(["preview", "tune"], capsys)
    assert code == 0, data
    outputs = data["outputs"][0]["outputs"]
    assert [o["output"] for o in outputs] == ["main", "variant:fast", "variant:other", "variant:minor"]
    main = outputs[0]
    assert Path(main["wav"]).is_file() and Path(main["sheet"]).is_file() and Path(main["seam"]).is_file()
    analysis = main["analysis"]
    assert abs(analysis["lufs"] + 16) < 0.5 and analysis["loop"]["end"] == analysis["frames"]
    assert analysis["pitch_check"]["lead"]["notes_checked"] > 0 and analysis["pitch_check"]["lead"]["off"] == []
    code, data = run_json(["preview", "tune", "--output", "variant:fast", "--from", "2", "--to", "3"], capsys)
    assert code == 0 and len(data["outputs"][0]["outputs"]) == 1


def test_preview_several_stems_at_once(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_song import GROUPED

    write(make_project(proj), "song", "tune", GROUPED)
    code, data = run_json(["preview", "tune", "--output", "stem:top", "--output", "mix:calm", "--output", "main"], capsys)
    assert code == 0, data
    outputs = {o["output"]: o["analysis"] for o in data["outputs"][0]["outputs"]}
    assert set(outputs) == {"main", "stem:top", "mix:calm"}
    assert set(outputs["stem:top"]["pitch_check"]) == {"lead"} and "bass" in outputs["mix:calm"]["pitch_check"]
    assert set(outputs["main"]["stem_mixes_lufs"]) == {"calm", "full"} and outputs["mix:calm"]["normalised_over_mix"] == "full"
    code, data = run_json(["preview", "tune", "--output", "stem:nope"], capsys)
    assert code == 1 and "stem:nope" in data["findings"][0]["message"]


def test_render_gallery_bake(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(proj)
    write(project, "sfx", "coin", "name: coin\npreset: coin\nvariations: { count: 2 }\n")
    code, data = run_json(["render", "coin"], capsys)
    assert code == 0 and len(data["outputs"][0]["files"]) == 3
    code, data = run_json(["gallery"], capsys)
    assert code == 0 and data["assets"] == 1 and Path(data["gallery"]).is_file()
    code, data = run_json(["bake", "sfx", "coin"], capsys)
    assert code == 0, data
    baked = Path(data["created"]).read_text()
    assert "\npreset:" not in baked and "id: shimmer" in baked and "name: coin_baked" in baked
    code, data = run_json(["lint", "--no-render", data["created"]], capsys)
    assert code == 0, data
    code, data = run_json(["bake", "sfx", "coin", "--in-place"], capsys)
    assert code == 0 and "preset" not in (proj / "sfx" / "coin.sfx.yaml").read_text().split("\n", 1)[1]


def test_lint_exit_codes(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(proj)
    write(project, "sfx", "bad", "name: bad\nlayers: []\n")
    code, data = run_json(["lint"], capsys)
    assert code == 1 and data["errors"] >= 1
    write(project, "sfx", "bad", "name: bad\nduration: 0.1\nlayers:\n  - { osc: sine, pitch: A4, length: 0.09, env: [0.001, 0.1, 0.5, 0.5] }\n")
    code, data = run_json(["lint"], capsys)
    assert code == 0 and data["warnings"] >= 1
    assert main(["lint", "--warnings-as-errors"]) == 1


def test_unknown_asset(proj: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["preview", "nothing"], capsys)
    assert code == 1 and data["findings"][0]["rule"] == "E000"
