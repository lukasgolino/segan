"""#87: opt-in duration-aware loudness for short one-shots (`[loudness] short_sfx = "duration"`) and the gallery's
peak readout. The default ("window") must render exactly as before."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from segan.analysis import MOMENTARY_WINDOW, max_momentary_lufs, peak_db, sfx_window
from segan.findings import SeganError
from segan.preview import analyze
from segan.project import parse_config
from segan.render import render_asset

from conftest import CONFIG, load, make_project, run_json

CLICK = "name: click\ncategory: ui\nduration: 0.06\nlayers:\n  - { osc: pulse, pitch: C6, env: [0.001, 0.03, 0.0, 0.02] }\n"
LONG = "name: whoosh\nduration: 0.6\nlayers:\n  - { osc: noise, env: [0.05, 0.3, 0.3, 0.2] }\n"
LOOP = "name: hum\nduration: 0.2\nloop: true\ncrossfade: 0.02\nlayers:\n  - { osc: saw, pitch: C3 }\n"
DURATION = '\n[loudness]\nshort_sfx = "duration"\n'
WINDOW = '\n[loudness]\nshort_sfx = "window"\n'


def test_window() -> None:
    assert sfx_window(0.06, False, "window") == MOMENTARY_WINDOW
    assert sfx_window(0.06, False, "duration") == 0.06
    assert sfx_window(0.001, False, "duration") == 0.01
    assert sfx_window(0.9, False, "duration") == MOMENTARY_WINDOW
    assert sfx_window(0.06, True, "duration") == MOMENTARY_WINDOW  # loops are heard continuously


def renders(tmp_path: Path, extra: str) -> dict[str, tuple[bytes, float]]:
    root = tmp_path / str(abs(hash(extra)))
    root.mkdir()
    project = make_project(root, CONFIG + extra)
    out = {}
    for text in (CLICK, LONG, LOOP):
        name = text.split("\n")[0].split(": ")[1]
        sfx, findings = load(project, "sfx", name, text)
        assert sfx is not None, findings
        main = render_asset(sfx, project, use_cache=False).main
        out[name] = (main.wav(), peak_db(main.audio))
    return out


def test_default_is_unchanged_and_duration_turns_short_one_shots_down(tmp_path: Path) -> None:
    default, window, duration = renders(tmp_path, ""), renders(tmp_path, WINDOW), renders(tmp_path, DURATION)
    assert default == window  # "window" is the default, byte for byte
    assert duration["whoosh"] == default["whoosh"] and duration["hum"] == default["hum"]  # >= 400 ms and loops: as before
    drop = default["click"][1] - duration["click"][1]
    assert drop > 0.8 * 10 * math.log10(MOMENTARY_WINDOW / 0.06), drop  # about 8 dB quieter (the room tail adds a little)


def test_level_and_preview_use_the_window(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG + DURATION)
    sfx, _ = load(project, "sfx", "click", CLICK)
    main = render_asset(sfx, project).main
    assert main.info["loudness_window"] == 0.06
    assert abs(float(main.level["lufs"] or 0) - max_momentary_lufs(main.audio, main.rate, 0.06)) < 0.01
    result = analyze(main, "sfx")
    assert result["loudness_measure"] == "max momentary (60 ms)" and abs(result["lufs"] - float(main.level["target"] or 0)) < 1.0
    (tmp_path / "plain").mkdir()
    plain = make_project(tmp_path / "plain")
    sfx, _ = load(plain, "sfx", "click", CLICK)
    main = render_asset(sfx, plain).main
    assert "loudness_window" not in main.info and analyze(main, "sfx")["loudness_measure"] == "max momentary (400 ms)"


def test_config(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert parse_config({"loudness": {"short_sfx": "duration", "ui": -22}}, Path("segan.toml")).short_sfx == "duration"
    config = parse_config({"loudness": {"ui": -22}}, Path("segan.toml"))
    assert config.short_sfx == "window" and "short_sfx" not in config.loudness
    with pytest.raises(SeganError, match="short_sfx"):
        parse_config({"loudness": {"short_sfx": "peak"}}, Path("segan.toml"))
    make_project(in_tmp)
    code, data = run_json(["config", "set", "loudness.short_sfx", "duration"], capsys)
    assert code == 0 and data["new"] == "duration"
    assert 'short_sfx = "duration"' in (in_tmp / "segan.toml").read_text()
    code, data = run_json(["config", "get", "loudness.short_sfx"], capsys)
    assert code == 0 and data["value"] == "duration"
    assert run_json(["config", "set", "loudness.short_sfx", "peak"], capsys)[0] != 0
    code, _ = run_json(["mix", "adjust", "--loudness", "-1"], capsys)  # shifts the targets, leaves short_sfx alone
    assert code == 0 and 'short_sfx = "duration"' in (in_tmp / "segan.toml").read_text()


def test_gallery_shows_short_one_shots(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(in_tmp)
    load(project, "sfx", "click", CLICK)
    code, data = run_json(["gallery"], capsys)
    assert code == 0 and data["assets"] == 1 and Path(data["gallery"]).is_file()
