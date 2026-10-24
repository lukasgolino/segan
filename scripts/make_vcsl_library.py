"""Generate SEGAN's VCSL library maps (src/segan/libraries/vcsl/).

The Versilian Community Sample Library (https://github.com/sgossner/VCSL, CC0 1.0, Versilian Studios) is VSCO's
sibling: keyboards, mallets, folk and world instruments and hand percussion as WAVs named by note, dynamic and round
robin, no SFZ in the repository. Same method as make_vsco2_library.py (library_maps.py): pin a commit, pick the
curated instruments below, download them into the normal SEGAN sample cache (verified by git blob id), measure each
folder's octave labelling and each sample's lead-in, level every instrument to -20 LUFS, write one SFZ per instrument
plus library.json.

    python scripts/make_vcsl_library.py            # needs `gh` (GitHub API) and network access (~1.4 GB once)
"""

from __future__ import annotations

from library_maps import ROOT, Inst, Spec, build

REPO = "sgossner/VCSL"
COMMIT = "c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e"
OUT = ROOT / "src" / "segan" / "libraries" / "vcsl"
C, I, M = "Chordophones", "Idiophones/Struck Idiophones", "Membranophones/Struck Membranophones"

# kind: sus (held), shot (rings to its end), hit (unpitched)
INSTRUMENTS: dict[str, Inst] = {
    "grand_piano": Inst(f"{C}/Zithers/Grand Piano, Kawai/Sustains", r".", "sus", 0.4, "Kawai grand piano (dampers on note-off)"),
    "fm_piano": Inst("Electrophones/TX81Z/FM Piano", r".", "sus", 0.3, "FM electric piano (Yamaha TX81Z)"),
    "clavisynth": Inst("Electrophones/TX81Z/Clavisynth", r".", "sus", 0.2, "FM clavinet-like keys (Yamaha TX81Z)"),
    "harpsichord": Inst(f"{C}/Zithers/Harpsichord, French/Sustains", r".", "sus", 0.3, "French harpsichord"),
    "folk_harp": Inst(f"{C}/Composite Chordophones/Folk Harp", r".", "shot", 0.5, "folk harp, plucked"),
    "dan_tranh": Inst(f"{C}/Zithers/Dan Tranh/Normal", r".", "shot", 0.4, "dan tranh (Vietnamese zither, koto-like), plucked"),
    "strumstick": Inst(f"{C}/Composite Chordophones/Strumstick/Finger", r".", "shot", 0.4, "strumstick (fretted dulcimer), fingerpicked"),
    "vibraphone": Inst(f"{I}/Vibraphone/Soft Mallets", r".", "shot", 1.0, "vibraphone, soft mallets"),
    "vibraphone_hard": Inst(f"{I}/Vibraphone/Hard Mallets", r".", "shot", 1.0, "vibraphone, hard mallets"),
    "tubular_bells": Inst(f"{I}/Tubular Bells 1", r".", "shot", 1.5, "tubular bells (chimes)"),
    "hand_chimes": Inst(f"{I}/Hand Chimes", r".", "shot", 1.0, "hand chimes"),
    "balafon": Inst(f"{I}/Balafon/Hard Mallet", r".", "shot", 0.3, "balafon (West African xylophone), hard mallet"),
    "kalimba": Inst("Idiophones/Plucked Idiophones/Kalimba, Kenya", r".", "shot", 0.5, "kalimba (Kenya)"),
    "mbira": Inst("Idiophones/Plucked Idiophones/Mbira Mavembe (Gandanga), Zimbabwe, Low G", r".", "shot", 0.6, "mbira (Zimbabwe), low and buzzy"),
    "harmonica": Inst("Aerophones/Free Aerophones/Harmonica-Hohner-Super64/Sustains/Normal", r".", "sus", 0.15, "chromatic harmonica"),
    "tenor_sax": Inst("Aerophones/Reed Aerophones/Tenor Saxophone/Non-Vibrato", r".", "sus", 0.2, "tenor saxophone, no vibrato"),
    "recorder": Inst("Aerophones/Edge-blown Aerophones/Baroque Alto Recorder/Sustain", r".", "sus", 0.15, "alto recorder"),
    "ocarina": Inst("Aerophones/Edge-blown Aerophones/Ocarina, Typical/Sustains/Sus", r".", "sus", 0.15, "ocarina"),
    "pipe_organ": Inst("Aerophones/Edge-blown Aerophones/Pipe Organ/Quiet", r".", "sus", 0.4, "pipe organ, quiet stop"),
    "pipe_organ_loud": Inst("Aerophones/Edge-blown Aerophones/Pipe Organ/Loud", r".", "sus", 0.5, "pipe organ, full"),
    "bowed_psaltery": Inst(f"{C}/Zithers/Psaltery, Bowed and Plucked/LongBow", r".", "sus", 0.5, "bowed psaltery (eerie, glassy)"),
    "conga": Inst(f"{M}/Conga", r"^Conga_HitN_", "hit", 0.4, "conga, open (unpitched)"),
    "conga_mute": Inst(f"{M}/Conga", r"^Conga_HitFM_", "hit", 0.2, "conga, muted (unpitched)"),
    "quinto": Inst(f"{M}/Conga", r"^Quinto_HitN_", "hit", 0.4, "quinto (high conga), open (unpitched)"),
    "tumba": Inst(f"{M}/Conga", r"^Tumba_HitN_", "hit", 0.4, "tumba (low conga), open (unpitched)"),
    "bongo_high": Inst(f"{M}/Bongos", r"^BongoH_Hit1_", "hit", 0.3, "bongo, high (unpitched)"),
    "bongo_low": Inst(f"{M}/Bongos", r"^BongoL_Hit1_", "hit", 0.3, "bongo, low (unpitched)"),
    "cajon_1": Inst(f"{I}/Cajon", r"^Cajon_hit1_", "hit", 0.3, "cajon, stroke 1: the brightest (unpitched)"),
    "cajon_2": Inst(f"{I}/Cajon", r"^Cajon_hit2_", "hit", 0.3, "cajon, stroke 2 (unpitched)"),
    "cajon_3": Inst(f"{I}/Cajon", r"^Cajon_hit3_", "hit", 0.3, "cajon, stroke 3: the deepest (unpitched)"),
    "darbuka_1": Inst(f"{M}/Darbuka", r"^Darbuka_1_", "hit", 0.3, "darbuka, stroke 1: the deepest, doum-like (unpitched)"),
    "darbuka_3": Inst(f"{M}/Darbuka", r"^Darbuka_3_", "hit", 0.3, "darbuka, stroke 3: the brightest, tek-like (unpitched)"),
    "darbuka_5": Inst(f"{M}/Darbuka", r"^Darbuka_5_", "hit", 0.3, "darbuka, stroke 5 (unpitched)"),
    "frame_drum": Inst(f"{M}/Frame Drum", r"^HDrumL_Hit_", "hit", 0.5, "frame drum, large (unpitched)"),
    "frame_drum_small": Inst(f"{M}/Frame Drum", r"^HDrumS_Hit_", "hit", 0.4, "frame drum, small (unpitched)"),
    "snare_drum": Inst(f"{M}/Snare Drum, Modern 1", r"^Snare2_HitSN_", "hit", 0.3, "snare drum, snares on (unpitched)"),
    "snare_off": Inst(f"{M}/Snare Drum, Modern 1", r"^Snare2_HitNS_", "hit", 0.3, "snare drum, snares off (unpitched)"),
    "hihat": Inst(f"{I}/Hi-Hat Cymbal", r"^HiHat_HitC_", "hit", 0.2, "hi-hat, closed (unpitched)"),
    "hihat_open": Inst(f"{I}/Hi-Hat Cymbal", r"^HiHat_HitO_", "hit", 0.6, "hi-hat, open (unpitched)"),
    "tom_high": Inst(f"{M}/Tom 1/Stick", r"^TomH_HitS_", "hit", 0.4, "tom, high, stick (unpitched)"),
    "tom_low": Inst(f"{M}/Tom 2/Stick", r"^TomL_HitS_", "hit", 0.5, "tom, low, stick (unpitched)"),
    "shaker": Inst(f"{I}/Shaker, Small", r"^Mid_ShakerDouble_Down_", "hit", 0.2, "shaker (unpitched)"),
    "cowbell": Inst(f"{I}/Cowbells", r"^Cowbell1_Normal_", "hit", 0.3, "cowbell (unpitched)"),
    "woodblock": Inst(f"{I}/Woodblock", r"^wood_click_", "hit", 0.2, "wood block (unpitched)"),
    "claves": Inst(f"{I}/Claves", r"^Claves1_Hit_", "hit", 0.2, "claves (unpitched)"),
    "agogo_high": Inst(f"{I}/Agogo Bells", r"^Agogo_High_", "hit", 0.4, "agogo bell, high (unpitched)"),
    "agogo_low": Inst(f"{I}/Agogo Bells", r"^Agogo_Low_", "hit", 0.4, "agogo bell, low (unpitched)"),
    "clap": Inst(f"{I}/Claps", r"^Clap_rr", "hit", 0.2, "hand claps, a group (unpitched)"),
    "cabasa": Inst(f"{I}/Cabasa", r"^Cabasa1_Hit_", "hit", 0.2, "cabasa (unpitched)"),
    "guiro": Inst(f"{I}/Guiro", r"^Guiro_Hit_", "hit", 0.2, "guiro, short scrape (unpitched)"),
    "anvil": Inst(f"{I}/Anvil", r"^Anvil_Hit1_", "hit", 0.6, "anvil (unpitched)"),
    "brake_drum": Inst(f"{I}/Brake Drum", r"^BrakeDrum1_Hammer", "hit", 0.8, "brake drum, hammer: industrial metal (unpitched)"),
    "slit_drum_high": Inst(f"{I}/Slit Drum", r"^LogDrumHi_", "hit", 0.3, "slit (log) drum, high (unpitched)"),
    "slit_drum_low": Inst(f"{I}/Slit Drum", r"^LogDrumLo_", "hit", 0.3, "slit (log) drum, low (unpitched)"),
    "sleigh_bells": Inst(f"{I}/Sleigh Bells", r"^Sleighbells_Hit_", "hit", 0.4, "sleigh bells (unpitched)"),
    "finger_cymbals": Inst(f"{I}/Finger Cymbals", r".", "hit", 1.0, "finger cymbals (unpitched)"),
}  # fmt: skip

SPEC = Spec(
    "vcsl", "Versilian Community Sample Library", "Versilian Community Sample Library (VCSL), Versilian Studios, CC0 1.0",
    f"https://github.com/{REPO}", "CC0-1.0", [("", REPO, COMMIT)], INSTRUMENTS,
    "The Versilian Community Sample Library samples are by Versilian Studios, released under CC0 1.0 Universal\n"
    f"(https://github.com/{REPO}). SEGAN doesn't ship them: `segan samples fetch vcsl` downloads them.\n"
    "The .sfz maps in this folder are part of SEGAN (MIT).\n",
    "make_vcsl_library.py",
)

if __name__ == "__main__":
    build(SPEC, OUT)
