# SEGAN reference

Everything an agent needs to write SEGAN files. All source files are YAML. Asset names: lowercase letters,
digits, `_`, `-`; they must match the file name and be unique across songs and SFX.

## Project layout

```
segan.toml   BRIEF.md   SOUND.md
kits/<name>.kit.yaml     music/<name>.song.yaml     sfx/<name>.sfx.yaml
previews/  (scratch: WAVs, listen sheets; gitignored)    .segan-cache/ (render cache; gitignored)
```

Notes are written like `A4` (= 440 Hz, MIDI 69), `C#5`, `Bb2`, `C-1`. Keys are a root and a scale:
`A minor`, `C major`, `D dorian`, `E phrygian`, `F lydian`, `G mixolydian`, `B locrian`, `A harmonic_minor`,
`A melodic_minor`, `C pentatonic_major`, `A pentatonic_minor`, `A blues`, `C whole_tone`, `C chromatic`.

## Kit - `kits/<name>.kit.yaml`

```yaml
name: nes
description: "2A03-flavoured: pulse leads, triangle bass, noise drums."
instruments:                  # key = ONE letter or digit (any Unicode letter works too); "." "-" "|" are reserved
  p: { name: pulse_lead, osc: pulse, duty: 0.25, env: [0.004, 0.08, 0.65, 0.09], gain: -7, range: [C4, C7] }
  q: { name: pulse_soft, osc: pulse, duty: 0.5, env: [0.02, 0.2, 0.5, 0.2], gain: -10, vibrato: [5.5, 0.12, 0.15] }
  b: { name: tri_bass, osc: triangle, env: [0.002, 0.05, 0.95, 0.04], gain: -2, range: [E1, C4] }
  w: { name: pad, osc: saw, unison: 3, detune: 9, filter: { type: lp, cutoff: 1400 }, env: [0.4, 0.5, 0.8, 0.9], voices: 4 }
  k: { name: kick, drum: kick, tune: 50, decay: 0.22 }
  s: { name: snare, drum: snare, noise: 0.7, decay: 0.14, gain: -5 }
  h: { name: hat, drum: hat, decay: 0.035, gain: -13 }
groups:                       # instrument families, for group_swap variants
  leads: [p, q]
```

Instrument fields (a source is required; everything else optional):

| Field | Meaning |
|---|---|
| `osc` | `sine`, `triangle`, `saw`, `pulse` (all band-limited), `noise` (white), `bitnoise` (sample-and-hold noise pitched by the note: NES/sfxr crunch), `fm` (2-operator) |
| `drum` | `kick`, `snare`, `hat`, `clap`, `tom`, `cymbal` - macros with `tune` (Hz), `decay` (s), `tone` (Hz), `noise` (0-1 mix), `click` (0-1), `punch` (semitones of pitch drop) |
| `duty` | pulse width 0.01-0.99 (0.5 square, 0.25 and 0.125 thinner, NES-like) |
| `pwm` | `[rate_hz, depth]` pulse-width modulation |
| `fm` | `{ ratio, index, env }`: modulator frequency ratio (whole numbers = harmonic, e.g. 1, 2; 3.5 = bell-like), modulation index (brightness), optional index envelope |
| `env` | `[attack, decay, sustain, release]` (seconds, seconds, 0-1, seconds) or `{attack, decay, sustain, release}` |
| `pitch_env` | `[semitones, seconds]` (start that far off and glide to the note) or keyframes `[[t, semitones], ...]` |
| `vibrato` | `[rate_hz, depth_semitones]` or `[rate, depth, delay_s]` |
| `tremolo` | `[rate_hz, depth 0-1]` |
| `arp` | semitone offsets cycled while the note holds, e.g. `[0, 7, 12]`; `arp_rate` notes per second (default 20) |
| `unison`, `detune` | 1-8 stacked voices spread over +/- `detune` cents (with `unison: 1`, `detune` just shifts the pitch) |
| `filter` | `{ type: lp\|hp\|bp, cutoff: Hz, resonance: 0-1, env_amount: octaves, env: [...], keytrack: 0-1 }` |
| `gain` | dB (relative level inside the kit) |
| `pan` | -1 left .. 1 right (stereo music only) |
| `range` | `[lowest, highest]` notes it may play (E007 outside) |
| `voices` | notes at once (default 1: a new note cuts the previous one, like a chip channel; E014 if a track stacks more) |
| `crush` | `{ bits: 1-16, rate: Hz }` lo-fi for this instrument only |
| `note` | the pitch it plays as a one-shot (drum lanes, SFX layers without `pitch`); default C4 |

## SFX - `sfx/<name>.sfx.yaml`

