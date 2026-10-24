"""Generate SEGAN's NeoSoundFonts library maps (src/segan/libraries/neosound/): Simone Piervergili's small sets on
github.com/NeoSoundFonts (each CC0 1.0, stated in the repository's licence file): a male "ooh" voice, an old steel-string
guitar and a bamboo flute. Mapped like the other libraries (library_maps.py).

    python scripts/make_neosound_library.py        # needs `gh` and network access
"""

from __future__ import annotations

import re

from library_maps import ROOT, Inst, Spec, build

OUT = ROOT / "src" / "segan" / "libraries" / "neosound"
SOURCES = [
    ("oohs", "NeoSoundFonts/SimonePiervergili-VoiceOohs", "19f6734cd4b10a767d3cd463d9517eb797dcabff"),
    ("steel", "NeoSoundFonts/SimonePiervergili-OldSteelGuitar", "c30bc2151d501d09de5281452fe7e61b9770ce15"),
    ("flute", "NeoSoundFonts/SP-Bamboo-Flute", "bffe30a67a29c8b2dc691e1a45af78b801d57ce6"),
]


def midi_number(base: str) -> tuple[int | None, int, int]:
    """`SteelGuitar 052.wav`, `BambooFlute 072L.wav`: the MIDI note is the number."""
    found = re.search(r" (\d{3})[LR]?\.wav$", base)
    return (int(found.group(1)) if found else None), 0, 1


INSTRUMENTS: dict[str, Inst] = {
    "voice_oohs": Inst("oohs/samples", r".", "sus", 0.4, "a male voice singing \"ooh\" (stack it for a small choir)"),
    "steel_guitar": Inst("steel/samples", r"^SteelGuitar \d+\.wav$", "shot", 0.4, "old steel-string acoustic guitar", parser=midi_number),
    "bamboo_flute": Inst("flute/samples", r"^BambooFlute \d+L\.wav$", "sus", 0.25, "bamboo flute (dizi-like)", parser=midi_number),
}

SPEC = Spec(
    "neosound", "NeoSoundFonts sets", "Simone Piervergili, NeoSoundFonts (Voice Oohs, Old Steel Guitar, Bamboo Flute), CC0 1.0",
    "https://github.com/NeoSoundFonts", "CC0-1.0", SOURCES, INSTRUMENTS,
    "The samples are Simone Piervergili's (https://github.com/NeoSoundFonts: SimonePiervergili-VoiceOohs, SimonePiervergili-OldSteelGuitar,\n"
    "SP-Bamboo-Flute), each released under CC0 1.0 Universal. SEGAN doesn't ship them: `segan samples fetch neosound` downloads them.\n"
    "The .sfz maps in this folder are part of SEGAN (MIT).\n",
    "make_neosound_library.py",
)

if __name__ == "__main__":
    build(SPEC, OUT)
