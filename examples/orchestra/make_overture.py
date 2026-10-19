"""Writes music/overture.song.yaml: an 8-bar looping D minor cue for the orchestra kit (with a 2-bar intro),
grouped into adaptive stems (strings + harp = calm, + brass and percussion = full).

    python make_overture.py && segan preview music/overture.song.yaml
"""

from pathlib import Path

from segan import api

KEY = "D minor"
BAR = 16  # 4/4, four steps per beat

strings_hi = api.Track.roll("violins", KEY, "D4", "C6")
violas = api.Track.roll("violas", KEY, "G3", "A4")
cellos = api.Track.roll("cellos", KEY, "C3", "D4")
basses = api.Track.roll("basses", KEY, "A1", "D3")
horn = api.Track.roll("horn", KEY, "A3", "F5")
harp = api.Track.roll("harp", KEY, "D3", "D6")
timp = api.Track.roll("timpani", KEY, "G2", "D3")
perc = api.Track.drums("perc", ["B", "X", "S"])
tracks = [strings_hi, violas, cellos, basses, horn, harp, timp, perc]

# i VI III VII | i iv VII i  (natural minor: an open, modal sound)
loop_chords = api.progression("i VI III VII i iv VII i", KEY, octave=3)
melody = [  # horn: (step in bar, note, length) per bar
    [(0, "A4", 8), (8, "D5", 8)],
    [(0, "D5", 6), (6, "C5", 2), (8, "Bb4", 8)],
    [(0, "A4", 8), (8, "C5", 8)],
    [(0, "C5", 6), (6, "Bb4", 2), (8, "A4", 4), (12, "G4", 4)],
    [(0, "A4", 4), (4, "D5", 4), (8, "F5", 8)],
    [(0, "D5", 6), (6, "C5", 2), (8, "Bb4", 8)],
    [(0, "C5", 8), (8, "E5", 8)],
    [(0, "D5", 16)],
]


def voiced(chord: list[int]) -> tuple[int, int, int, int]:
    """(bass, cello, viola, violin) notes for a root-position triad built at octave 3."""
    root, third, fifth = chord
    bass = root - 12 if root - 12 >= api.note("A1") else root
    while bass > api.note("D3"):
        bass -= 12
    cello = root if api.note("C3") <= root <= api.note("D4") else root + 12
    viola = fifth if fifth >= api.note("A3") else fifth + 12
    violin = third + 12 if third + 12 >= api.note("D4") else third + 24
    return bass, cello, viola, violin


def bar(chord: list[int], tune: list[tuple[int, str, int]] | None, timp_hit: bool, crash: bool, last: bool) -> api.Pattern:
    p = api.Pattern(BAR)
    bass, cello, viola, violin = voiced(chord)
    p.note(basses, 0, bass, BAR, "b")
    p.note(cellos, 0, cello, BAR, "c")
    p.note(violas, 0, viola, BAR, "a")
    p.note(strings_hi, 0, violin, BAR, "v")
    if tune:
        for step, pitch, length in tune:
            p.note(horn, step, pitch, length, "h")
    arp_notes = [n for n in (chord[0] + 12, chord[1] + 12, chord[2] + 12, chord[0] + 24) if api.note("D3") <= n <= api.note("D6")]
    for step, midi, length in api.arpeggiate(arp_notes, BAR, rate=2):
        p.note(harp, step, midi, length, "r")
    if timp_hit:
        root = chord[0]
        while root > api.note("D3"):
            root -= 12
        while root < api.note("G2"):
            root += 12
        p.note(timp, 0, root, 4, "T")
        if last:
            p.note(timp, 12, api.note("A2"), 2, "T")
            p.note(timp, 14, api.note("A2"), 2, "T")
    if crash:
        p.hit(perc, 0, "X").hit(perc, 0, "B", "X")
    p.row(perc, "S", "....x.......x.x." if last else "....x.......x...")
    return p


patterns: dict[str, api.Pattern] = {}
for i, chord in enumerate(api.progression("i i", KEY, octave=3)):
    p = api.Pattern(BAR)
    bass, cello, viola, violin = voiced(chord)
    p.note(basses, 0, bass, BAR, "b").note(cellos, 0, cello, BAR, "c")
    if i == 1:
        p.note(violas, 0, viola, BAR, "a").note(timp, 8, api.note("A2"), 4, "T").note(timp, 12, api.note("A2"), 4, "T")
    for step, midi, length in api.arpeggiate([chord[0] + 12, chord[1] + 12, chord[2] + 12, chord[0] + 24], BAR, rate=2):
        p.note(harp, step, midi, length, "r")
    patterns[f"intro{i + 1}"] = p
for i, chord in enumerate(loop_chords):
    patterns[f"m{i + 1}"] = bar(chord, melody[i], timp_hit=i in (0, 4, 7), crash=i == 0, last=i == 7)

text = api.song_yaml(
    "overture", key=KEY, tempo=84, kit="orchestra",
    description="Adventure cue for the sampled orchestra: strings hold the chords, a horn sings, the harp ripples; loops from bar 3.",
    tracks=tracks, patterns=patterns, sections={"intro": ["intro1", "intro2"], "main": [f"m{i + 1}" for i in range(8)]},
    arrangement=["intro", "main"], loop="main",
    stems={"groups": {"strings": ["violins", "violas", "cellos", "basses"], "harp": ["harp"], "brass": ["horn"], "perc": ["timpani", "perc"]},
           "mixes": {"calm": ["strings", "harp"], "full": ["strings", "harp", "brass", "perc"]}},
)  # fmt: skip
Path(__file__).with_name("music").joinpath("overture.song.yaml").write_text(text, encoding="utf-8")
print("wrote music/overture.song.yaml")