```yaml
name: coin
description: "Bright two-note pickup chime, short, no tail."
category: pickup              # loudness target: [loudness] in segan.toml (unlisted categories use sfx)
preset: coin                  # optional starting point: coin jump laser explosion hit hurt powerup blip select door step
kit: nes                      # optional: layers can use `instrument: <key>`
duration: 0.42                # seconds of dry sound; still sounding at this point = cut (W011); the room tail is added after
layers:
  - id: tone                  # ids let presets/templates be changed one layer at a time
    osc: pulse
    duty: 0.5
    pitch: [[0, B5], [0.07, E6]]   # keyframes [seconds from the layer's start, note or Hz]; one value: `pitch: A5` / `pitch: 440`
    slide: false              # true: glide between keyframes; false: jump
    env: [0.001, 0.08, 0.55, 0.22]
    length: 0.16              # seconds held before the release (default: so the release ends at duration)
    gain: -6                  # dB, or keyframes [[t, dB], ...] (multiplied with the envelope, not replacing it)
  - { id: click, osc: noise, filter: { type: hp, cutoff: 6000 }, env: [0, 0.02, 0, 0.01], gain: -18 }
variations: { count: 4, seed: 7, pitch: 0.5, timbre: 0.1, gain: 1 }   # -> coin.1.wav ... coin.4.wav (+ Godot randomizer)
```

Layer fields = instrument fields (above) plus: `id`, `instrument` (a kit key to start from), `start` (s),
`length` (s), `pitch` (+ `slide`), `gain` keyframes, `cutoff` keyframes (`[[t, Hz], ...]`; adds a low-pass if the
layer has no filter), `distort` (0-1), `ring` (`{ freq: Hz, mix: 0-1 }` ring modulation), `delay`
(`{ time: s, feedback: 0-0.95, mix: 0-1 }`).

More SFX fields:
- `variations`: `count` 1-32, `seed` (change it for a different set), `pitch` (+/- semitones), `timbre` (0-1:
  duty, filter, envelope jitter), `gain` (+/- dB). Each variation is its own WAV, all normalised to the target.
