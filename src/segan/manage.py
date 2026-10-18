"""Long-term asset management (filled in by milestone 5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from segan.project import Project


@dataclass
class AssetStatus:
    name: str
    kind: str
    path: Path
    errors: int


def catalogue(project: Project, render: bool = True) -> list[AssetStatus]:
    return []
