from __future__ import annotations

from pathlib import Path

import pytest

from segan.cli import main
from segan.project import load_project
from segan.wavio import read_wav

from conftest import run_json


def test_init_creates_a_working_strict_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["init", "art"], capsys)
    assert code == 0 and data["mode"] == "strict" and data["default_kit"] == "chip"
    project = load_project(in_tmp / "art")
    assert project.config.default_kit == "chip"
    assert project.load_kit("chip").instruments
    for name in ("BRIEF.md", "SOUND.md", ".gitignore", "kits", "music", "sfx"):
        assert (in_tmp / "art" / name).exists()
    code, data = run_json(["init", "art"], capsys)
    assert code == 1 and data["findings"][0]["rule"] == "E000"


def test_init_synth_style_and_open_mode(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["init", "a", "--style", "synth", "--open"], capsys)
    assert code == 0 and data["default_kit"] == "synth" and data["mode"] == "open"
    assert load_project(in_tmp / "a").config.mode == "open"


def test_init_orchestral_style(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from segan.kitshow import library_needs

    code, data = run_json(["init", "o", "--style", "orchestral"], capsys)
    assert code == 0 and data["default_kit"] == "orchestra"
    config = load_project(in_tmp / "o").config
    assert config.mix.room == 0.3 and config.mix.room_decay == 1.6 and config.lint.max_instruments == 16
    needs = library_needs(in_tmp / "o" / "kits" / "orchestra.kit.yaml")
    assert "violins_sus" in needs and "timpani" in needs
    (in_tmp / "o" / "sfx" / "hit.sfx.yaml").write_text("layers:\n  - sample: vsco2/horn_stac\n", encoding="utf-8")
    assert library_needs(in_tmp / "o") == [*needs, "horn_stac"]


def test_init_into_godot_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (in_tmp / "game").mkdir()
    (in_tmp / "game" / "project.godot").write_text("config_version=5\n")
    code, data = run_json(["init", "game/audio_src", "--godot", "game"], capsys)
    assert code == 0
    config = load_project(in_tmp / "game" / "audio_src").config
    assert config.export == ("wav", "godot") and config.output_dir == "../assets/generated/audio"
    assert (in_tmp / "game" / "audio_src" / ".gdignore").exists()


def test_init_warns_about_a_pagan_output_clash(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (in_tmp / "pagan.toml").write_text('output_dir = "art/build/audio"\n')
    code, data = run_json(["init", "art"], capsys)
    assert code == 0 and data["pagan_clash"] is not None


def test_init_steps_out_of_a_sibling_pagan_output(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """#12: game/art/pagan.toml builds into game/assets/generated: the audio goes to assets/audio, not inside it."""
    (in_tmp / "game" / "art").mkdir(parents=True)
    (in_tmp / "game" / "project.godot").write_text("config_version=5\n")
    (in_tmp / "game" / "art" / "pagan.toml").write_text('output_dir = "../assets/generated"\n')
    code, data = run_json(["init", "game/sound", "--godot", "game"], capsys)
    assert code == 0 and data["pagan_clash"] is None
    assert load_project(in_tmp / "game" / "sound").config.output_dir == "../assets/audio"


def test_init_warns_when_outputs_nest(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """#12: an output_dir inside PAGAN's (or around it) is a clash too, not only the same folder."""
    (in_tmp / "pagan.toml").write_text('output_dir = "art"\n')
    code, data = run_json(["init", "art/sound"], capsys)  # build/audio inside art/
    assert code == 0 and data["pagan_clash"] is not None


def test_new_kit_and_kit_show(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["init", "."])
    capsys.readouterr()
    code, data = run_json(["new", "kit", "tiny"], capsys)
    assert code == 0 and Path(data["created"]).is_file()
    code, data = run_json(["new", "kit", "tiny"], capsys)
    assert code == 1
    code, data = run_json(["kit", "show", "tiny"], capsys)
    assert code == 0, data
    out = data["outputs"][0]
    assert Path(out["sheet"]).is_file() and len(out["wavs"]) == 6
    wav = read_wav(Path(out["wavs"][0]).read_bytes())
    assert wav.rate == 44100 and wav.channels == 2
    assert abs(out["lufs"] + 16.0) < 0.5
    assert out["instruments"]["p"]["aliasing_db"] < -50
    code, data = run_json(["kit", "show", "nope"], capsys)
    assert code == 1 and data["findings"][0]["rule"] == "E005"


def test_commands_need_a_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["new", "kit", "x"], capsys)
    assert code == 1 and "segan init" in data["findings"][0]["message"]
