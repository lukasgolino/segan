"""`segan docs` and the token budgets that keep the skill cheap for agents."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import run_json

from segan import docs

SKILL = Path(__file__).parent.parent / "src" / "segan" / "skill"

# Budgets in bytes (about 4 per token). The core is loaded whenever the skill triggers and stays in context for
# the whole session, so it is the expensive one; topics are read on demand.
SKILL_CORE_BYTES = 8_000
TOPIC_BYTES = 16_000
DESCRIPTION_CHARS = 420


def test_skill_core_budget() -> None:
    size = len((SKILL / "SKILL.md").read_bytes())
    assert size <= SKILL_CORE_BYTES, f"SKILL.md is {size} bytes: move detail into a topic"


def test_skill_description_budget() -> None:
    line = next(line for line in (SKILL / "SKILL.md").read_text().splitlines() if line.startswith("description: "))
    assert len(line) - len("description: ") <= DESCRIPTION_CHARS


@pytest.mark.parametrize("topic", [t.name for t in docs.topics()])
def test_topic_budget_and_shape(topic: str) -> None:
    found = docs.find(topic)
    assert found is not None and found.text.startswith("# ") and found.summary
    assert len(found.text.encode()) <= TOPIC_BYTES, f"{topic} is {len(found.text.encode())} bytes: split it"


def test_core_names_every_topic() -> None:
    core = (SKILL / "SKILL.md").read_text()
    assert all(f"`{t.name}`" in core for t in docs.topics())


def test_docs_list_print_search(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["docs"], capsys)
    assert code == 0 and {"sfx", "songs", "lint"} <= {t["name"] for t in data["topics"]}
    code, data = run_json(["docs", "sfx"], capsys)
    assert code == 0 and data["topics"][0]["text"].startswith("# Sfx")
    code, data = run_json(["docs", "--search", "seam", "click"], capsys)
    assert code == 0 and 1 <= len(data["hits"]) <= 5
    assert all(len(h["text"]) < 2000 for h in data["hits"])  # paragraphs, not whole topics


def test_docs_unknown_topic_suggests(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["docs", "sfz"], capsys)
    assert code != 0 and "sfx" in data["findings"][0]["message"]


def test_status_is_terse_by_default(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    from segan.cli import main

    monkeypatch.chdir(Path(__file__).parent.parent / "examples" / "demo")
    assert main(["status", "--fast"]) == 0
    terse = capsys.readouterr().out
    assert main(["status", "--fast", "-v"]) == 0
    verbose = capsys.readouterr().out
    assert "coin" in terse and "Bright two-note pickup" not in terse and "Bright two-note pickup" in verbose
    assert len(terse) < 1500 and len(terse) < len(verbose) / 2
    assert main(["--json", "status", "--fast"]) == 0
    raw = capsys.readouterr().out
    assert raw.count("\n") == 1 and '"description"' not in raw  # compact JSON, descriptions only with -v


def test_preview_text_has_the_checks(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The text output carries the numbers an agent checks, so it needn't parse `--json` for them."""
    import shutil

    from segan.cli import main

    demo = Path(__file__).parent.parent / "examples" / "demo"
    shutil.copytree(demo, tmp_path / "demo", ignore=shutil.ignore_patterns("previews", ".segan-cache"))
    monkeypatch.chdir(tmp_path / "demo")
    assert main(["preview", "coin"]) == 0
    text = capsys.readouterr().out
    assert "pitch 987.7 -> 1321.2 Hz" in text and "lead-in" in text and "onsets" in text
