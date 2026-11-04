# Songs

Making a song: suggest, rows, patterns, craft, loops, variants, stems; song notation.

## Making a song

1. **Start somewhere new**: `segan suggest song <name> --mood "<words>"` proposes key and mode, tempo, meter,
   an opening texture (pad, ostinato, arpeggio, pulse, drone and melody, drums first, solo line, chorale, bass riff,
   call and response), the opening voicing (chord, inversion, spread, register), a progression and the instruments
   (the identity plus extras), steered away from the project's songs and seeded by the project seed (`--take 1`
   for another). Use it, or decide yourself from SOUND.md, but **vary key, mode, tempo, meter, register, texture and
   instrumentation between songs**: if the last three songs were D minor / F major at 60-72 bpm on a pad, this one
   isn't. Moods: major bright, minor sad/tense, dorian adventurous, mixolydian heroic, phrygian menacing, lydian
   dreamy, harmonic minor exotic; slow isn't always minor, and 3/4, 6/8 or 5/4 change the feel more than tempo.
   **No two songs open the same way**: different first chord, inversion, register or texture (W021).
2. `segan new song <name> [--key "E dorian"] [--tempo 96] [--meter 6/8] --bars 2 --description "..."` gives tracks
   with labelled empty rows (without `--key`/`--tempo` it takes the suggestion). Rows are the scale's notes, highest first, so **you can't write a wrong note**: pick rows, not
   pitches. Keep the trailing labels on every row (E011 catches a missing or extra row).
3. Write **short patterns** (1-2 bars = 16-32 steps) and reuse them: derived patterns (`from: a` with
   `transpose`, `mute`, `swap`, `shift`, `reverse`, or one lane replaced) and sections (`main: [a, b, a, c]`).
   A 16-bar loop is typically 3-5 written patterns. This keeps files small and the song coherent.
