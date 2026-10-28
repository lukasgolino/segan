"""#34: export "web" writes segan_audio.js (a Web Audio player for the manifest). The player is tested headless with
node (`tests/web/segan_audio.test.mjs`, a fake AudioContext) against a real build; skipped where node is missing."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from segan.build import build
from segan.findings import SeganError
from segan.project import load_project

from conftest import CONFIG, make_project, write
from test_song import SONG

ROOT = Path(__file__).resolve().parent.parent
PLAYER = ROOT / "src" / "segan" / "templates" / "segan_audio.js"
WEB = 'export = ["wav", "web"]\n'


def web_project(root: Path) -> Path:
    project = make_project(root, WEB + CONFIG + '\n[bus.pickup]\nbus = "SFX"\nvolume_db = -3\n')
    write(project, "song", "tune", SONG)
    write(project, "sfx", "coin", "name: coin\npreset: coin\nvariations: { count: 3, seed: 1, pitch: 1 }\nplayback: { max_instances: 2, min_gap_s: 0.05 }\n")
    write(project, "sfx", "hum", "name: hum\nduration: 0.3\nloop: true\nlayers:\n  - { osc: sine, pitch: A3 }\n")
    return root


def test_web_export_writes_the_player(tmp_path: Path) -> None:
    root = web_project(tmp_path)
    result = build(load_project(root))
    assert not result.errors, result.errors
    out = root / "build" / "audio"
    assert (out / "segan_audio.js").read_text() == PLAYER.read_text()
    manifest = json.loads((out / "manifest.json").read_text())
    assert "segan_audio.js" in manifest["files"] and manifest["assets"]["coin"]["file"] == "sfx/coin.wav"
    (root / "segan.toml").write_text(CONFIG)
    result = build(load_project(root))
    assert not (out / "segan_audio.js").exists() and "segan_audio.js" in [p.name for p in result.removed]


def test_web_and_godot_dont_mix(tmp_path: Path) -> None:
    (tmp_path / "segan.toml").write_text('export = ["wav", "godot", "web"]\n')
    with pytest.raises(SeganError, match='both "godot" and "web"'):
        load_project(tmp_path)


@pytest.mark.skipif(shutil.which("node") is None, reason="node isn't installed")
def test_player_in_node(tmp_path: Path) -> None:
    root = web_project(tmp_path)
    assert not build(load_project(root)).errors
    env = {**os.environ, "SEGAN_AUDIO_JS": str(PLAYER), "SEGAN_WEB_BUILD": str(root / "build" / "audio")}
    run = subprocess.run(["node", "--test", str(ROOT / "tests" / "web" / "segan_audio.test.mjs")], env=env, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "# fail 0" in run.stdout and "# skipped 0" in run.stdout and "# pass 7" in run.stdout
