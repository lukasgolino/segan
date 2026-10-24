"""Regenerate src/segan/fingerprints/shipped.json: fingerprints of the demo's songs and of reference.md's generator
example, so lint (W025) warns any user whose song is close to SEGAN's own examples. Run after changing either;
tests/test_similarity.py fails while it's stale. Usage: python scripts/make_fingerprints.py
"""

from __future__ import annotations

import json
from pathlib import Path

from segan.similarity import make_shipped

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    out = ROOT / "src" / "segan" / "fingerprints" / "shipped.json"
    out.write_text(json.dumps(make_shipped(ROOT), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
