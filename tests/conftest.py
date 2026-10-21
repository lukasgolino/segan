from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from segan.asset import load_asset
from segan.cli import main
from segan.findings import Finding
from segan.project import Project, load_project


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_json(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)


KIT = """\
name: t
instruments:
  p: { name: lead, osc: pulse, duty: 0.25, env: [0.005, 0.05, 0.6, 0.05], range: [C4, C6] }
  q: { name: soft, osc: triangle, env: [0.01, 0.05, 0.6, 0.05], voices: 2 }
  b: { name: bass, osc: triangle, env: [0.002, 0.05, 0.9, 0.05], range: [E1, C4] }
  k: { name: kick, drum: kick }
  s: { name: snare, drum: snare }
  h: { name: hat, drum: hat }
groups:
  leads: [p]
  softs: [q]
"""

OTHER_KIT = """\
name: u
instruments:
  p: { osc: saw, env: [0.005, 0.05, 0.6, 0.05] }
  q: { osc: sine }
  b: { osc: sine, range: [E1, C4] }
  k: { drum: kick }
  s: { drum: snare }
  h: { drum: hat }
"""

CONFIG = """\
mode = "strict"
default_kit = "t"

[mix]
sample_rate = 22050
room = 0.1
room_decay = 0.2
"""


def make_project(root: Path, config: str = CONFIG) -> Project:
    (root / "segan.toml").write_text(config)
    for name in ("kits", "music", "sfx"):
        (root / name).mkdir(exist_ok=True)
    (root / "kits" / "t.kit.yaml").write_text(KIT)
    (root / "kits" / "u.kit.yaml").write_text(OTHER_KIT)
    return load_project(root)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return make_project(tmp_path)


def write(project: Project, kind: str, name: str, text: str) -> Path:
    folder, suffix = (project.music_dir, ".song.yaml") if kind == "song" else (project.sfx_dir, ".sfx.yaml")
    path = folder / f"{name}{suffix}"
    path.write_text(text)
    return path


def load(project: Project, kind: str, name: str, text: str) -> tuple[Any, list[Finding]]:
    return load_asset(write(project, kind, name, text), project)


def rules(findings: list[Finding]) -> list[str]:
    return [f.rule for f in findings]


@pytest.fixture(autouse=True)
def _one_render_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests render tiny projects: a process pool would cost more than it saves (test_render_jobs covers it)."""
    monkeypatch.setenv("SEGAN_JOBS", "1")
