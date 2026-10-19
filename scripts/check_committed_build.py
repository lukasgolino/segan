"""CI check: after `segan build`, the generated folder must match the commit.

WAVs may differ by 1 LSB between machines (float results can differ by an ulp; see CLAUDE.md), so they are
compared by decoded samples with that tolerance; every other file must be byte-identical, and nothing may
be added or removed. Usage: python scripts/check_committed_build.py <generated dir>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

from segan.wavio import read_wav


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def main(folder: str) -> int:
    top = Path(git("rev-parse", "--show-toplevel").decode().strip())
    changed = [line for line in git("status", "--porcelain", "--", folder).decode().splitlines() if line.strip()]
    problems = []
    for line in changed:
        status, path = line[:2], line[3:]
        if status.strip() != "M" or not path.endswith(".wav"):
            problems.append(f"{status.strip()} {path}")
            continue
        old = read_wav(git("show", f"HEAD:{path}"))
        new = read_wav((top / path).read_bytes())
        same_shape = old.samples.shape == new.samples.shape and old.loop == new.loop and old.cues == new.cues and old.rate == new.rate
        diff = int(np.abs(old.samples.astype(np.int32) - new.samples.astype(np.int32)).max()) if same_shape else -1
        if diff < 0 or diff > 1:
            problems.append(f"M {path} (max sample difference {diff})")
        else:
            print(f"ok {path}: within 1 LSB of the commit")
    if problems:
        print("Generated output differs from the commit: run `segan build` in examples/demo and commit.")
        print("\n".join(problems))
        return 1
    print(f"generated output matches the commit ({len(changed)} WAVs within 1 LSB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
