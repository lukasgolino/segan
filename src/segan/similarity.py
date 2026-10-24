"""How alike songs are (#76): fingerprints from the source, pairwise similarity, and the stores they are
compared with.

A song's fingerprint is read from its notes, not its audio (fast, exact, the same on every machine):
- the **opening**: the pitches sounding on the first step of the arrangement;
- **harmony**: a duration-weighted pitch-class profile (chroma) per bar for the first `BARS` bars;
- **rhythm**: note onsets per bar on a 16-slot grid;
- **register**: the duration-weighted mean pitch and the range;
- **timbre**: a small descriptor per instrument played (its source family, brightness, envelope, unison);
- the key's pitch set, tempo, meter and kit.

Similarity is 0..1 per aspect and overall. Songs are compared with the other songs of the project (lint W021-
W024, `segan similarity`, the preview's closest song), with SEGAN's own examples and templates shipped in
`fingerprints/` (W025) and, when `[similarity] local_store = true`, with songs from other projects on this
machine (`~/.cache/segan/fingerprints/`, W026).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from segan.patch import Instrument
from segan.song import Song

BARS = 8
SLOTS = 16  # onset grid per bar
VERSION = 1
WEIGHTS = {"harmony": 0.35, "rhythm": 0.25, "timbre": 0.2, "register": 0.12, "tempo": 0.08}
FAMILIES = ("pulse", "saw", "soft", "noise", "fm", "pluck", "bowed", "additive", "wavetable", "formant", "modal", "supersaw", "drum", "sample")


@dataclass
class Fingerprint:
    name: str
    project: str  # the project folder (or "segan" for shipped examples)
    key: str
    pitch_set: list[int]  # the key's pitch classes
    tempo: float
    meter: list[int]
    kit: str
    opening: list[int]  # MIDI notes sounding on step 1
    chroma: list[list[float]]  # per bar, 12 values summing to 1 (empty bar: zeros)
    onsets: list[list[int]]  # per bar: SLOTS onset counts of pitched notes, then SLOTS of drum hits
    register: list[float]  # mean, low, high (MIDI)
    timbre: list[list[float]]  # per instrument played
    path: str = ""
    version: int = VERSION

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fingerprint:
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    def label(self, home: str = "") -> str:
        """The song's name; with the project folder when it's from another project, `segan:` for shipped ones."""
        if self.project == "segan":
            return f"segan:{self.name}"
        return self.name if self.project in ("", home) else f"{Path(self.project).name}/{self.name}"


def family(inst: Instrument) -> str:
    if inst.is_drum:
        return "drum"
    if inst.is_sample:
        return "sample"
    if inst.wave in ("sine", "triangle"):
        return "soft"
    if inst.wave == "bitnoise":
        return "noise"
    return inst.wave if inst.wave in FAMILIES else "soft"


def timbre_of(inst: Instrument) -> list[float]:
    """One-hot source family + brightness (filter cutoff, log), attack and release (log), unison, sample identity."""
    vec = [1.0 if family(inst) == f else 0.0 for f in FAMILIES]
    cutoff = inst.filter.cutoff if inst.filter is not None and inst.filter.type == "lp" else 12000.0
    vec.append(math.log2(max(cutoff, 50.0) / 50.0) / 8.0)
    vec.append(math.log10(max(inst.env.attack, 0.001) / 0.001) / 3.5)
    vec.append(math.log10(max(inst.env.release, 0.01) / 0.01) / 3.0)
    vec.append(min(inst.unison, 8) / 8.0)
    sample = inst.sample.path if inst.sample is not None else ""
    vec.append((int(hashlib.sha1(sample.encode()).hexdigest()[:6], 16) % 1000) / 1000.0 if sample else 0.0)
    return [round(v, 4) for v in vec]


def fingerprint(song: Song, project_root: str = "") -> Fingerprint:
    from segan.sequence import build_timeline, placed_notes

    timeline = build_timeline(song)
    placed = placed_notes(song, timeline)
    per_bar = timeline.steps_per_bar
    chroma = [[0.0] * 12 for _ in range(BARS)]
    onsets = [[0] * (2 * SLOTS) for _ in range(BARS)]
    weight_sum = 0.0
    pitch_sum = 0.0
    low, high = 127.0, 0.0
    opening: set[int] = set()
    used: dict[str, Instrument] = {}
    for p in placed:
        inst = song.kit.instruments.get(p.key)
        if inst is not None:
            used[p.key] = inst
        drums = song.tracks[p.note.track].drums
        bar = p.step // per_bar
        if bar < BARS:
            onsets[bar][min(SLOTS - 1, (p.step % per_bar) * SLOTS // per_bar) + (SLOTS if drums else 0)] += 1
        if drums:
            continue
        if p.step == 0:
            opening.add(int(p.midi))
        length = p.note.length
        for step in range(p.step, p.step + length):
            b = step // per_bar
            if b < BARS:
                chroma[b][int(p.midi) % 12] += 1.0
        weight_sum += length
        pitch_sum += p.midi * length
        low, high = min(low, p.midi), max(high, p.midi)
    for row in chroma:
        total = sum(row)
        if total:
            row[:] = [round(v / total, 4) for v in row]
    register = [round(pitch_sum / weight_sum, 2), low, high] if weight_sum else [60.0, 60.0, 60.0]
    kit = song.kit.name or "inline"
    return Fingerprint(song.name, project_root, song.key.describe(), sorted({(song.key.root + i) % 12 for i in song.key.intervals}), song.tempo,
                       list(song.meter), kit, sorted(opening), chroma, onsets, register, [timbre_of(i) for _, i in sorted(used.items())],
                       str(song.path or ""))  # fmt: skip


# --- comparing ----------------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float | None:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return None
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def harmony(a: Fingerprint, b: Fingerprint) -> float:
    """Bar-by-bar chroma agreement over the first bars, half weighted with the overall profile."""
    bars = [c for x, y in zip(a.chroma, b.chroma, strict=False) if (c := _cosine(x, y)) is not None]
    whole = _cosine([sum(r[i] for r in a.chroma) for i in range(12)], [sum(r[i] for r in b.chroma) for i in range(12)])
    if not bars or whole is None:
        return 0.0
    return 0.6 * sum(bars) / len(bars) + 0.4 * whole


def rhythm(a: Fingerprint, b: Fingerprint) -> float:
    """Bar-by-bar agreement of where notes start (pitched parts and drums separately, by how many start there)."""
    scores = []
    for x, y in zip(a.onsets, b.onsets, strict=False):
        for part in (slice(0, SLOTS), slice(SLOTS, 2 * SLOTS)):
            c = _cosine([float(v) for v in x[part]], [float(v) for v in y[part]])
            if c is not None:
                scores.append(c**2)  # squared: two busy grids that only partly agree shouldn't look alike
            elif any(x[part]) or any(y[part]):
                scores.append(0.0)
    return sum(scores) / len(scores) if scores else 0.0


def timbre(a: Fingerprint, b: Fingerprint) -> float:
    """Each instrument of one song matched to its nearest in the other, both ways."""
    if not a.timbre or not b.timbre:
        return 0.0

    def near(x: list[float], pool: list[list[float]]) -> float:
        return max(1.0 - min(1.0, math.dist(x, y) / 1.5) for y in pool)

    there = sum(near(x, b.timbre) for x in a.timbre) / len(a.timbre)
    back = sum(near(y, a.timbre) for y in b.timbre) / len(b.timbre)
    return (there + back) / 2


def register(a: Fingerprint, b: Fingerprint) -> float:
    mean = 1.0 - min(1.0, abs(a.register[0] - b.register[0]) / 12.0)
    lo, hi = max(a.register[1], b.register[1]), min(a.register[2], b.register[2])
    span = max(a.register[2], b.register[2]) - min(a.register[1], b.register[1])
    overlap = max(0.0, hi - lo) / span if span > 0 else 1.0
    return 0.6 * mean + 0.4 * overlap


def tempo(a: Fingerprint, b: Fingerprint) -> float:
    return 1.0 - min(1.0, abs(a.tempo - b.tempo) / 30.0) if a.meter == b.meter else 0.3 * (1.0 - min(1.0, abs(a.tempo - b.tempo) / 30.0))


@dataclass(frozen=True)
class Similarity:
    a: str
    b: str
    overall: float
    parts: dict[str, float] = field(default_factory=dict)
    same_opening: bool = False
    same_pitch_set: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"a": self.a, "b": self.b, "overall": round(self.overall, 3), **{k: round(v, 3) for k, v in self.parts.items()},
                "same_opening": self.same_opening, "same_pitch_set": self.same_pitch_set}  # fmt: skip


def compare(a: Fingerprint, b: Fingerprint, home: str | None = None) -> Similarity:
    parts = {"harmony": harmony(a, b), "rhythm": rhythm(a, b), "timbre": timbre(a, b), "register": register(a, b), "tempo": tempo(a, b)}
    overall = sum(WEIGHTS[k] * v for k, v in parts.items())
    base = a.project if home is None else home
    return Similarity(a.label(base), b.label(base), overall, parts, bool(a.opening) and a.opening == b.opening, a.pitch_set == b.pitch_set)


def opening_score(s: Similarity) -> float:
    """How alike the first bars are (W024): harmony and rhythm, with the instruments as a tie-breaker."""
    return 0.5 * s.parts["harmony"] + 0.35 * s.parts["rhythm"] + 0.15 * s.parts["timbre"]


def matrix(prints: list[Fingerprint]) -> list[Similarity]:
    return [compare(a, b) for i, a in enumerate(prints) for b in prints[i + 1 :]]


def closest(target: Fingerprint, pool: list[Fingerprint]) -> Similarity | None:
    found = [compare(target, other) for other in pool if (other.project, other.name) != (target.project, target.name)]
    return max(found, key=lambda s: s.overall, default=None)


# --- stores -------------------------------------------------------------------------------------


def shipped() -> list[Fingerprint]:
    """Fingerprints of SEGAN's own examples and templates (scripts/make_fingerprints.py)."""
    try:
        data = json.loads(files("segan").joinpath("fingerprints", "shipped.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError):
        return []
    return [Fingerprint.from_dict(d) for d in data.get("songs", [])]


def reference_example(reference: Path) -> str:
    """The generator script in reference.md's `segan.api` section (the example every agent sees first)."""
    text = reference.read_text(encoding="utf-8")
    section = text[text.index("## Generator scripts: `segan.api`") :]
    return section[section.index("```python") + len("```python") : section.index("```", section.index("```python") + 9)]


def make_shipped(repo: Path) -> dict[str, Any]:
    """Fingerprints of the demo project's songs and of reference.md's generator example (run against the demo's kits)."""
    import runpy
    import shutil
    import tempfile

    from segan.asset import load_asset
    from segan.project import load_project

    def prints(root: Path, prefix: str) -> list[Fingerprint]:
        project = load_project(root)
        out = []
        for path in sorted((root / "music").glob("*.song.yaml")):
            song, _ = load_asset(path, project)
            if song is not None and not song.meta.template:
                fp = fingerprint(song, "segan")
                fp.name, fp.path = f"{prefix}/{song.name}", ""
                out.append(fp)
        return out

    demo = repo / "examples" / "demo"
    songs = prints(demo, "demo")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "demo"
        shutil.copytree(demo, work, ignore=shutil.ignore_patterns("previews", ".segan-cache", "build", "music"))
        (work / "music").mkdir()
        script = Path(tmp) / "example.py"
        script.write_text(reference_example(repo / "src" / "segan" / "skill" / "reference.md"), encoding="utf-8")
        cwd = os.getcwd()
        try:
            os.chdir(work)
            runpy.run_path(str(script))
        finally:
            os.chdir(cwd)
        songs += prints(work, "reference")
    return {"version": VERSION, "songs": [p.to_dict() for p in songs]}


def store_dir() -> Path:
    if env := os.environ.get("SEGAN_FINGERPRINTS"):
        return Path(env)
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "segan" / "fingerprints"


def _store_file(root: Path) -> Path:
    return store_dir() / f"{hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]}.json"


def save_local(root: Path, prints: list[Fingerprint]) -> Path:
    """This project's song fingerprints in the machine's store (replacing what was there for the project)."""
    path = _store_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": VERSION, "project": str(root.resolve()), "songs": [p.to_dict() for p in sorted(prints, key=lambda p: p.name)]}
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return path


def other_projects(root: Path) -> list[Fingerprint]:
    """Songs of every other project in the machine's store (projects whose folder is gone are skipped)."""
    folder = store_dir()
    if not folder.is_dir():
        return []
    mine = _store_file(root)
    out: list[Fingerprint] = []
    for path in sorted(folder.glob("*.json")):
        if path == mine:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("version") != VERSION or not Path(str(data.get("project", ""))).is_dir():
            continue
        out += [Fingerprint.from_dict(d) for d in data.get("songs", [])]
    return out


# --- lint ---------------------------------------------------------------------------------------

TEMPO_BAND = 10.0  # bpm: W022 counts songs within one band


def sameness_findings(project: Any, songs: dict[str, Song], linted: set[str]) -> list[Any]:
    """W021-W026 for the songs being linted, compared with every song of the project (and shipped/local songs)."""
    from segan.findings import Finding

    root = str(project.root)
    prints = {name: fingerprint(song, root) for name, song in sorted(songs.items()) if not song.meta.template}
    out: list[Finding] = []
    limit = project.config.lint.max_similarity

    def path(name: str) -> Path | None:
        return songs[name].path

    names = list(prints)
    for name in names:
        if name not in linted:
            continue
        mine = prints[name]
        same = [o for o in names if o != name and mine.opening and len(mine.opening) >= 2 and prints[o].opening == mine.opening]
        if same:
            notes = " ".join(songs[name].key.name(m) for m in mine.opening)
            out.append(Finding("W021", f"opens on the same notes as {', '.join(same)} ({notes} on step 1): songs that start alike blur into one. Open "
                               "on another chord, inversion or register, or with a different texture (a lone line, drums first, a pedal note)",
                               path(name), None, "patterns"))  # fmt: skip
        pairs = sorted(((opening_score(compare(mine, prints[o])), o) for o in names if o != name), reverse=True)
        if pairs and pairs[0][0] >= limit:
            score, other = pairs[0]
            out.append(Finding("W024", f"its first {BARS} bars are {score:.0%} like {other}'s (harmony, rhythm and instruments; lint.max_similarity "
                               f"{limit:g}): `segan similarity {name} {other}` shows how. Change the progression, the rhythm or the instruments",
                               path(name), None, "patterns"))  # fmt: skip
        for pool, rule, what in ((shipped() if project.config.similarity.shipped else [], "W025", "SEGAN's example or template"),
                                 (other_projects(project.root) if project.config.similarity.local_store else [], "W026", "a song in another project")):
            best = max(((opening_score(compare(mine, other)), other) for other in pool), key=lambda x: x[0], default=None)
            if best is not None and (best[0] >= limit or mine.opening and len(mine.opening) >= 2 and mine.opening == best[1].opening):
                out.append(Finding(rule, f"is close to {what} {best[1].label(root)} ({best[0]:.0%} alike in its first {BARS} bars"
                                   + (", same opening notes" if mine.opening == best[1].opening else "") + "): defaults and examples are where "
                                   "every project starts, so move away from them (key, progression, rhythm, instruments)", path(name), None, "patterns"))  # fmt: skip
    if len(prints) >= 3 and linted & set(prints):
        where = project.config_path
        sets: dict[tuple[int, ...], list[str]] = {}
        for name, p in prints.items():
            sets.setdefault(tuple(p.pitch_set), []).append(name)
        common = max(sets.values(), key=len)
        if len(common) * 2 > len(prints):
            keys = sorted({songs[n].key.describe() for n in common})
            out.append(Finding("W022", f"{len(common)} of {len(prints)} songs use the same notes ({', '.join(keys)}: one pitch set): vary key and mode "
                               "between songs (relative keys like D minor and F major count as the same)", where, None, "music"))  # fmt: skip
        tempos = sorted(p.tempo for p in prints.values())
        band = max((sum(1 for t in tempos if lo <= t <= lo + TEMPO_BAND), lo) for lo in tempos)
        if band[0] * 2 > len(prints):
            out.append(Finding("W022", f"{band[0]} of {len(prints)} songs are within {TEMPO_BAND:g} bpm of each other ({band[1]:g}-{band[1] + TEMPO_BAND:g}): "
                               "vary tempo (and meter) between songs", where, None, "music"))  # fmt: skip
        kits = {p.kit for p in prints.values()}
        used = [songs[n].used_keys() for n in prints]
        overlap = [len(x & y) / len(x | y) for i, x in enumerate(used) for y in used[i + 1 :] if x | y]
        if len(kits) == 1 and overlap and sum(overlap) / len(overlap) > 0.7:
            out.append(Finding("W023", f"all {len(prints)} songs play one kit ({next(iter(kits))}) with nearly the same instruments: keep the game's "
                               "signature instruments, and give each song extras of its own (more instruments in the kit, a second kit, "
                               "`segan kit roll`)", where, None, "music"))  # fmt: skip
    return out
