from __future__ import annotations

from pathlib import Path

import pytest
from conftest import run_json

from segan.lint import WARNING_RULES

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "src" / "segan" / "skill"


def test_installed_copy_matches_the_package() -> None:
    """`.claude/skills/segan/` is this repo's installed copy: run `segan skill install` after editing the skill."""
    from segan.cli import _skill_files

    for name in _skill_files():
        assert (ROOT / ".claude" / "skills" / "segan" / name).read_text() == (SKILL / name).read_text(), name
    assert not (ROOT / ".claude" / "skills" / "segan" / "reference.md").exists()


def test_skill_frontmatter() -> None:
    text = (SKILL / "SKILL.md").read_text()
    assert text.startswith("---\nname: segan\ndescription: ")


@pytest.mark.parametrize("rule", [f"E{n:03d}" for n in range(21)] + sorted(WARNING_RULES))
def test_reference_documents_every_rule(rule: str) -> None:
    assert rule in (SKILL / "topics" / "lint.md").read_text()


def test_skill_install(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (in_tmp / ".git").mkdir()
    old = in_tmp / ".claude" / "skills" / "segan" / "reference.md"
    old.parent.mkdir(parents=True)
    old.write_text("the pre-0.16 reference")
    code, data = run_json(["skill", "install"], capsys)
    assert code == 0 and len(data["written"]) == len(list((SKILL / "topics").glob("*.md"))) + 2  # + SKILL.md + the removed reference
    assert not old.exists() and (in_tmp / ".claude" / "skills" / "segan" / "topics" / "sfx.md").is_file()
    assert (in_tmp / ".claude" / "skills" / "segan" / "SKILL.md").is_file()
    code, data = run_json(["skill", "install"], capsys)
    assert code == 0 and data["written"] == []


def test_reference_api_example_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from segan.lint import lint_paths
    from segan.project import load_project

    code = (SKILL / "topics" / "api.md").read_text().split("```python\n")[1].split("```")[0]
    project = ROOT / "examples" / "demo"
    monkeypatch.chdir(tmp_path)
    (tmp_path / "music").mkdir()
    exec(code, {})
    result = lint_paths(load_project(project), [tmp_path / "music" / "shop.song.yaml"], render=False)
    assert not result.errors, [f.format() for f in result.errors]
