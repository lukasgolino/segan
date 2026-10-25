"""The licence rule for recorded sounds: only CC0 and CC BY (any version) are allowed.

CC0 needs nothing; CC BY needs attribution (title, author, source, licence, and a note that it was changed),
which `segan sounds credits` writes. Everything else is refused: non-commercial (BY-NC) can't ship in a game that
might be sold, share-alike (BY-SA) and no-derivatives (BY-ND) don't fit sounds that are processed and mixed into
a game, Sampling+ is withdrawn, and an unknown licence is no licence. A project can clear other licences itself
(royalty-free libraries under their own terms) by name: `[sounds] extra_licences = ["Sonniss-GDC"]`.

A licence can be written as an id (`CC0`, `CC0-1.0`, `CC-BY`, `CC-BY-4.0`, `CC BY 3.0`), as a Creative Commons
URL (`https://creativecommons.org/licenses/by/4.0/`, `.../publicdomain/zero/1.0/`), or as Freesound's licence
names ("Creative Commons 0", "Attribution").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


@dataclass(frozen=True)
class Licence:
    id: str  # SPDX-style: CC0-1.0, CC-BY-4.0, CC-BY-3.0, ... or CC-BY (version not given)
    url: str
    attribution: bool  # credits are required (CC BY)
    cleared: bool = False  # not CC: a licence the project cleared itself (`[sounds] extra_licences`)

    @property
    def title(self) -> str:
        if self.cleared:
            return self.id
        return "CC0 1.0" if self.id == "CC0-1.0" else self.id.replace("CC-BY", "CC BY").replace("-", " ")


def _by(version: str | None) -> Licence:
    if version is None:
        return Licence("CC-BY", "https://creativecommons.org/licenses/by/4.0/", True)
    return Licence(f"CC-BY-{version}", f"https://creativecommons.org/licenses/by/{version}/", True)


_CC0 = Licence("CC0-1.0", CC0_URL, False)
_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?creativecommons\.org/(licenses|publicdomain)/([a-z+-]+)/(\d\.\d)/?(?:[a-z]{2}(?:[-_][a-z]+)?/?)?(?:legalcode.*|deed.*)?$", re.I)
_ID_RE = re.compile(r"^cc[\s_-]*by(?:[\s_-]*(\d(?:\.\d)?))?$", re.I)
BY_VERSIONS = ("1.0", "2.0", "2.5", "3.0", "4.0")


def project_extras(root: Path) -> tuple[str, ...]:
    """Licences a project has cleared itself (`[sounds] extra_licences` in segan.toml at `root`)."""
    config = root / "segan.toml"
    try:
        stat = config.stat()
    except OSError:
        return ()
    return _extras(str(config), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=16)
def _extras(path: str, size: int, mtime: int) -> tuple[str, ...]:
    import tomllib

    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    names = data.get("sounds", {}).get("extra_licences", []) if isinstance(data.get("sounds"), dict) else []
    return tuple(str(n) for n in names if isinstance(n, str) and n.strip())


def classify(value: object, extra: tuple[str, ...] = ()) -> Licence | None:
    """The allowed licence `value` names, or None (refused: non-commercial, share-alike, unknown...). `extra`: licences
    the project has cleared itself (royalty-free libraries under their own terms); they need a source, not credits."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    for name in extra:
        if text.lower() == name.strip().lower():
            return Licence(name.strip(), "", False, cleared=True)
    if (m := _URL_RE.match(text)) is not None:
        kind, name, version = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if kind == "publicdomain":
            return _CC0 if name == "zero" else None
        return _by(version) if name == "by" and version in BY_VERSIONS else None
    lowered = " ".join(text.lower().replace("_", " ").split())
    if lowered in ("cc0", "cc0 1.0", "cc0-1.0", "cc-0", "creative commons 0", "cc zero", "public domain (cc0)"):
        return _CC0
    if lowered in ("attribution", "cc by", "cc-by", "ccby"):
        return _by(None)
    if (m := re.fullmatch(r"attribution (\d\.\d)", lowered)) is not None and m.group(1) in BY_VERSIONS:
        return _by(m.group(1))
    if (m := _ID_RE.match(text)) is not None:
        version = m.group(1)
        if version is None:
            return _by(None)
        version = version if "." in version else f"{version}.0"
        return _by(version) if version in BY_VERSIONS else None
    return None


ALLOWED_TEXT = "CC0 or CC BY (CC0-1.0, CC-BY-3.0, CC-BY-4.0, or the creativecommons.org URL)"
