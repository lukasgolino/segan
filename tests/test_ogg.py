"""Export "ogg": music as Ogg Vorbis (deterministic bytes, exact length, loop to the file's end); SFX stay WAV."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import CONFIG, make_project, write
from test_flow import FLOW_SONG, G_SONG

from segan import oggio
from segan.build import build
from segan.render import render_asset

pytestmark = pytest.mark.skipif(not oggio.available(), reason="needs soundfile (segan[ogg])")


def ogg_project(tmp_path: Path, export: str = '["wav", "ogg"]') -> Path:
    project = make_project(tmp_path, CONFIG.replace('mode = "strict"', f'mode = "strict"\nexport = {export}') + "\n[ogg]\nquality = 0.5\n")
    write(project, "song", "f", FLOW_SONG)
    write(project, "song", "g", G_SONG)
    write(project, "sfx", "hit", "name: hit\npreset: hit\n")
    return tmp_path


def test_music_is_ogg_and_sfx_stay_wav(tmp_path: Path) -> None:
    from segan.project import load_project

    project = load_project(ogg_project(tmp_path))
    result = build(project)
    assert not result.errors, result.errors
    manifest = json.loads((project.output_dir / "manifest.json").read_text())
    g, hit = manifest["assets"]["g"], manifest["assets"]["hit"]
    assert g["file"].endswith(".ogg") and hit["file"].endswith(".wav")
    assert all(c.endswith(".ogg") for c in manifest["assets"]["f"]["flow"]["sections"]["verse"]["from"].values())
    audio, rate = oggio.decode_ogg((project.output_dir / g["file"]).read_bytes())
    assert rate == g["sample_rate"] and len(audio) == g["samples"] == g["loop"]["end"]  # exact length: the loop ends at the file's end
    song = render_asset(next(a for a in result.lint.assets if a.name == "g"), project).main
    assert np.abs(audio - song.audio).max() < 0.05  # lossy, but the same music
    files = sorted(p.name for p in project.output_dir.rglob("*.ogg"))
    first = {p: (project.output_dir / p).read_bytes() for p in (g["file"],)}
    rebuilt = build(project)
    assert not rebuilt.errors and all((project.output_dir / p).read_bytes() == b for p, b in first.items())  # byte-identical rebuild
    assert files and not rebuilt.written


def test_switching_back_to_wav_removes_the_ogg_files(tmp_path: Path) -> None:
    from segan.project import load_project

    project = load_project(ogg_project(tmp_path))
    assert not build(project).errors
    assert list(project.output_dir.rglob("*.ogg"))
    (tmp_path / "segan.toml").write_text((tmp_path / "segan.toml").read_text().replace('["wav", "ogg"]', '["wav"]'))
    project = load_project(tmp_path)
    result = build(project)
    assert not result.errors and not list(project.output_dir.rglob("*.ogg")) and result.removed


def test_ogg_quality_setting_is_checked(tmp_path: Path) -> None:
    from segan.findings import SeganError
    from segan.project import load_project

    ogg_project(tmp_path)
    (tmp_path / "segan.toml").write_text((tmp_path / "segan.toml").read_text().replace("quality = 0.5", "quality = 2"))
    with pytest.raises(SeganError) as caught:
        load_project(tmp_path)
    assert "ogg.quality" in str(caught.value.findings)