4. Writing music that works (you can't hear it, so follow the craft):
   - Pick a chord per bar (e.g. i VI III VII = Am F C G in A minor; `segan.api.progression` lists the notes).
   - **Bass**: chord roots on the beats (steps 1, 5, 9, 13 of a 16-step bar), octave or fifth hops between.
   - **Melody**: mostly steps between neighbouring rows, a leap now and then followed by a step back; chord
     tones on strong beats (steps 1 and 9); phrases of 2 or 4 bars that answer each other (`transpose` a
     phrase for the answer); rests between phrases. End the loop on a note that leads back to the start.
   - **Harmony/arpeggio**: chord tones in eighths, quieter (track `gain: -3`).
   - **Drums**: kick on 1 and 3 (or every beat for driving music), snare on 2 and 4 (steps 5 and 13), hats in
     eighths; `X` accents and `o` ghosts give groove; a fill in the last bar of a section. Not every song needs a
     kit: hand percussion, a brush, a shaker or no drums at all are textures too.
   - **Dynamics**: roll notes get `velocity:` rows (`X` accent, `o` ghost, `1`-`9`) and `dynamics:` ramps
     (crescendos, swells): a phrase without dynamics sounds mechanical. `humanize: { timing: 8, velocity: 0.1 }` on
     the song loosens the grid (seeded: the same every render; change `seed` for another take).
   - W009 flags minor-second/tritone clashes between tracks on a beat (the meter's beat: a dotted quarter in 6/8;
     notes held from earlier count while still above -30 dB): fix them
     unless you want the tension. A dominant seventh (V7, e.g. C7 going to F) contains a tritone on purpose:
     there it's a judgement call between shortening a note and `lint: { disable: [W009] }`.
   - Many similar patterns, or tired of counting dots: generate lanes with `segan.api` (`segan docs api` has a worked
     example) instead of an ad-hoc script. A generator that writes several songs must vary them: `api.Rng(seed,
     song_name)` for seeded choices, `api.voicing(chord, inversion, spread, octave)` for voicings, different
     progressions, textures and instruments per song. One template with the chords swapped is one song 20 times.
5. **Loops**: `loop: main` (from the start of that section to the end). The file is the whole song **plus the
   first bar(s) of the loop again**, and the loop points sit that many whole bars later (`loop.offset` in the
   manifest; usually one bar: enough bars to cover the longest release + the room tail). So the loop's own end
   rings into its start, the seam is clean and the intro flows naturally into the first pass. The file is
   therefore longer than the arrangement (8 bars at 100 bpm = 19.2 s, the file 21.6 s): that's expected; engines
   use the loop points. Check `seam_click` and the seam view (`<name>.seam.png`). Intros are their own section
   before the loop.
   **Music the player hears for minutes (exploration, towns, combat) must not be one 8-16 bar loop**: players
   tire of it fast. Write 5-10 contrasting sections (derive most with section changes: `{ from: verse,
   semitones: 2 }`, `{ from: chorus, mute: [drums], velocity: 0.7 }`, a breakdown, a bridge) and a `flow:` graph
   so the game picks the next section at run time; preview `--output walk` and look at the whole walk. Plan the
   game's music as a soundtrack (`music/<name>.soundtrack.yaml`): states with song pools, play times and
   silence gaps (silence between songs is what keeps music fresh), and transitions (sync point, fades,
   stingers). A pool of short loops: group same-key loops into `families` and give the state a `crossfade`
   so they flow into each other. `segan docs long-form` and `segan docs soundtrack`.
6. **Variants** in one line each: `danger: { tempo: 150, instrument_swap: { q: r } }`, `calm: { kit: soft_kit }`,
   `night: { semitones: -2 }`, `major: { key: A major }`; combinations with `variant_axes`. Adaptive layering:
   add `"stems"` to `export` (one WAV per track, Godot AudioStreamSynchronized), or a `stems:` block with `groups`
   (one WAV per layer) and `mixes` (the layer combinations the game plays: normalised over the loudest of them;
   each quieter mix gets a `trim_db` the game adds to the stem volumes while it plays that mix).
   Size: many long songs add up (a 3-minute stereo WAV is 30 MB). `"ogg"` in `export` writes music as Ogg
   Vorbis (~10x smaller); a simple chip song can set `sample_rate: 22050` and `channels: mono` for itself.
7. `segan lint`, then `segan preview <song>`: look at the piano roll (is it what you meant?), the spectrogram
   (busy where you expect, bass at the bottom, no smear of clashing notes), the LUFS curve (no holes or spikes),
   `pitch_check` (every note within 50 cents), the seam, and `closest_song` (the most similar song in the project
   and among SEGAN's examples). Long songs: `--from 9 --to 16` (bars) shows a window. Then a human listens to the WAV.
8. **Before you call a soundtrack done**: `segan similarity` (or the MCP `similarity` tool). No pair should share
   an opening (W021) or score over `lint.max_similarity` in its first bars (W024); most songs shouldn't share a
   pitch set or tempo band (W022), and the songs shouldn't all play the same instruments (W023). A song close to
   SEGAN's own examples (W025) means you started from a default: move away from it. Report the similarity numbers
   with the soundtrack.
9. Existing music as MIDI: `segan import midi file.mid --kit <kit>` (quantized, snapped to the key, mapped to
   the kit, with a report of every change); then lint, preview and tidy the patterns.


## Song - `music/<name>.song.yaml`

```yaml
name: overworld
description: "Upbeat exploration loop, A minor, 120 bpm."
kit: nes                      # or segan.toml default_kit; open mode may define `instruments:` inline
tempo: 120                    # bpm (beats of the meter's unit)
meter: [4, 4]
steps_per_beat: 4             # grid: 4 = sixteenth notes in 4/4
swing: 0.0                    # 0-0.5: delays every off-step by that many steps
key: A minor
tracks:                       # order = mix order
  lead:  { roll: [A4, A5] }               # rows = the key's notes from A4 to A5, highest first
  bass:  { roll: [E2, E3], gain: -2 }
  keys:  { roll: [C4, C5], chromatic: true }   # all 12 semitones as rows
  drums: { drums: [k, s, h] }             # rows = these kit keys, in this order
patterns:
  a:
    length: 16                # steps per row (`|` and spaces between the grid and its label don't count)
    lead: |
      ....|....|....|....  A5
      ....|....|..p-|....  G5
      ....|..p-|....|....  F5
      ....|....|....|p---  E5
      ....|....|....|....  D5
      ..p-|....|....|....  C5
      ....|....|....|....  B4
      p-..|....|....|....  A4
    drums: |
      x...|....|x.x.|....  k
      ....|X...|....|X..o  s
      x.x.|x.x.|x.x.|x.x.  h
  b: { from: a, transpose: { lead: 2 } }   # derived pattern
sections:
  intro: [a]
  main: [a, b, a, b]
arrangement: [intro, main]    # play order
loop: main                    # loop from the start of main to the end (true = the whole song; omit = no loop)
markers: { drop: [main, 3] }  # name: [section, bar within it] -> manifest + WAV cue
variants:
  danger: { tempo: 144, instrument_swap: { q: r } }
```

Grid rules:
- **Roll lanes**: a kit key starts a note on that row, `-` holds it (one more step), `.` rests. `pp` = two notes,
  `p-` = one note two steps long. Several rows at once = a chord (needs `voices`). Rows are the scale notes
  inside the track's `roll` range, highest first (all 12 semitones with `chromatic: true`).
- **Drum lanes**: `x` hit, `X` accent (+3.5 dB), `o` ghost (-9 dB), `.` rest.
- Every row has exactly `length` steps; `|` anywhere in a row is ignored (use it to mark beats).
- The label after the row (`A5`, `k`) is optional but checked: write it every time (E011 catches shifted rows).
- A lane left out of a pattern is silent. `-` at the start of a row or after a rest is E015.
- **Dynamics** (any track, mostly rolls): `velocity: { lead: "X...o...|x.3.5..." }` sets the velocity of the notes
  starting at each step: `X` accent (1.5, +3.5 dB), `x` plain, `o` ghost (0.35), `1`-`9` = 0.2-1.8 (`5` = plain),
  `.`/`-` unchanged; one mark per step (`|` ignored). `dynamics: { strings: [[1, -12], [16, 0]] }` then scales a
  track's notes by a ramp in dB (steps from 1, linear between points, held outside them): crescendos, swells,
  fades. Velocity picks sample layers (accent = MIDI 120, ghost 28) and scales synth notes. A derived pattern keeps
  its source's velocities unless it sets its own.
- **Release** (roll tracks): `release: { pad: 3.0 }` in a pattern makes every note of that track in that pattern
  release over that many seconds (0-30) instead of its instrument's release; `release: 3.0` = every roll track. So
  a sting's last chord, in a pattern of its own, rings longer than the kit allows. On a track (`pad: { roll: [C3,
  C5], release: 3.0 }`) it applies to all of the track's notes; a pattern's overrides the track's. A derived
  pattern keeps its source's unless it sets its own. The longer ring counts for the loop offset (W019), flow clips
  and the render cache; an instrument's `max_ring` shorter than the override is lifted to it. Drums keep their decay.

```yaml
  swell:
    length: 16
    strings: |
      v---------------  A4
      ...
    velocity: { horn: "X.......o...o..." }
    dynamics: { strings: [[1, -15], [12, 0], [16, -3]] }
