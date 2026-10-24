"""Sample libraries SEGAN knows how to fetch: SFZ maps shipped with SEGAN over audio downloaded on demand.

Each library folder (`libraries/<name>/`) has `library.json` (source repository, pinned commit, licence, every
instrument's files and every file's size and git blob id) and one `<instrument>.sfz` per instrument whose
`sample=` paths are relative to the repository root. A library gathered from several repositories names them in
`sources` ({alias: {repo, commit}}); its file paths then start with the alias (`emily/notes/a2_f_rr1.wav`). `segan samples fetch <library> [instruments]` downloads
only the files those instruments use, from the pinned commit, checks each against its blob id and keeps them
in the user cache (`$SEGAN_SAMPLES`, else `$XDG_CACHE_HOME/segan/samples`, else `~/.cache/segan/samples`),
shared by every project. Nothing is bundled: the audio is the library author's, under their licence.
"""

from __future__ import annotations

import re

import json
import os
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from segan.samples import SampleSpec, blob_sha1

HERE = Path(__file__).parent


class LibraryError(ValueError):
    """Unknown library/instrument, or samples not downloaded (the message says what to run)."""


@dataclass(frozen=True)
class Library:
    name: str
    title: str
    repo: str
    commit: str
    license: str
    url: str
    credit: str
    instruments: dict[str, dict[str, Any]]
    files: dict[str, tuple[int, str]]  # path -> (size, git blob sha1)
    sources: tuple[tuple[str, str, str], ...] = ()  # (alias, repo, commit) when gathered from several repositories

    @property
    def pin(self) -> str:
        """What the cache folder is named after: the commit, or every source's commit together."""
        if not self.sources:
            return self.commit[:12]
        import hashlib

        return hashlib.sha1("\n".join(f"{a} {r} {c}" for a, r, c in sorted(self.sources)).encode()).hexdigest()[:12]

    def origin(self, path: str) -> tuple[str, str, str]:
        """(repo, commit, path in that repo) of a library file."""
        if not self.sources:
            return self.repo, self.commit, path
        alias, _, rest = path.partition("/")
        for name, repo, commit in self.sources:
            if name == alias:
                return repo, commit, rest
        raise LibraryError(f"{self.name}: {path} names no source")

    @property
    def folder(self) -> Path:
        return HERE / self.name

    @property
    def cache(self) -> Path:
        return cache_root() / self.name / self.pin

    def sfz(self, instrument: str) -> Path:
        return self.folder / f"{instrument}.sfz"

    def missing(self, instrument: str) -> list[str]:
        return [f for f in self.instruments[instrument]["files"] if not (self.cache / f).is_file()]

    def size(self, instrument: str) -> int:
        return sum(self.files[f][0] for f in self.instruments[instrument]["files"])

    def key_range(self, instrument: str) -> tuple[int, int] | None:
        """Lowest and highest MIDI key the instrument's SFZ maps (read from the bundled map, no audio needed);
        None for unpitched instruments (pitch_keytrack=0: every key plays the same sound)."""
        text = self.sfz(instrument).read_text(encoding="utf-8")
        if re.search(r"\bpitch_keytrack=0\b", text):
            return None
        low = [int(v) for v in re.findall(r"\blokey=(\d+)", text)]
        high = [int(v) for v in re.findall(r"\bhikey=(\d+)", text)]
        return (min(low), max(high)) if low and high else None


def cache_root() -> Path:
    if env := os.environ.get("SEGAN_SAMPLES"):
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "segan" / "samples"


def names() -> list[str]:
    return sorted(p.parent.name for p in HERE.glob("*/library.json"))


@lru_cache(maxsize=8)
def library(name: str) -> Library:
    path = HERE / name / "library.json"
    if not path.is_file():
        raise LibraryError(f"unknown sample library {name!r} (libraries: {', '.join(names()) or 'none'})")
    data = json.loads(path.read_text(encoding="utf-8"))
    files = {k: (int(v[0]), str(v[1])) for k, v in data["files"].items()}
    sources = tuple((str(a), str(v["repo"]), str(v["commit"])) for a, v in sorted(data.get("sources", {}).items()))
    return Library(name, data["title"], data["repo"], data["commit"], data["license"], data["url"], data["credit"], data["instruments"], files, sources)


def library_spec(lib_name: str, instrument: str) -> SampleSpec:
    """The SFZ spec of a library instrument; LibraryError if it's unknown or not downloaded."""
    lib = library(lib_name)
    if instrument not in lib.instruments:
        raise LibraryError(f"{lib_name} has no instrument {instrument!r} (`segan samples list {lib_name}` shows them: {', '.join(sorted(lib.instruments))})")
    missing = lib.missing(instrument)
    if missing:
        total = len(lib.instruments[instrument]["files"])
        raise LibraryError(f"{lib_name}/{instrument}: {len(missing)} of {total} samples aren't downloaded; run `segan samples fetch {lib_name} {instrument}` "
                           f"({lib.size(instrument) / 1e6:.0f} MB, {lib.license}, into {lib.cache})")  # fmt: skip
    return SampleSpec("library", str(lib.sfz(instrument)), base=str(lib.cache), stamp=((f"{lib_name}@{lib.pin}", 0, 0),))


def raw_url(lib: Library, path: str) -> str:
    repo, commit, inner = lib.origin(path)
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{urllib.parse.quote(inner)}"


def fetch(lib: Library, instruments: list[str], progress: Callable[[str], None] | None = None, workers: int = 8) -> tuple[int, int]:
    """Download the instruments' missing files (verified by size and git blob id). Returns (files fetched,
    bytes fetched). Raises LibraryError for an unknown instrument or a file that fails its check."""
    unknown = [i for i in instruments if i not in lib.instruments]
    if unknown:
        raise LibraryError(f"{lib.name} has no instrument(s) {', '.join(unknown)} (instruments: {', '.join(sorted(lib.instruments))})")
    wanted = sorted({f for i in instruments for f in lib.instruments[i]["files"] if not (lib.cache / f).is_file()})

    def get(path: str) -> int:
        size, sha = lib.files[path]
        try:
            with urllib.request.urlopen(raw_url(lib, path), timeout=120) as response:  # noqa: S310 (fixed https host)
                data = response.read()
        except OSError as exc:
            raise LibraryError(f"downloading {path} failed: {exc}") from None
        if len(data) != size or blob_sha1(data) != sha:
            raise LibraryError(f"{path}: the download doesn't match the pinned file (size {len(data)} vs {size}); try again")
        target = lib.cache / path
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        part.replace(target)
        if progress is not None:
            progress(path)
        return size

    with ThreadPoolExecutor(max_workers=workers) as pool:
        sizes = list(pool.map(get, wanted))
    return len(wanted), sum(sizes)
