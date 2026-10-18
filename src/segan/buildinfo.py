"""Which SEGAN build is running: a pinned release, a VCS install at some commit, or a dev checkout.

`segan --version` shows this so a game can tell exactly what produced its assets. The manifest keeps
only the release version, so the same release always produces byte-identical output.
"""

from __future__ import annotations

import json
import subprocess
from importlib.metadata import PackageNotFoundError, distribution
from urllib.parse import unquote, urlparse

from segan import __version__


def install_details() -> str | None:
    """e.g. "v0.1.0, ce24ab4" (pip install from git), "editable checkout v0.1.0-3-g1a2b3c4-dirty", or None."""
    try:
        text = distribution("segan").read_text("direct_url.json")
    except PackageNotFoundError:
        return "not installed: running from a source tree"
    if not text:
        return None  # a plain release install (e.g. from an index)
    try:
        data = json.loads(text)
    except ValueError:
        return None
    vcs = data.get("vcs_info")
    if isinstance(vcs, dict):
        commit = str(vcs.get("commit_id", ""))[:7]
        requested = vcs.get("requested_revision")
        return f"{requested}, {commit}" if requested else commit or None
    if isinstance(data.get("dir_info"), dict) and data["dir_info"].get("editable"):
        path = unquote(urlparse(str(data.get("url", ""))).path)
        return f"editable checkout {_describe(path) or path}"
    return None


def _describe(path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", path, "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, timeout=5,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def is_editable() -> bool:
    details = install_details()
    return bool(details and details.startswith("editable"))


def version_string() -> str:
    details = install_details()
    return f"segan {__version__}" + (f" ({details})" if details else "")