```

Derived patterns: `{ from: <pattern>, ... }` with
`transpose` (scale steps; a number for every roll track or `{ track: steps }`), `semitones` (must land on rows of
the track), `shift` (steps later (+) or earlier (-); notes pushed off the end are E010, tails cut are W012),
`reverse` (true or a list of tracks), `mute` (list of tracks), `swap` (`{ p: q }` instrument keys), and any lane
written out in full to replace that track's lane. The length stays the source's.

Variants (each becomes `<song>.<variant>.wav`): `tempo`, `swing`, `instrument_swap` (`{ q: p }`), `group_swap`
(`{ leads: pads }`, groups of the same size), `kit` (another kit with the same keys), `transpose` (scale steps),
`semitones`, `key` (same notes by scale degree in another key/mode, e.g. `A major`). `variant_axes`:
`{ intensity: { calm: {...}, combat: {...} }, time: { day: {...}, night: {...} } }` makes every combination,
named `calm+day` etc.

Stems (adaptive layers): with `"stems"` in `export` every track is a stem WAV. A `stems:` block (stems for this
song whatever `export` says) groups tracks and names the combinations the game plays:

```yaml
stems:
  groups: { base: [drums, bass], calm: [calm_*], combat: [combat_*] }   # track names or globs; each track in one group
  mixes: { calm: [base, calm], combat: [base, combat] }                 # normalised so the loudest mix hits the target
  main_mix: false                                                       # build only the stems (no full-mix WAV)
```

`segan preview <song> --output mix:calm --output stem:base` renders once and shows each; the main analysis
lists every mix's LUFS (`stem_mixes_lufs`). Without `mixes` the stems follow the full mix's gain (they add up to it).
A quieter mix (a bed without drums can sit 10+ dB under the loudest) gets a `trim_db` in the manifest
(`stem_mixes_trim_db` in the analysis): add it to every stem's volume while the game plays that mix and it is on
target too; it's capped so the mix's true peak stays under `[mix] limiter`. W017: a mix too peaky to reach its
target even with its trim.

More song fields: `humanize: { timing: ms (0-40), velocity: 0-0.5 }` (every note a little early or late and
louder or softer, seeded: the same nudge each time a section plays, in loops and flow clips; `humanize: 8` = timing
only), `seed` (the song's own seed: change it for another take of the humanize; default from the name), `fade_in` /
`fade_out` (seconds; songs that play once: a smooth rise from the start, a fall to silence at the end of the
arrangement, before the room, so the room still rings out),
`category` (default `music`: loudness target), `normalize: false`, `sample_rate` (22050 |
32000 | 44100 | 48000) and `channels` (`mono` | `stereo`): this song's own output format over `[mix]`'s (a chip
loop at 22050 Hz mono is a quarter of the size; it aliases more, which lint checks at that rate), `extends` (a
song with `template: true`; tracks, patterns, sections, variants merge by name), and the common fields below.
