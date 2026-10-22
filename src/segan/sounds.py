"""Recorded sounds for SFX: Freesound search, the user cache, the project's `sounds.lock`, credits and vendoring.

- **Freesound** (API v2, token auth with `FREESOUND_API_KEY`): text search (`/apiv2/search/`) and a sound's
  details (`/apiv2/sounds/<id>/`). SEGAN fetches the HQ Ogg Vorbis preview (~192 kbit/s), which the key alone
  allows; originals need an OAuth2 login and aren't fetched. Search keeps only allowed licences (licences.py),
  on the server (a licence filter) and again here.
- **Cache**: fetched files live in `$SEGAN_SOUNDS`, else `$XDG_CACHE_HOME/segan/sounds`, else
  `~/.cache/segan/sounds` (shared by projects, like the sample-library cache). Nothing goes into a project unless
  `segan sounds vendor` copies it to `<project>/sounds/`.
- **sounds.lock** (TOML, next to segan.toml, kept in version control): one `[sounds."<ref>"]` table per sound with
  its name, author, licence, page URL, file kind, download URL and sha256. A build fetches a missing file into the
  cache on first use and checks it against the sha256; a mismatch is an error. Local files can be recorded too
  (licence, source, author), so their origin lives in one place.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from segan.licences import ALLOWED_TEXT, classify

API = "https://freesound.org/apiv2"
FIELDS = "id,name,username,license,duration,avg_rating,num_ratings,tags,previews,url"
LOCK_NAME = "sounds.lock"
VENDOR_DIR = "sounds"
KEY_ENV = "FREESOUND_API_KEY"
PREVIEWS = {"ogg": "preview-hq-ogg", "mp3": "preview-hq-mp3"}
# Freesound's licence names for the search filter (each covers every version: CC BY 3.0 and 4.0 are both "Attribution").
SEARCH_LICENCES = {"cc0": "Creative Commons 0", "cc-by": "Attribution"}
FREESOUND_RE = re.compile(r"^freesound:(\d+)$")
TIMEOUT = 60

_urlopen = urllib.request.urlopen  # tests replace this (no network in tests)


class SoundsError(ValueError):
    """A recorded sound that can't be used or fetched (the message says why and what to run)."""


# --- paths -------------------------------------------------------------------------------------------


def cache_root() -> Path:
    if env := os.environ.get("SEGAN_SOUNDS"):
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "segan" / "sounds"


def freesound_id(ref: str) -> int | None:
    m = FREESOUND_RE.match(ref.strip())
    return int(m.group(1)) if m else None


def lock_key(ref: str, root: Path) -> str:
    """The sounds.lock key of a reference: freesound:<id>, or a local path relative to the project (posix)."""
    if freesound_id(ref) is not None:
        return ref.strip()
    path = Path(ref)
    full = (path if path.is_absolute() else root / path).resolve()
    try:
        return full.relative_to(root.resolve()).as_posix()
    except ValueError:
        return full.as_posix()


def _file_name(sound_id: int, entry: dict[str, Any]) -> str:
    suffix = Path(urllib.parse.urlparse(str(entry.get("download", ""))).path).suffix or ".ogg"
    return f"{sound_id}{suffix}"


def cache_path(sound_id: int, entry: dict[str, Any]) -> Path:
    return cache_root() / "freesound" / _file_name(sound_id, entry)


def vendor_path(root: Path, sound_id: int, entry: dict[str, Any]) -> Path:
    return root / VENDOR_DIR / "freesound" / _file_name(sound_id, entry)


# --- sounds.lock -------------------------------------------------------------------------------------


def read_lock(root: Path) -> dict[str, dict[str, Any]]:
    path = root / LOCK_NAME
    if not path.is_file():
        return {}
    st = path.stat()
    return _read_lock(str(path), st.st_size, st.st_mtime_ns)


@lru_cache(maxsize=8)
def _read_lock(path: str, size: int, mtime: int) -> dict[str, dict[str, Any]]:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise SoundsError(f"{LOCK_NAME}: {exc}") from None
    sounds = data.get("sounds", {})
    if not isinstance(sounds, dict) or not all(isinstance(v, dict) for v in sounds.values()):
        raise SoundsError(f'{LOCK_NAME}: expected [sounds."<ref>"] tables')
    return {str(k): dict(v) for k, v in sounds.items()}


def lock_entry(root: Path, ref: str) -> dict[str, Any] | None:
    return read_lock(root).get(lock_key(ref, root))


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string


