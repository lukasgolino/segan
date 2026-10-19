"""Generate SEGAN's VSCO 2 Community Edition library maps (src/segan/libraries/vsco2/).

VSCO-2-CE (https://github.com/sgossner/VSCO-2-CE, CC0 1.0, Versilian Studios) ships WAVs named by note,
dynamic layer and round robin, but no SFZ. This script pins a commit, picks the curated instruments below,
downloads their files (into the normal SEGAN sample cache, verified by git blob id), measures each folder's
octave labelling (VSCO folders disagree: some call middle C "C3") and each sample's lead-in silence with
SEGAN's own analysis, and writes one SFZ per instrument plus library.json.

    python scripts/make_vsco2_library.py            # needs `gh` (GitHub API) and network access

Run it again only to change the curated set or move the pin; commit the generated files.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from segan.analysis import max_momentary_lufs, yin  # noqa: E402
from segan.libraries import Library, fetch  # noqa: E402
from segan.samples import _wav_audio, sfz_key, wav_info  # noqa: E402

REPO = "sgossner/VSCO-2-CE"
COMMIT = "440300901dfe9275fd84e0b7763af1f8443ae62e"
OUT = ROOT / "src" / "segan" / "libraries" / "vsco2"

# name: (folder, basename regex, kind, release s, description)
# kind: sus (held: the note gate decides), shot (one-shot: plays to its end), hit (unpitched one-shot)
INSTRUMENTS: dict[str, tuple[str, str, str, float, str]] = {
    "violins_sus": ("Strings/Violin Section/susVib", r".", "sus", 0.35, "violin section, sustained with vibrato"),
    "violins_trem": ("Strings/Violin Section/Trem", r".", "sus", 0.3, "violin section, tremolo"),
    "violins_pizz": ("Strings/Violin Section/Pizz", r".", "shot", 0.2, "violin section, pizzicato"),
    "violins_spic": ("Strings/Violin Section/Spic", r".", "shot", 0.2, "violin section, spiccato (short bowed)"),
    "violas_sus": ("Strings/Viola Section/susvib", r".", "sus", 0.35, "viola section, sustained with vibrato"),
    "violas_pizz": ("Strings/Viola Section/pizz", r".", "shot", 0.2, "viola section, pizzicato"),
    "violas_spic": ("Strings/Viola Section/spic", r".", "shot", 0.2, "viola section, spiccato"),
    "cellos_sus": ("Strings/Cello Section/susvib", r".", "sus", 0.4, "cello section, sustained with vibrato"),
    "cellos_trem": ("Strings/Cello Section/trem", r".", "sus", 0.3, "cello section, tremolo"),
    "cellos_pizz": ("Strings/Cello Section/pizzT", r".", "shot", 0.25, "cello section, pizzicato"),
    "cellos_spic": ("Strings/Cello Section/spic", r".", "shot", 0.2, "cello section, spiccato"),
    "basses_sus": ("Strings/Solo Contrabass/SusVib", r".", "sus", 0.4, "contrabass, sustained with vibrato"),
    "basses_pizz": ("Strings/Solo Contrabass/Pizz", r".", "shot", 0.3, "contrabass, pizzicato"),
    "violin_solo": ("Strings/Solo Violin/Arco Vib", r".", "sus", 0.35, "solo violin, arco with vibrato"),
    "harp": ("Strings/Harp", r".", "shot", 0.5, "concert harp, plucked"),
    "horn_sus": ("Brass/F Horn/sus", r".", "sus", 0.3, "French horn, sustained"),
    "horn_stac": ("Brass/F Horn/stac", r".", "shot", 0.2, "French horn, staccato"),
    "trumpet_sus": ("Brass/Trumpet/sus", r".", "sus", 0.25, "trumpet, sustained"),
    "trumpet_stac": ("Brass/Trumpet/stac", r".", "shot", 0.2, "trumpet, staccato"),
    "trombone_sus": ("Brass/Tenor Trombone/sus", r".", "sus", 0.3, "tenor trombone, sustained"),
    "trombone_stac": ("Brass/Tenor Trombone/stac", r".", "shot", 0.2, "tenor trombone, staccato"),
    "tuba_sus": ("Brass/Tuba/sus", r".", "sus", 0.3, "tuba, sustained"),
    "tuba_stac": ("Brass/Tuba/stac", r".", "shot", 0.2, "tuba, staccato"),
    "flute_sus": ("Woodwinds/Flute/susvib", r".", "sus", 0.25, "flute, sustained with vibrato"),
    "flute_stac": ("Woodwinds/Flute/stac", r".", "shot", 0.2, "flute, staccato"),
    "piccolo": ("Woodwinds/Piccolo/Sus", r".", "sus", 0.2, "piccolo, sustained"),
    "oboe_sus": ("Woodwinds/Oboe/Vib", r".", "sus", 0.25, "oboe, sustained with vibrato"),
    "oboe_stac": ("Woodwinds/Oboe/Stacc", r".", "shot", 0.2, "oboe, staccato"),
    "clarinet_sus": ("Woodwinds/Clarinet/susLong", r".", "sus", 0.25, "clarinet, sustained"),
    "clarinet_stac": ("Woodwinds/Clarinet/stac", r".", "shot", 0.2, "clarinet, staccato"),
    "bassoon_sus": ("Woodwinds/Bassoon/vib", r".", "sus", 0.3, "bassoon, sustained with vibrato"),
    "bassoon_stac": ("Woodwinds/Bassoon/stac", r".", "shot", 0.2, "bassoon, staccato"),
    "timpani": ("Percussion/Timpani", r"_Hit_", "shot", 0.5, "timpani, single hits (five drums, pitch-shifted between them)"),
    "timpani_roll": ("Percussion/Timpani/Rolls", r"_Roll_", "shot", 0.5, "timpani, rolls"),
    "glockenspiel": ("Percussion/Glock", r".", "shot", 0.6, "glockenspiel"),
    "marimba": ("Percussion/Marimba", r".", "shot", 0.4, "marimba"),
    "xylophone": ("Percussion/Xylo", r".", "shot", 0.3, "xylophone"),
    "piano": ("Keys/Upright Nr1", r"\.wav$", "sus", 0.35, "upright piano (dampers on note-off)"),
    "bass_drum": ("Percussion", r"^BDrumNewhit_", "hit", 0.5, "orchestral bass drum (unpitched)"),
    "snare": ("Percussion", r"^Snare2-HitSN_", "hit", 0.3, "concert snare, snares on (unpitched)"),
    "crash": ("Percussion", r"^cymbal-crash", "hit", 1.0, "clash cymbals (unpitched)"),
    "sus_cymbal": ("Percussion", r"^susCymb1-hitstick_", "hit", 1.0, "suspended cymbal, stick (unpitched)"),
    "tam_tam": ("Percussion", r"^gongHit", "hit", 2.0, "tam-tam / gong (unpitched)"),
    "triangle": ("Percussion", r"^Triangle3-Hit_", "hit", 1.0, "triangle (unpitched)"),
    "tambourine": ("Percussion", r"^Tamb1-Hit", "hit", 0.3, "tambourine (unpitched)"),
}

DYNAMICS = {"ppp": 1, "pp": 2, "p": 3, "mp": 4, "soft": 3, "quiet": 3, "medium": 5, "mf": 5, "f": 6, "loud": 7, "ff": 7, "fff": 8}
NOTE_RE = re.compile(r"(?:^|_)([A-G]#?-?\d)(?=_|\.|$)")


def tree() -> dict[str, tuple[int, str]]:
    out = subprocess.run(["gh", "api", f"repos/{REPO}/git/trees/{COMMIT}?recursive=1"], check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    assert not data.get("truncated"), "tree truncated"
    return {t["path"]: (int(t["size"]), t["sha"]) for t in data["tree"] if t["type"] == "blob"}


def files_for(all_files: dict[str, tuple[int, str]], folder: str, pattern: str) -> list[str]:
    rx = re.compile(pattern)
    out = []
    for path in all_files:
        parent, _, base = path.rpartition("/")
        if parent == folder and base.lower().endswith(".wav") and rx.search(base):
            out.append(path)
    return sorted(out)


def parse_name(base: str) -> tuple[int | None, int, int]:
    """(labelled MIDI note or None, dynamic rank, round robin) from a VSCO file name."""
    stem = base[:-4]
    m = NOTE_RE.search(stem)
    note = sfz_key(m.group(1)) if m else None
    vel = 0
    if v := re.search(r"(?:^|_)v(\d+)(?=_|$)", stem):
        vel = int(v.group(1))
    elif v := re.search(r"(?:^|_)dyn(\d+)", stem):
        vel = int(v.group(1))
    else:
        for token in re.split(r"[_\-]", stem):
            if token.lower() in DYNAMICS:
                vel = DYNAMICS[token.lower()]
    rr = 1
    if r := re.search(r"(?:^|_)rr(\d+)", stem, re.I):
        rr = int(r.group(1))
    elif r := re.search(r"_(\d{1,2})$", stem):
        rr = int(r.group(1))
    return note, vel, rr


def measured_midi(path: Path) -> float | None:
    info = wav_info(path)
    audio = _wav_audio(str(path))
    peak = float(np.max(np.abs(audio))) or 1.0
    loud = np.flatnonzero(np.abs(audio) > peak * 0.1)
    if not len(loud):
        return None
    start = int(loud[0]) + info.rate // 10
    chunk = audio[start : start + info.rate // 2]
    track = yin(chunk, info.rate, fmin=25.0, fmax=5000.0, hop=0.01, require_fundamental=True)
    voiced = track.hz[track.hz > 0]
    if len(voiced) < 5:
        return None
    return 69.0 + 12.0 * math.log2(float(np.median(voiced)) / 440.0)


def lead_in(path: Path) -> int:
    """Frames of silence before the sound (40 dB under the peak), minus 2 ms of pre-roll."""
    info = wav_info(path)
    audio = _wav_audio(str(path))
    peak = float(np.max(np.abs(audio))) or 1.0
    loud = np.flatnonzero(np.abs(audio) > peak * 0.01)
    return max(0, int(loud[0]) - info.rate // 500) if len(loud) else 0


REFERENCE_LUFS = -20.0  # every instrument's median sample (loudest 400 ms) lands here: kit gains are pure balance


def loudness(path: Path) -> float:
    return max_momentary_lufs(_wav_audio(str(path)), wav_info(path).rate)


def layer_bounds(count: int) -> list[tuple[int, int]]:
    return [(1 + (127 * i) // count, (127 * (i + 1)) // count) for i in range(count)]


def main() -> None:
    all_files = tree()
    chosen = {name: files_for(all_files, folder, pattern) for name, (folder, pattern, *_rest) in INSTRUMENTS.items()}
    for name, files in chosen.items():
        assert files, f"{name}: no files"
    used = sorted({f for files in chosen.values() for f in files})
    instruments = {name: {"description": INSTRUMENTS[name][4], "kind": INSTRUMENTS[name][2], "files": files} for name, files in chosen.items()}
    lib = Library("vsco2", "VSCO 2 Community Edition", REPO, COMMIT, "CC0-1.0", f"https://github.com/{REPO}",
                  "Versilian Studios Chamber Orchestra 2 Community Edition (VSCO-2-CE), CC0 1.0", instruments,
                  {f: all_files[f] for f in used})  # fmt: skip
    total = sum(all_files[f][0] for f in used)
    print(f"{len(used)} files, {total / 1e6:.0f} MB; fetching what's missing into {lib.cache}")
    count, size = fetch(lib, list(instruments), progress=lambda p: print("  got", p))
    print(f"fetched {count} files ({size / 1e6:.0f} MB)")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, files in chosen.items():
        folder, _, kind, release, description = INSTRUMENTS[name]
        parsed = {f: parse_name(f.rpartition("/")[2]) for f in files}
        if kind == "hit":
            notes = {f: 60 for f in files}
        elif name.startswith("timpani"):
            drums: dict[str, list[str]] = defaultdict(list)
            for f in chosen["timpani_roll"]:  # a roll's pitch is steadier than a hit's: tune both from the rolls
                drums[re.search(r"Timpani(\d)", f).group(1)].append(f)  # type: ignore[union-attr]
            pitch = {}
            for drum, members in drums.items():
                found = [m for m in (measured_midi(lib.cache / f) for f in members) if m is not None]
                pitch[drum] = round(float(np.median(found))) if found else 40 + 3 * int(drum)
            notes = {f: pitch[re.search(r"Timpani(\d)", f).group(1)] for f in files}  # type: ignore[union-attr]
            print(f"{name}: drums {pitch}")
        else:
            offsets = []
            for f, (note, _, _) in parsed.items():
                assert note is not None, f"{f}: no note in the name"
                m = measured_midi(lib.cache / f)
                if m is not None:
                    offsets.append(round((m - note) / 12.0) * 12)
            shift = max(set(offsets), key=offsets.count) if offsets else 0
            agree = offsets.count(shift) / max(1, len(offsets))
            print(f"{name}: label octave shift {shift:+d} ({agree:.0%} of {len(offsets)} measured agree)")
            notes = {f: parsed[f][0] + shift for f in files}  # type: ignore[operator]
        levels = sorted(loudness(lib.cache / f) for f in files)
        volume = round(REFERENCE_LUFS - levels[len(levels) // 2], 1)
        lines = [f"// VSCO 2 CE {name}: {description}. Samples: {lib.credit} ({lib.url}, commit {COMMIT[:12]}).",
                 "// Generated by scripts/make_vsco2_library.py; sample paths are relative to the repository root.",
                 "<control>",
                 f"// volume: the median sample (loudest 400 ms) is {REFERENCE_LUFS:g} LUFS; dynamic layers keep their recorded levels.",
                 f"<group> volume={volume:g} ampeg_release={release:g}" + (" loop_mode=one_shot" if kind != "sus" else "") + (" pitch_keytrack=0" if kind == "hit" else "")]  # fmt: skip
        vel_ranks = sorted({parsed[f][1] for f in files})
        per_note_single = all(len({parsed[g][1] for g in files if notes[g] == notes[f]}) == 1 for f in files)
        layers = [0] if per_note_single else vel_ranks
        bounds = dict(zip(layers, layer_bounds(len(layers)), strict=True))
        for rank in layers:
            members = [f for f in files if per_note_single or parsed[f][1] == rank]
            keys = sorted({notes[f] for f in members})
            for i, key in enumerate(keys):
                lo = key - 3 if i == 0 else (keys[i - 1] + key) // 2 + 1
                hi = key + 3 if i == len(keys) - 1 else (key + keys[i + 1]) // 2
                if kind == "hit":
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
        (OUT / f"{name}.sfz").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data = {"title": lib.title, "repo": REPO, "commit": COMMIT, "license": lib.license, "url": lib.url, "credit": lib.credit,
            "instruments": instruments, "files": {f: list(all_files[f]) for f in used}}  # fmt: skip
    (OUT / "library.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (OUT / "LICENSE.txt").write_text("The VSCO 2 Community Edition samples are by Versilian Studios, released under CC0 1.0 Universal\n"
                                     f"({lib.url}). SEGAN doesn't ship them: `segan samples fetch vsco2` downloads them.\n"
                                     "The .sfz maps in this folder are part of SEGAN (MIT).\n", encoding="utf-8")  # fmt: skip
    print(f"wrote {len(chosen)} instruments to {OUT}")


if __name__ == "__main__":
    main()
