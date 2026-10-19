from __future__ import annotations

from pathlib import Path

import pytest

from segan.lint import WARNING_RULES

from conftest import run_json

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "src" / "segan" / "skill"


def test_installed_copy_matches_the_package() -> None:
    """`.claude/skills/segan/` is this repo's installed copy: run `segan skill install` after editing the skill."""
    for name in ("SKILL.md", "reference.md"):
        assert (ROOT / ".claude" / "skills" / "segan" / name).read_text() == (SKILL / name).read_text(), name


def test_skill_frontmatter() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: segan\ndescription: ")


@pytest.mark.parametrize("rule", [f"E{n:03d}" for n in range(16)] + sorted(WARNING_RULES))
def test_reference_documents_every_rule(rule: str) -> None:
    assert rule in (SKILL / "reference.md").read_text()


def test_skill_install(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (in_tmp / ".git").mkdir()
    code, data = run_json(["skill", "install"], capsys)
    assert code == 0 and len(data["written"]) == 2
    assert (in_tmp / ".claude" / "skills" / "segan" / "SKILL.md").is_file()
    code, data = run_json(["skill", "install"], capsys)
    assert code == 0 and data["written"] == []