ENTRY_ORDER = ("name", "author", "licence", "licence_url", "url", "source", "file", "download", "duration", "sha256")


def write_lock(root: Path, sounds: dict[str, dict[str, Any]]) -> Path:
    lines = ["# Recorded sounds this project uses: written by `segan sounds add`; keep it in version control.",
             "# Builds fetch missing files into the user cache and check each against its sha256.", ""]  # fmt: skip
    for key in sorted(sounds):
        entry = sounds[key]
        lines.append(f"[sounds.{_toml_string(key)}]")
        for field in sorted(entry, key=lambda f: (ENTRY_ORDER.index(f) if f in ENTRY_ORDER else len(ENTRY_ORDER), f)):
            value = entry[field]
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                continue
            lines.append(f"{field} = {_toml_string(value) if isinstance(value, str) else repr(value)}")
        lines.append("")
    path = root / LOCK_NAME
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- checksums and resolving ------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    st = path.stat()
    return _sha256(str(path), st.st_size, st.st_mtime_ns)


@lru_cache(maxsize=1024)
def _sha256(path: str, size: int, mtime: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _check(path: Path, entry: dict[str, Any], ref: str) -> None:
    want = entry.get("sha256")
    if want and sha256_of(path) != want:
        raise SoundsError(f"{ref}: {path} doesn't match its sha256 in {LOCK_NAME} (the file changed or the download is damaged); "
                          f"delete it to fetch it again, or `segan sounds add {ref}` to record the new file")  # fmt: skip


def resolve(ref: str, root: Path) -> Path:
    """The file a recorded-sound reference plays: a local path (relative to the project), or freesound:<id> (vendored
    copy, else the cache, fetched on first use). Checked against sounds.lock's sha256 when it has one."""
    sound_id = freesound_id(ref)
    if sound_id is None:
        if ref.startswith("freesound:"):
            raise SoundsError(f"{ref!r}: a Freesound reference is freesound:<id> (the number in the sound's page URL)")
        path = Path(ref)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            raise SoundsError(f"sample file {ref!r} not found (relative paths start at the project folder: {root})")
        entry = lock_entry(root, ref)
        if entry is not None:
            _check(path, entry, ref)
        return path.resolve()
    entry = lock_entry(root, ref)
    if entry is None:
        raise SoundsError(f"{ref} isn't in {LOCK_NAME}: run `segan sounds add {ref}` (checks its licence, fetches it and records it)")
    vendored = vendor_path(root, sound_id, entry)
    if vendored.is_file():
        _check(vendored, entry, ref)
        return vendored.resolve()
    path = cache_path(sound_id, entry)
    if not path.is_file():
        url = entry.get("download")
        if not isinstance(url, str) or not url:
            raise SoundsError(f"{ref}: no download URL in {LOCK_NAME}; run `segan sounds add {ref}` again")
        data = fetch_bytes(url)
        if entry.get("sha256") and hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SoundsError(f"{ref}: the download from {url} doesn't match its sha256 in {LOCK_NAME} (Freesound may have re-encoded the "
                              f"preview); listen again and `segan sounds add {ref}` to record the new file")  # fmt: skip
        _save(path, data)
    _check(path, entry, ref)
    return path.resolve()


def _save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    part.replace(path)


# --- Freesound API ----------------------------------------------------------------------------------


def api_key() -> str:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise SoundsError(f"{KEY_ENV} isn't set: Freesound search and fetching need an API key (free: https://freesound.org/apiv2/apply, "
                          f"then export {KEY_ENV}=<key>). Without one: find a sound on freesound.org, check it's {ALLOWED_TEXT}, download "
                          "it into the project and use it as a local file (sample: sounds/x.wav with licence, source and author)")  # fmt: skip
    return key


def _request(url: str, key: str | None) -> bytes:
    headers = {"User-Agent": "segan"}
    host = urllib.parse.urlparse(url).hostname or ""
    if key and (host == "freesound.org" or host.endswith(".freesound.org")):
        headers["Authorization"] = f"Token {key}"  # only ever sent to Freesound
    request = urllib.request.Request(url, headers=headers)
    try:
        with _urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (https URLs from Freesound)
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        reason = {401: f"the API key was refused (check {KEY_ENV})", 403: "not allowed", 404: "not found", 429: "rate limited: wait and try again"}
        raise SoundsError(f"Freesound: {reason.get(exc.code, f'HTTP {exc.code}')} ({urllib.parse.urlparse(url).path})") from None
    except (urllib.error.URLError, OSError) as exc:
        raise SoundsError(f"Freesound: can't reach {host} ({getattr(exc, 'reason', exc)})") from None


def fetch_bytes(url: str) -> bytes:
    """A file from Freesound (a preview); the key is sent when one is set (previews don't need one today)."""
    return _request(url, os.environ.get(KEY_ENV, "").strip() or None)


def _api(path: str, params: dict[str, Any]) -> Any:
    key = api_key()
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        return json.loads(_request(url, key))
    except ValueError:
        raise SoundsError(f"Freesound: {path} didn't return JSON") from None


def _licence_filter(licences: tuple[str, ...]) -> str:
    names = [SEARCH_LICENCES[name] for name in licences]
    return "license:(" + " OR ".join(f'"{n}"' for n in names) + ")"


def search(query: str, max_seconds: float | None = None, licences: tuple[str, ...] = ("cc0", "cc-by"), limit: int = 15,
           sort: str = "score") -> dict[str, Any]:  # fmt: skip
    """Freesound text search, allowed licences only: {"count": total matches, "results": [...], "refused": n}."""
    unknown = [name for name in licences if name not in SEARCH_LICENCES]
    if unknown or not licences:
        raise SoundsError(f"licence must be {' or '.join(SEARCH_LICENCES)} (nothing else is allowed)")
    filters = [_licence_filter(licences)]
    if max_seconds is not None:
        filters.append(f"duration:[0 TO {max_seconds:g}]")
    data = _api("search/", {"query": query, "filter": " ".join(filters), "fields": FIELDS, "page_size": max(1, min(150, limit)), "sort": sort})
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SoundsError("Freesound: unexpected search response")
    results, refused = [], 0
    for item in data["results"]:
        row = describe(item)
        lid = row["licence_id"] if row is not None else None
        if row is None or lid is None or ("cc0" if lid == "CC0-1.0" else "cc-by") not in licences:
            refused += 1  # the server filter should have dropped it: never trust it alone
            continue
        results.append(row)
    return {"count": int(data.get("count", len(results))), "results": results[:limit], "refused": refused}


def describe(item: Any) -> dict[str, Any] | None:
    """A Freesound sound (API fields) as SEGAN lists it; None if it isn't a sound record."""
    if not isinstance(item, dict) or not isinstance(item.get("id"), int):
        return None
    licence = classify(item.get("license"))
    tags = item.get("tags")
    sound_id = int(item["id"])
    return {
        "ref": f"freesound:{sound_id}",
        "id": sound_id,
        "name": str(item.get("name", "")),
        "author": str(item.get("username", "")),
        "licence": licence.title if licence else None,
        "licence_id": licence.id if licence else None,
        "licence_url": licence.url if licence else None,
        "licence_given": item.get("license"),
        "duration": round(float(item.get("duration") or 0.0), 3),
        "rating": round(float(item.get("avg_rating") or 0.0), 2),
        "ratings": int(item.get("num_ratings") or 0),
        "tags": [str(t) for t in tags] if isinstance(tags, list) else [],
        "url": str(item.get("url") or f"https://freesound.org/s/{sound_id}/"),
        "previews": item.get("previews") if isinstance(item.get("previews"), dict) else {},
    }


def sound_info(sound_id: int) -> dict[str, Any]:
    data = _api(f"sounds/{sound_id}/", {"fields": FIELDS})
    row = describe(data)
    if row is None:
        raise SoundsError(f"Freesound: unexpected response for sound {sound_id}")
    return row


def fetch_freesound(sound_id: int, fmt: str = "ogg") -> tuple[Path, dict[str, Any], str]:
    """Fetch a sound's HQ preview into the cache (licence checked first): (path, details, download URL)."""
    row = sound_info(sound_id)
    if row["licence_id"] is None:
        raise SoundsError(f"freesound:{sound_id} ({row['name']!r}) is under {row['licence_given']!r}: not allowed; only {ALLOWED_TEXT}")
    url = row["previews"].get(PREVIEWS[fmt])
    if not isinstance(url, str) or not url.startswith("https://"):
        raise SoundsError(f"freesound:{sound_id}: no {PREVIEWS[fmt]} preview in the API response")
    data = fetch_bytes(url)
    path = cache_path(sound_id, {"download": url})
    _save(path, data)
    return path, row, url


# --- adding, credits, vendoring --------------------------------------------------------------------


def add(ref: str, root: Path, fmt: str = "ogg", licence: str | None = None, source: str | None = None, author: str | None = None,
        name: str | None = None) -> tuple[str, dict[str, Any]]:  # fmt: skip
    """Record a sound in sounds.lock (Freesound: fetched into the cache; a local file: its licence, source, author)."""
    from segan.recorded import RECORDED_SUFFIXES

    sounds = read_lock(root)
    sound_id = freesound_id(ref)
    if sound_id is not None:
        if licence or source or author:
            raise SoundsError("--licence/--source/--author are for local files: Freesound says who made a sound and under which licence")
        path, row, url = fetch_freesound(sound_id, fmt)
        lic = classify(row["licence_given"])
        assert lic is not None
        entry: dict[str, Any] = {"name": name or row["name"], "author": row["author"], "licence": lic.id, "licence_url": lic.url, "url": row["url"],
                                 "file": PREVIEWS[fmt], "download": url, "duration": row["duration"], "sha256": sha256_of(path)}  # fmt: skip
        key = ref.strip()
    else:
        path = Path(ref)
        path = path if path.is_absolute() else root / path
        if not path.is_file():
            raise SoundsError(f"no such file: {ref} (relative paths start at the project folder: {root})")
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            raise SoundsError(f"{ref} is outside the project: copy it in first (e.g. into {VENDOR_DIR}/)") from None
        if path.suffix.lower() not in RECORDED_SUFFIXES:
            raise SoundsError(f"{ref}: SEGAN plays {', '.join(RECORDED_SUFFIXES)} files")
        lic = classify(licence)
        if lic is None:
            raise SoundsError(f"--licence {licence!r} isn't allowed: only {ALLOWED_TEXT}" if licence else f"--licence is required for a local file: {ALLOWED_TEXT}")
        if not source:
            raise SoundsError('--source is required: the page the sound came from (or "own recording")')
        if lic.attribution and not author:
            raise SoundsError(f"--author is required for {lic.title}: the credits must name who made it")
        entry = {"name": name or path.stem, "licence": lic.id, "licence_url": lic.url, "source": source, "file": "local", "sha256": sha256_of(path)}
        if author:
            entry["author"] = author
        key = lock_key(ref, root)
    sounds[key] = entry
    write_lock(root, sounds)
    return key, entry


def credit_line(ref: str, entry: dict[str, Any], used_in: list[str]) -> str:
    """TASL attribution: title, author, source, licence, and the changes made."""
    lic = classify(entry.get("licence")) or classify(entry.get("licence_url"))
    title = entry.get("name") or ref
    author = entry.get("author")
    source = entry.get("url") or entry.get("source")
    parts = [f'"{title}"' + (f" by {author}" if author else "")]
    if source:
        parts[0] += f" ({source})" if str(source).startswith("http") else f", {source}"
    if lic is not None:
        parts.append(f"licensed under {lic.title} ({lic.url})")
    line = ", ".join(parts) + "."
    if lic is not None and lic.attribution:
        line += " Modified: edited, processed and mixed into the game's sound effects."
    if used_in:
        line += f" Used in: {', '.join(sorted(used_in))}."
    return f"- {line}"


def credits_text(entries: dict[str, dict[str, Any]], used: dict[str, list[str]]) -> str:
    by = {k: v for k, v in entries.items() if (lic := classify(v.get("licence"))) is not None and lic.attribution}
    cc0 = {k: v for k, v in entries.items() if k not in by}
    lines = ["# Sound credits", "", "Recorded sounds in this game's sound effects (written by `segan sounds credits` from sounds.lock).", ""]
    if by:
        lines += ["## Attribution required (CC BY)", ""] + [credit_line(k, by[k], used.get(k, [])) for k in sorted(by)] + [""]
    if cc0:
        lines += ["## Public domain (CC0, credit not required)", ""] + [credit_line(k, cc0[k], used.get(k, [])) for k in sorted(cc0)] + [""]
    if not entries:
        lines += ["No recorded sounds.", ""]
    return "\n".join(lines)


def vendor(root: Path, refs: list[str]) -> list[tuple[str, Path]]:
    """Copy Freesound sounds (from the cache, fetched if needed) into <project>/sounds/freesound/."""
    copied = []
    for ref in sorted(set(refs)):
        sound_id = freesound_id(ref)
        if sound_id is None:
            continue  # local files are in the project already
        entry = lock_entry(root, ref)
        if entry is None:
            raise SoundsError(f"{ref} isn't in {LOCK_NAME}: run `segan sounds add {ref}` first")
        target = vendor_path(root, sound_id, entry)
        if target.is_file():
            _check(target, entry, ref)
            continue
        source = resolve(ref, root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append((ref, target))
    return copied