- `phases`: `{ <name>: { duration, loop, crossfade, layers } }` - each phase is its own output `<name>.<phase>.wav`
  (layers default to the SFX's own); e.g. a looping `charge` and a one-shot `release`.
- `loop: true` + `crossfade` (s, default 0.05): a seamless loop (engine hum, alarm): the end blends into the start.
- `normalize: false`: keep the level as written (W013 if it's more than 1 LU off its target).
- `extends: <template>`: start from a file with `template: true` in sfx/ (templates aren't built). Layers merge by
  `id` (fields you give change, the rest stays), other layers are added, `remove: [ids]` drops template layers.
  Own fields (name, description, tags, status, style_version) aren't inherited.
- `preset` works like `extends` with a built-in template (layers merge by id, `remove: [ids]` drops preset layers;
  `segan new sfx --preset P` lists the preset's layer ids). `segan bake sfx <name> [--in-place]` writes everything out.
- The output is `duration` plus the room tail (trimmed at -70 dB). Every output is normalised to its category
  target, however quiet or loud the layers are written (`normalisation_gain_db` in the analysis); write gains for
  the balance between layers, not for the absolute level.

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

More song fields: `category` (default `music`: loudness target), `normalize: false`, `extends` (a song with
`template: true`; tracks, patterns, sections, variants merge by name), and the common fields below.

## Common fields (songs and SFX)

`description` (always), `tags: [...]`, `status: draft|approved` (approved only after a human listened),
`style_version` (set by `segan mark --current`), `template: true` (never built; for `extends`),
`lint: { disable: [W009] }` (warnings that are wrong by design for this asset).

## `segan.toml`

```toml
mode = "strict"               # strict: kits only; open: inline instruments allowed
default_kit = "nes"
output_dir = "build/audio"    # e.g. ../game/assets/generated/audio (apart from PAGAN's output: both write manifest.json)
preview_dir = "previews"
export = ["wav"]              # + "godot" (.import loops/compression, randomizer/synchronized .tres), "stems"
style_version = 1

[mix]                         # shared by every asset; any change re-renders everything
sample_rate = 44100           # 22050 | 32000 | 44100 | 48000
oversample = 2                # 1 | 2 | 4 | 8: synthesis rate multiplier (anti-aliasing; 4 for very high leads)
music_channels = "stereo"
sfx_channels = "mono"
tuning = 440.0
room = 0.15                   # shared reverb amount
room_decay = 0.6              # seconds to fall 60 dB
crush_bits = 0                # 0 off; e.g. 8
crush_rate = 0                # Hz, 0 off
declick = true                # micro-fades at note edges
limiter = -1.0                # true-peak ceiling, dBFS
brightness = 0.0              # dB tilt
warmth = 0.0                  # dB low-mid

[loudness]                    # LUFS per category (songs: integrated; SFX: loudest 400 ms)
music = -16.0
sfx = -14.0
ui = -20.0
foley = -22.0                 # add any category: boss = -12

[godot]
compress = "qoa"              # qoa | ima | none

[lint]
disable = []
max_seam_click = 0.02         # W007
max_leading_silence_ms = 5    # W005
max_instruments = 8           # W003
max_aliasing_db = -50.0       # W010
max_limiting_db = 3.0         # W001: the most the limiter may take off before the target counts as out of reach
max_dc_offset = 0.01          # W008
loudness_tolerance = 1.0      # W001/W013, LU
```

## Commands (all accept `--json`; non-zero exit on errors)

| Command | Purpose |
|---|---|
| `segan init [dir] [--open] [--style chiptune\|synth] [--godot DIR]` | create a project with a starter kit |
| `segan new kit <name>` / `new song <name> [--kit K] [--key "A minor"] [--tempo 120] [--bars 2]` / `new sfx <name> [--preset P] [--kit K]` | starter files (always pass `--description`) |
| `segan kit show [kits]` | every instrument playing a test phrase: `previews/kits/<kit>.listen.png` + WAVs |
| `segan lint [paths] [--warnings-as-errors] [--no-render]` | errors + warnings (audio warnings render the asset; cached) |
| `segan preview <asset...> [--output main\|variant:X\|variation:N\|phase:X\|stem:T] [--from 5 --to 8]` | WAV + listen sheet (+ seam view for loops) per output in `previews/<asset>/`, analysis in `--json` |
| `segan render <asset...>` | WAVs only |
| `segan gallery` | every asset's waveform + spectrum and a loudness chart by category |
| `segan bake sfx <name> [--in-place]` | expand a preset/template into every field |
| `segan import midi <file.mid> [--kit K] [--key K] [--quantize 16] [--bars-per-pattern 2]` | MIDI -> song + change report |
| `segan build [--verify-godot]` | final WAVs + manifest (+ Godot files); `--verify-godot` loads and plays everything headless |
| `segan status [--fast]` | catalogue + what needs attention |
| `segan mark <asset...> [--status approved\|draft] [--current] [--outdated]` | record reviews |
| `segan style bump "note"` | new style version; flags older assets (W006) |
| `segan config show` / `get <key>` / `set <key> <value>` / `unset <key>` | every setting with its default and meaning |
| `segan mix adjust [--brightness dB] [--warmth dB] [--room d] [--crush bits] [--loudness LU] [--dry-run]` | change the whole project's sound |
| `segan skill install [dir]` | install this skill into a repo's `.claude/skills/segan/` |
| `segan mcp [--project DIR] [--allow-godot]` | MCP server over stdio (needs `segan[mcp]`) |

Slow steps print `segan: ...` progress lines on stderr (`--quiet` or `SEGAN_QUIET=1` turns them off).

**MCP tools** (same JSON as the commands): `status`, `read_docs`, `write_doc`, `log_feedback`, `config_show`/
`config_set`/`config_unset`, `kit_list`, `kit_show` (image), `kit_write`, `mix_adjust` (dry run by default),
`scaffold`, `read_asset`, `write_asset` (writes + lints + listen sheet image), `lint`, `preview` (image: sheet or
seam; `audio: true` adds the WAV), `gallery` (image), `mark`, `style_bump`, `import_midi` (path or base64),
`build` (`verify_godot` needs `--allow-godot`), `manifest`. Resources: `segan://workflow`, `segan://reference`,
`segan://brief`, `segan://sound`, `segan://manifest`, `segan://kit/{name}`, `segan://asset/{name}`,
`segan://audio/{name}`. Prompts: `setup_new_game`, `make_sound`, `change_the_sound`, `review_asset`.

## Lint rules

Errors (the build stops): E000 command/usage, E001 YAML/field problem, E002 unknown character in a lane,
E003 row width or row count wrong, E004 missing pattern/section/marker target, E005 kit problem, E006 variant
problem (unknown key/group, group sizes differ, a key with no instrument), E007 note outside an instrument's
range (also in variants), E008 bad loop/phase/crossfade, E009 inline instruments in strict mode, E010 derived
pattern problem, E011 row label doesn't match its row, E012 duplicate asset name, E013 SFX problem, E014 more
notes at once than an instrument's voices, E015 hold with nothing to hold.

Warnings: W001 loudness target out of reach without more limiting than `max_limiting_db` (too short/spiky:
give it body or a quieter category), W002 unused pattern or section, W003 too many instruments in one song,
W004 silent pattern or sound, W005 lead-in silence in an SFX, W006 made under an older style version, W007
click at a loop point, W008 DC offset, W009 tracks clash (minor 2nd/tritone) on a beat, W010 aliasing (raise
`[mix] oversample` or play lower), W011 SFX still sounding at `duration`, W012 note cut at the end of its
pattern, W013 loudness off target with `normalize: false`.
Turn warnings off for one asset with `lint: { disable: [...] }`, project-wide with `[lint] disable`.

## Build output (any engine)

`manifest.json` in `output_dir` is the contract with the game. Per asset: `kind`, `category`, `description`,
`tags`, `status`, `style_version`, `sample_rate`, and
- every audio file as `{ file, seconds, samples, channels, loop }` (`loop` = `{start, end}` in samples, end
  exclusive, or null), `lufs`, `target_lufs`, `limiting_db`;
- SFX: `variations` (list, + `pitch_offset_semitones`), `godot_randomizer`, `phases` (name -> file entry);
- songs: `bpm`, `meter`, `steps_per_beat`, `key`, `beat_seconds`, `beat_count`, `bars`, `sections` (name ->
  start/end in samples, seconds and bars, first occurrence), `arrangement` (every section in order), `markers`
  (name -> sample, seconds, bar), `loop` (`start`/`end` in the file + `offset`: the loop points sit that many
  samples (whole bars, usually one) after the loop section's start and the song's end, because the file carries
  that much of the loop's start again with the end's tail ringing into it; `section`), `variants` (name -> file entry + timing),
  `stems` (track -> file entry) and `godot_stems`.
Files: `music/<song>.wav`, `music/<song>.<variant>.wav`, `stems/<song>/<track>.wav`, `sfx/<name>.wav`,
`sfx/<name>.<n>.wav`, `sfx/<name>.<phase>.wav`. WAVs are 16-bit PCM with a `smpl` loop chunk and `cue` markers.
The build only rewrites files that changed and deletes outputs (and their `.import`) it no longer produces.

## Godot

With `export = ["wav", "godot"]` and `output_dir` inside a Godot 4 project, SEGAN writes each WAV's loop points
and compression into its `.import` (Godot keeps the rest), `sfx/<name>.tres` (AudioStreamRandomizer over the
variations: play it and Godot picks one, never the same twice in a row) and `stems/<song>.tres`
(AudioStreamSynchronized: all stems in sync; change `stream_N/volume` to layer them).

```gdscript
$Music.stream = load("res://assets/generated/audio/music/overworld.wav")   # loops by itself
$Music.play()
$Coin.stream = load("res://assets/generated/audio/sfx/coin.tres")          # a random variation each play
$Coin.play()
```

## Generator scripts: `segan.api`

For many similar sounds or procedural music, write a Python script with `segan.api` (stable, `API_VERSION`):
`note("A4")`, `scale(key, low, high)`, `chord(degree, key, octave, size=3)`, `progression("i VI III VII", key)`,
`euclid(hits, steps, rotate)`, `arpeggiate(notes, steps, rate, order)`, `humanize(row, seed, amount)`,
`Track.roll(name, key, low, high)`, `Track.drums(name, keys)`, `Pattern(length).note(track, step, pitch, length,
key)` / `.hit(track, step, drum, mark)` / `.row(track, drum, "x...x...")` / `.lane(track)`,
`song_yaml(name, tracks=..., patterns=..., sections=..., arrangement=..., key=..., tempo=..., loop=...)`,
`sfx_yaml(name, layers=[...], ...)`. Write the result to a file, then lint and preview it like any other.

```python
from pathlib import Path
from segan import api

key = "F major"
lead = api.Track.roll("lead", key, "F4", "A5")
bass = api.Track.roll("bass", key, "F2", "F3")
drums = api.Track.drums("drums", ["k", "s", "h"])
patterns = {}
for name, numeral in (("a", "I"), ("b", "vi"), ("c", "IV"), ("d", "V")):
    p = api.Pattern(16)
    chord = api.progression(numeral, key, octave=4)[0]
    for step, midi, length in api.arpeggiate(chord, 16, rate=4):
        p.note(lead, step, midi, length, "f")
    p.note(bass, 0, chord[0] - 24, 8, "a").note(bass, 8, chord[0] - 24, 8, "a")
    p.row(drums, "k", "x.......x.......").row(drums, "s", "....x.......x...").row(drums, "h", api.humanize("x.x.x.x.x.x.x.x.", name))
    patterns[name] = p
text = api.song_yaml("shop", kit="fm_soft", key=key, tempo=100, tracks=[lead, bass, drums], patterns=patterns,
                     sections={"main": ["a", "b", "c", "d"]}, arrangement=["main"], loop="main",
                     description="cosy shop loop")
Path("music/shop.song.yaml").write_text(text)
```
