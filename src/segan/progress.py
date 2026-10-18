"""Progress lines on stderr for slow steps (song renders, Godot), so a long run shows it's alive.

Copied from PAGAN's progress.py. Only the CLI turns them on (`--quiet` or SEGAN_QUIET=1 turns them off);
stdout, and so `--json`, is never touched.
"""

from __future__ import annotations

import sys

enabled = False


def note(message: str) -> None:
    if enabled:
        print(f"segan: {message}", file=sys.stderr, flush=True)
