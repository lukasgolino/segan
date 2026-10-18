from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from segan.cli import main


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run_json(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    code = main([*args, "--json"])
    return code, json.loads(capsys.readouterr().out)
