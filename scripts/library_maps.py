"""Shared by the sample-library generators (make_vcsl_library.py, make_karoryfer_library.py): pin repositories,
download the curated instruments into the SEGAN sample cache (verified by git blob id), measure each folder's octave
labelling and each sample's lead-in, level each instrument, and write one SFZ per instrument plus library.json.

The measuring helpers come from make_vsco2_library.py (the first library, written before this module).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from make_vsco2_library import DYNAMICS, REFERENCE_LUFS, layer_bounds, lead_in, loudness, measured_midi  # noqa: E402

from segan.analysis import spectral_centroid  # noqa: E402
from segan.libraries import Library, fetch  # noqa: E402
from segan.samples import _wav_audio, sfz_key, wav_info  # noqa: E402

PEAK_CEILING = 0.7  # short hits measure quiet in LUFS: the plain-velocity sample's peak may not go above this after levelling
NOTE_RE = re.compile(r"(?:^|[_ ])([A-Ga-g][#b]?-?\d)(?=[_ .]|$)")
Parser = Callable[[str], tuple[int | None, int, int]]


@dataclass(frozen=True)
class Inst:
    folder: str  # in the repository (multi-source: starting with the source alias)
    pattern: str  # regex on the file name
    kind: str  # sus (held), shot (rings to its end), hit (unpitched)
    release: float
    description: str
    parser: Parser | None = None  # file name -> (note, dynamic rank, round robin)
    octave: int | None = None  # force the label's octave shift (when the measurement can't be trusted)


@dataclass
class Spec:
    name: str
    title: str
    credit: str
    url: str
    license: str
    sources: list[tuple[str, str, str]]  # (alias, repo, commit); one source with alias "" = paths as in the repository
    instruments: dict[str, Inst]
    licence_text: str
    script: str
    extra: dict[str, str] = field(default_factory=dict)


def tree(repo: str, commit: str) -> dict[str, tuple[int, str]]:
    out = subprocess.run(["gh", "api", f"repos/{repo}/git/trees/{commit}?recursive=1"], check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    assert not data.get("truncated"), "tree truncated"
    return {t["path"]: (int(t["size"]), t["sha"]) for t in data["tree"] if t["type"] == "blob"}


def parse_name(base: str) -> tuple[int | None, int, int]:
    """(labelled MIDI note or None, dynamic rank, round robin) from a file name: `A#3`, `gb5`; `v2`, `vl10`, `mf`; `rr2`."""
    stem = base.rsplit(".", 1)[0]
    m = NOTE_RE.search(stem)
    note = sfz_key(m.group(1)[0].upper() + m.group(1)[1:]) if m else None
    vel = 0
    if v := re.search(r"(?:^|_)vl?(\d+)(?=_|$)", stem):
        vel = int(v.group(1))
    else:
        for token in re.split(r"[_\- ]", stem):
            if token.lower() in DYNAMICS:
                vel = DYNAMICS[token.lower()]
    rr = 1
    if r := re.search(r"(?:^|[_ ])r[r]?(\d+)", stem, re.I):
        rr = int(r.group(1))
    return note, vel, rr


def build(spec: Spec, out: Path) -> None:
    all_files: dict[str, tuple[int, str]] = {}
    for alias, repo, commit in spec.sources:
        for path, info in tree(repo, commit).items():
            all_files[f"{alias}/{path}" if alias else path] = info
    chosen: dict[str, list[str]] = {}
    for name, inst in spec.instruments.items():
        rx = re.compile(inst.pattern)
        chosen[name] = sorted(p for p in all_files if p.rpartition("/")[0] == inst.folder and p.lower().endswith(".wav") and rx.search(p.rpartition("/")[2]))
        assert chosen[name], f"{name}: no files"
    used = sorted({f for files in chosen.values() for f in files})
    instruments = {name: {"description": spec.instruments[name].description, "kind": spec.instruments[name].kind, "files": files} for name, files in chosen.items()}
    multi = len(spec.sources) > 1 or bool(spec.sources[0][0])
    sources = tuple((a, r, c) for a, r, c in spec.sources) if multi else ()
    repo = "several" if multi else spec.sources[0][1]
    commit = "several" if multi else spec.sources[0][2]
    lib = Library(spec.name, spec.title, repo, commit, spec.license, spec.url, spec.credit, instruments, {f: all_files[f] for f in used}, sources)
    print(f"{len(used)} files, {sum(all_files[f][0] for f in used) / 1e6:.0f} MB; fetching what's missing into {lib.cache}")
    count, size = fetch(lib, list(instruments), progress=lambda p: print("  got", p))
    print(f"fetched {count} files ({size / 1e6:.0f} MB)")
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.sfz"):
        old.unlink()
    for name, files in chosen.items():
        inst = spec.instruments[name]
        parse = inst.parser or parse_name
        parsed = {f: parse(f.rpartition("/")[2]) for f in files}
        if inst.kind == "hit":
            notes = {f: 60 for f in files}
            centroid = np.median([spectral_centroid(_wav_audio(str(lib.cache / f)), wav_info(lib.cache / f).rate) for f in files])
            print(f"{name}: {len(files)} hits, centroid {centroid:.0f} Hz")
        else:
            offsets = []
            for f, (note, _, _) in parsed.items():
                assert note is not None, f"{f}: no note in the name"
                m = measured_midi(lib.cache / f)
                if m is not None:
                    offsets.append(round((m - note) / 12.0) * 12)
            shift = inst.octave if inst.octave is not None else (max(set(offsets), key=offsets.count) if offsets else 0)
            print(f"{name}: label octave shift {shift:+d} ({offsets.count(shift) / max(1, len(offsets)):.0%} of {len(offsets)} measured agree)")
            notes = {f: parsed[f][0] + shift for f in files}  # type: ignore[operator]
        vel_ranks = sorted({parsed[f][1] for f in files})
        per_note_single = all(len({parsed[g][1] for g in files if notes[g] == notes[f]}) == 1 for f in files)
        layers = [0] if per_note_single else vel_ranks
        bounds = dict(zip(layers, layer_bounds(len(layers)), strict=True))
        # level from the samples a plain note plays (velocity 1.0 = MIDI 80), so plain notes balance across instruments
        plain = [f for f in files if per_note_single or bounds[parsed[f][1]][0] <= 80 <= bounds[parsed[f][1]][1]] or files
        levels = sorted(loudness(lib.cache / f) for f in plain)
        peaks = sorted(float(np.max(np.abs(_wav_audio(str(lib.cache / f))))) for f in plain)
        volume = round(min(REFERENCE_LUFS - levels[len(levels) // 2], 20.0 * np.log10(PEAK_CEILING / max(peaks[len(peaks) // 2], 1e-6))), 1)
        tune = 0
        if inst.kind != "hit":  # a whole set recorded off A440 is pulled back in (single notes' readings are too noisy to trust)
            cents = sorted((m - notes[f]) * 100 for f in files if (m := measured_midi(lib.cache / f)) is not None)
            median = round(cents[len(cents) // 2]) if cents else 0
            if 15 <= abs(median) <= 60:
                tune = -median
                print(f"{name}: recorded {median:+d} cents off: tune={tune}")
        lines = [f"// {spec.title} {name}: {inst.description}. Samples: {spec.credit} ({spec.url}).",
                 f"// Generated by scripts/{spec.script}; sample paths are relative to the library's cache folder.",
                 "<control>",
                 f"// volume: the median plain-velocity sample (loudest 400 ms) is {REFERENCE_LUFS:g} LUFS, its peak at most {PEAK_CEILING:g}; "
                 "dynamic layers keep their recorded levels.",
                 f"<group> volume={volume:g} ampeg_release={inst.release:g}" + (f" tune={tune}" if tune else "") + (" loop_mode=one_shot" if inst.kind != "sus" else "")
                 + (" pitch_keytrack=0" if inst.kind == "hit" else "")]  # fmt: skip
        for rank in layers:
            members = [f for f in files if per_note_single or parsed[f][1] == rank]
            keys = sorted({notes[f] for f in members})
            for i, key in enumerate(keys):
                lo = key - 3 if i == 0 else (keys[i - 1] + key) // 2 + 1
                hi = key + 3 if i == len(keys) - 1 else (key + keys[i + 1]) // 2
                if inst.kind == "hit":
                    lo, hi = 0, 127
                group = sorted((f for f in members if notes[f] == key), key=lambda f: (parsed[f][2], f))
                for pos, f in enumerate(group, start=1):
                    lovel, hivel = bounds[rank]
                    parts = [f"lokey={max(0, lo)}", f"hikey={min(127, hi)}", f"pitch_keycenter={key}", f"lovel={lovel}", f"hivel={hivel}"]
                    if len(group) > 1:
                        parts += [f"seq_length={len(group)}", f"seq_position={pos}"]
                    if (skip := lead_in(lib.cache / f)) > 0:
                        parts.append(f"offset={skip}")
                    lines.append("<region> " + " ".join(parts) + f" sample={f}")
        (out / f"{name}.sfz").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data = {"title": spec.title, "repo": repo, "commit": commit, "license": spec.license, "url": spec.url, "credit": spec.credit,
            "instruments": instruments, "files": {f: list(all_files[f]) for f in used},
            **({"sources": {a: {"repo": r, "commit": c} for a, r, c in sources}} if sources else {})}  # fmt: skip
    (out / "library.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "LICENSE.txt").write_text(spec.licence_text, encoding="utf-8")
    print(f"wrote {len(chosen)} instruments to {out}")
