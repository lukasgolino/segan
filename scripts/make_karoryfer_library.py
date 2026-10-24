"""Generate SEGAN's Karoryfer library maps (src/segan/libraries/karoryfer/): guitars, basses, double bass, erhu and
a drum kit (with a brush) from Karoryfer Lecolds' free libraries on github.com/sfzinstruments (each CC0 1.0, stated
in the repository's licence file). Their own SFZ programs use keyswitches, includes and Sforzando-only controls, so
SEGAN maps the WAVs itself, the same way as VSCO and VCSL (library_maps.py).

    python scripts/make_karoryfer_library.py       # needs `gh` and network access (~2 GB once)
"""

from __future__ import annotations

import re

from library_maps import ROOT, Inst, Spec, build, parse_name

OUT = ROOT / "src" / "segan" / "libraries" / "karoryfer"
SOURCES = [
    ("bng", "sfzinstruments/karoryfer.black-and-green-guitars", "b3b3249d37dc977a1a297bd2dc053e6d9b6b805c"),
    ("emily", "sfzinstruments/karoryfer.emilyguitar", "b4920dc662fd9cad6dcaccdeecffdd91c8725d8c"),
    ("bnb", "sfzinstruments/karoryfer.black-and-blue-basses", "6e7d674cdb41be7a54dbccb15472401ad01099b9"),
    ("smolken", "sfzinstruments/dsmolken.double-bass", "c2985eb647109d2a8f30a70071e3e163339d7396"),
    ("erhu", "sfzinstruments/aliexpress-erhu", "6615047b2fd06126877483e97b8bb4af9d00b080"),
    ("swirly", "sfzinstruments/karoryfer.swirly-drums", "c40dafe0011cb2e54c0c220ff0fa308a11fc60f5"),
]


def pizz(base: str) -> tuple[int | None, int, int]:
    """`pizz_a2_fa.wav`: note, then dynamic letter (p, m, f) and round-robin letter (a-d)."""
    note, _, _ = parse_name(base)
    tail = base.rsplit(".", 1)[0].rsplit("_", 1)[-1]
    return note, {"p": 3, "m": 5, "f": 6}.get(tail[0], 5), ord(tail[-1]) - 96


def stir(base: str) -> tuple[int | None, int, int]:
    """`stir_dl2_rr3.wav`: dynamic level 1-4."""
    found = re.search(r"dl(\d)", base)
    _, _, rr = parse_name(base)
    return 60, int(found.group(1)) if found else 1, rr


S = "swirly/Samples"
INSTRUMENTS: dict[str, Inst] = {
    "gretsch": Inst("bng/Samples/green/ord", r"^twang_", "sus", 0.25, "hollowbody electric guitar (green Gretsch Anniversary), plucked"),
    "gretsch_mute": Inst("bng/Samples/green/stac", r"^staccato_", "shot", 0.15, "hollowbody electric guitar (Gretsch), palm-muted staccato"),
    "hofner": Inst("bng/Samples/black/ord", r"^twang_", "sus", 0.25, "hollowbody electric guitar (black Hofner Club), plucked"),
    "clean_guitar": Inst("emily/notes", r".", "sus", 0.25, "clean electric guitar (Epiphone, flatwound strings, direct)"),
    "bass_guitar": Inst("bnb/Samples/babyblue/reg", r".", "sus", 0.2, "electric bass (Baby Blue), fingered"),
    "bass_guitar_dark": Inst("bnb/Samples/darkblack/reg", r".", "sus", 0.2, "electric bass (Dark Black), darker"),
    "upright_pizz": Inst("smolken/pizz", r"^pizz_", "shot", 0.3, "double bass, pizzicato (jazz upright)", parser=pizz),
    "upright_arco": Inst("smolken/arco", r"^arco_", "sus", 0.4, "double bass, bowed"),
    "erhu": Inst("erhu/Samples/sus", r".", "sus", 0.3, "erhu (Chinese two-string fiddle), sustained"),
    "erhu_stac": Inst("erhu/Samples/stac", r".", "shot", 0.2, "erhu, staccato"),
    "kick": Inst(f"{S}/marching_kick", r"_beater\.wav$", "hit", 0.4, "kick drum (a marching bass drum in a kit, beater mic) (unpitched)"),
    "cajon_kick": Inst(f"{S}/cajon_kick", r"_front\.wav$", "hit", 0.3, "cajon played as a kick (unpitched)"),
    "snare": Inst(f"{S}/snare_main", r"_top\.wav$", "hit", 0.3, "snare drum (unpitched)"),
    "snare_edge": Inst(f"{S}/snare_edge", r"_top\.wav$", "hit", 0.3, "snare drum, hit near the edge (unpitched)"),
    "brush": Inst(f"{S}/snare_stir", r"^stir_dl\d_rr", "hit", 0.6, "brush stirred on the snare (unpitched)", parser=stir),
    "hat_closed": Inst(f"{S}/hat_closed", r".", "hit", 0.2, "hi-hat, closed (unpitched)"),
    "hat_tight": Inst(f"{S}/hat_tight", r".", "hit", 0.15, "hi-hat, tight (unpitched)"),
    "hat_half": Inst(f"{S}/hat_half", r".", "hit", 0.4, "hi-hat, half open (unpitched)"),
    "hat_open": Inst(f"{S}/hat_open", r".", "hit", 0.8, "hi-hat, open (unpitched)"),
    "hat_foot": Inst(f"{S}/hat_foot", r".", "hit", 0.2, "hi-hat, foot (unpitched)"),
    "tom_floor": Inst(f"{S}/tom_floor", r".", "hit", 0.6, "floor tom (unpitched)"),
    "tom_low": Inst(f"{S}/tom_mlow", r".", "hit", 0.5, "tom, low (unpitched)"),
    "tom_mid": Inst(f"{S}/tom_xmed", r".", "hit", 0.5, "tom, middle (unpitched)"),
    "tom_high": Inst(f"{S}/tom_mhi", r".", "hit", 0.4, "tom, high (unpitched)"),
    "tom_very_high": Inst(f"{S}/tom_vhi", r".", "hit", 0.4, "tom, very high (unpitched)"),
    "crash": Inst(f"{S}/crash", r".", "hit", 1.5, "crash cymbal (unpitched)"),
    "ride": Inst(f"{S}/ride", r".", "hit", 1.5, "ride cymbal (unpitched)"),
    "splash": Inst(f"{S}/splash", r".", "hit", 1.0, "splash cymbal (unpitched)"),
    "china": Inst(f"{S}/china", r".", "hit", 1.5, "china cymbal (unpitched)"),
    "djembe": Inst(f"{S}/djembe", r".", "hit", 0.4, "djembe (unpitched)"),
}  # fmt: skip

SPEC = Spec(
    "karoryfer", "Karoryfer Lecolds libraries", "Karoryfer Lecolds (Black And Green Guitars, Emily Guitar, Black And Blue Basses, "
    "D. Smolken double bass, Aliexpress Erhu, Swirly Drums), CC0 1.0", "https://github.com/sfzinstruments", "CC0-1.0", SOURCES, INSTRUMENTS,
    "The samples are Karoryfer Lecolds' (https://github.com/sfzinstruments: black-and-green-guitars, emilyguitar, black-and-blue-basses,\n"
    "dsmolken.double-bass, aliexpress-erhu, swirly-drums), each released under CC0 1.0 Universal. SEGAN doesn't ship them:\n"
    "`segan samples fetch karoryfer` downloads them. The .sfz maps in this folder are part of SEGAN (MIT).\n",
    "make_karoryfer_library.py",
)

if __name__ == "__main__":
    build(SPEC, OUT)
