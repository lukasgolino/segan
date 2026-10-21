from __future__ import annotations

from pathlib import Path

import pytest

from segan.cli import template
from segan.findings import SeganError
from segan.project import Config, parse_config
from segan.settings import SETTINGS, describe, parse_value, remove_from_toml, set_in_toml

from conftest import make_project, run_json


def test_registry_defaults_match_config_defaults() -> None:
    rows = {r["key"]: r for r in describe(Config())}
    for setting in SETTINGS:
        assert rows[setting.key]["value"] == setting.default, setting.key
        assert rows[setting.key]["is_default"]


def test_template_parses_to_defaults() -> None:
    import tomllib
    from string import Template

    text = Template(template("segan.toml")).substitute(mode="strict", default_kit='default_kit = "chip"')
    config = parse_config(tomllib.loads(text), Path("segan.toml"))
    assert config.mix == Config().mix and config.loudness == Config().loudness and config.lint == Config().lint


def test_set_in_toml_keeps_comments_and_layout() -> None:
    text = 'mode = "strict"  # strict or open\n\n[mix]\nroom = 0.15   # reverb\n# crush_bits = 0\n\n[lint]\ndisable = []\n'
    updated = set_in_toml(text, "mix.room", 0.3)
    assert "room = 0.3   # reverb" in updated
    updated = set_in_toml(updated, "mix.crush_bits", 8)
    assert "crush_bits = 8" in updated and "# crush_bits" not in updated
    updated = set_in_toml(updated, "godot.compress", "ima")
    assert updated.rstrip().endswith('[godot]\ncompress = "ima"')
    assert "room = 0.3" not in remove_from_toml(updated, "mix.room").replace("# room = 0.3", "")


def test_parse_value() -> None:
    assert parse_value("0.3") == 0.3 and parse_value("true") is True and parse_value("nes") == "nes"
    assert parse_value('["wav", "godot"]') == ["wav", "godot"]


def test_config_cli(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_project(in_tmp)
    code, data = run_json(["config", "show"], capsys)
    assert code == 0 and any(r["key"] == "mix.room" and r["value"] == 0.1 for r in data["settings"])
    code, data = run_json(["config", "get", "mix.sample_rate"], capsys)
    assert code == 0 and data["value"] == 22050
    code, data = run_json(["config", "set", "export", "wav,stems"], capsys)
    assert code == 0 and data["new"] == ["wav", "stems"]
    code, data = run_json(["config", "set", "default_kit", "nope"], capsys)
    assert code == 1 and data["findings"][0]["rule"] == "E005"
    code, data = run_json(["config", "unset", "mix.room"], capsys)
    assert code == 0 and data["new"] == 0.15
    code, data = run_json(["config", "set", "mix.wobble", "1"], capsys)
    assert code == 1


def test_loudness_targets_reach_minus_60(tmp_path: Path) -> None:
    """#9: quiet categories (a hover tick at -45 LUFS) are allowed; -60 is the floor."""
    from segan.project import load_project

    (tmp_path / "segan.toml").write_text('[loudness]\nhover = -45\n')
    assert load_project(tmp_path).config.target("hover") == -45
    (tmp_path / "segan.toml").write_text('[loudness]\nhover = -61\n')
    with pytest.raises(SeganError):
        load_project(tmp_path)
