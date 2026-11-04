# Api

Generator scripts: the segan.api Python API with a worked example.

## Generator scripts: `segan.api`

For many similar sounds or procedural music, write a Python script with `segan.api` (stable, `API_VERSION`):
`note("A4")`, `scale(key, low, high)`, `chord(degree, key, octave, size=3)`, `progression("i VI III VII", key)`,
`euclid(hits, steps, rotate)`, `arpeggiate(notes, steps, rate, order)`, `humanize(row, seed, amount)`,
`invert(notes, inversion)`, `voicing(notes, inversion, spread="close"|"open"|"wide", octave, bass)`, `Rng(seed, ...)`
(seeded `random()`, `choice()`, `range()`, `weighted()`: the same on every machine),
`Track.roll(name, key, low, high)`, `Track.drums(name, keys)`, `Pattern(length).note(track, step, pitch, length,
key, velocity=None)` (written as a `velocity:` row) / `.hit(track, step, drum, mark)` / `.row(track, drum, "x...x...")` / `.lane(track)`,
`song_yaml(name, tracks=..., patterns=..., sections=..., arrangement=..., key=..., tempo=..., loop=...)` (any other
song field as a keyword with its YAML value: `meter=[3, 4]`, `category=`, `status=`, `stems={...}`, `lint={"disable":
[...]}`, `variants={...}`, `flow={...}`, `humanize={...}`, `seed=`),
`sfx_yaml(name, layers=[...], ...)` (both take `comments={"patterns.chorus": "text", ...}`: `#` lines above
those keys). `dedupe(patterns, sections)` merges identical patterns (sections follow); `derive("a", a, b, tracks)`
writes `b` as `{from: a, transpose, mute, shift}` when it is one (else None). Write the result to a file, then lint and preview it like any other.

```python
from pathlib import Path
from segan import api

key = "E dorian"
rng = api.Rng(11, "market")                 # seeded choices: the same file every run, another seed = another take
lead = api.Track.roll("lead", key, "C4", "C6")
keys = api.Track.roll("keys", key, "C3", "A5")
bass = api.Track.roll("bass", key, "C2", "C4")
perc = api.Track.drums("perc", ["k", "s", "h"])
patterns = {}
for name, numeral in zip("abcd", ["i", "IV", "VII", "IV"]):
    p = api.Pattern(12)                     # 3/4: 12 sixteenths per bar
    triad = api.progression(numeral, key, octave=3)[0]
    for m in api.voicing(triad, inversion=rng.choice([0, 1, 2])):
        p.note(keys, 0, m, 12, "e", velocity=0.8)
    for step, midi, length in api.arpeggiate([m + 12 for m in triad], 12, rate=2, order=rng.choice(["up", "down", "updown"])):
        p.note(lead, step, midi, length, "f", velocity=1.5 if step == 0 else 1.0)
    low = api.progression(numeral, key, octave=2)[0]
    p.note(bass, 0, low[0], 6, "a").note(bass, 6, low[2], 6, "a")
    p.row(perc, "k", "x.....x.....").row(perc, "h", api.humanize("..x...x...x.", name))
    patterns[name] = p
text = api.song_yaml("market", kit="fm_soft", key=key, tempo=96, meter=[3, 4], tracks=[lead, keys, bass, perc], patterns=patterns,
                     sections={"main": ["a", "b", "c", "d"]}, arrangement=["main"], loop="main",
                     humanize={"timing": 6, "velocity": 0.1}, description="busy market at dusk, 3/4")
Path("music/market.song.yaml").write_text(text)
```
