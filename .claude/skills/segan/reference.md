# SEGAN reference

Everything an agent needs to write SEGAN files. All source files are YAML. Asset names: lowercase letters,
digits, `_`, `-`; they must match the file name and be unique across songs and SFX.

## Project layout

```
segan.toml   BRIEF.md   SOUND.md
kits/<name>.kit.yaml     music/<name>.song.yaml     sfx/<name>.sfx.yaml     music/<name>.soundtrack.yaml
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
| `osc` | `sine`, `triangle`, `saw`, `pulse` (all band-limited), `noise` (white), `bitnoise` (sample-and-hold noise pitched by the note: NES/sfxr crunch), `fm` (2-operator, or 3-4 operators), and the models `pluck`, `bowed`, `additive`, `wavetable`, `formant`, `modal`, `supersaw` (below) |
| `drum` | `kick`, `snare`, `hat`, `clap`, `tom`, `cymbal`, `rim`, `shaker`, `cowbell`, `block` (wood block), `conga`, `brush` (brush swish), `metal` (struck scrap metal/anvil) - macros with `tune` (Hz), `decay` (s), `tone` (Hz), `noise` (0-1 mix), `click` (0-1), `punch` (semitones of pitch drop) |
| `sample` | recorded sound instead of a synth (see Samples below): `vsco2/violins_sus` (library), `samples/x.sfz`, `samples/gm.sf2` + `preset`, `samples/hit.wav` + `root` |
| `duty` | pulse width 0.01-0.99 (0.5 square, 0.25 and 0.125 thinner, NES-like) |
| `pwm` | `[rate_hz, depth]` pulse-width modulation |
| `fm` | `{ ratio, index, env }`: modulator frequency ratio (whole numbers = harmonic, e.g. 1, 2; 3.5 = bell-like), modulation index (brightness), optional index envelope. 3-4 operators: `{ algorithm: stack\|pairs\|branch\|stack3\|parallel, ops: [{ ratio, index, out, env, detune, mod }, ...] }` (op 1 is heard; `stack` = 4 -> 3 -> 2 -> 1, `pairs` = 2 -> 1 + 4 -> 3, `branch` = 2 -> 1 <- 3 <- 4, `stack3` = 3 -> 2 -> 1 + 4, `parallel` = all heard; an op's `mod: [3, 4]` overrides the routing) |
| `sub` | sub-oscillator: `-1` / `-2` (octaves) or `{ octave, wave: sine\|square\|triangle, level: dB }` |
| `sync` | hard sync for `saw`/`pulse`: a ratio (`2.6`) or `{ ratio, env_amount: octaves, env }` (the classic sync sweep) |
| `mute` | brass mute tone: `straight` (thin, bright), `cup` (soft, covered), `harmon` (buzzy, nasal; add `filter: { lfo }` for wah-wah) |
| `fx` | per-instrument effects, in order: `[{ chorus: {...} }, { delay: {...} }]` (see Effects below) |
| `max_ring` | seconds a note may ring after it ends (gate), then a 50 ms fade: chokes long one-shots and releases (timpani rolls, tam-tam, crash, low harp) so a loop file doesn't grow by bars (W019) |
| `env` | `[attack, decay, sustain, release]` (seconds, seconds, 0-1, seconds) or `{attack, decay, sustain, release, curve}`; decay/release are (1 - x)^3 and stop at zero; `[..., exp]` / `curve: exp` = exponential: decay = time to fall 60 dB and it rings on (bells, plucks), release = time to -60 dB then zero |
| `pitch_env` | `[semitones, seconds]` (start that far off and glide to the note) or keyframes `[[t, semitones], ...]` |
| `vibrato` | `[rate_hz, depth_semitones]` or `[rate, depth, delay_s]` |
| `tremolo` | `[rate_hz, depth 0-1]` |
| `arp` | semitone offsets cycled while the note holds, e.g. `[0, 7, 12]`; `arp_rate` notes per second (default 20) |
| `unison`, `detune` | 1-8 stacked voices spread over +/- `detune` cents (with `unison: 1`, `detune` just shifts the pitch) |
| `filter` | `{ type: lp\|hp\|bp\|notch, cutoff: Hz, resonance: 0-1, env_amount: octaves, env: [...], keytrack: 0-1, lfo: [rate_hz, octaves], slope: 12\|24 }` (`lfo` sweeps the cutoff up and back from each note's start) |
| `gain` | dB (relative level inside the kit) |
| `pan` | -1 left .. 1 right (stereo music only) |
| `range` | `[lowest, highest]` notes it may play (E007 outside) |
| `voices` | notes at once (default 1: a new note cuts the previous one, like a chip channel; E014 if a track stacks more) |
| `crush` | `{ bits: 1-16, rate: Hz }` lo-fi for this instrument only |
| `note` | the pitch it plays as a one-shot (drum lanes, SFX layers without `pitch`); default C4 |

### Instrument models

An `osc` model takes a block named after it; a string picks a preset; no block = the defaults.

| Model | What it is | Block (defaults) | Presets |
|---|---|---|---|
| `pluck` | plucked string (Karplus-Strong): guitar, harp, koto, pizzicato, harpsichord | `{ decay: 3 (s, C4 to -60 dB), brightness: 0.5, pick: 0.15 (0-0.5), damping: 0.5 (high notes shorter), body: none\|guitar\|violin\|viola\|cello\|bass }` | `guitar nylon steel harp koto pizz bass muted harpsichord` |
| `bowed` | bowed strings: per player a saw with its own pitch drift and onset, bow noise, the body's resonances; `unison` = players (4-8 = a section) | `{ body: auto\|violin\|viola\|cello\|bass, bow: 0.3, drift: 5 (cents) }` | a body name |
| `additive` | sum of partials: organs, flutes, clarinet, bells, glass | `{ partials: preset \| [1, 0.5, 0.3] (harmonic amps) \| [[ratio, amp], [ratio, amp, decay_s]], drawbars: "888000000", stretch: 0 (inharmonicity) }` | `organ organ_full organ_soft flute clarinet hollow warm bright bell glass chime` |
| `wavetable` | single-cycle frames morphed by position, envelope or LFO | `{ table, position: 0-1, env, env_amount: -1..1, lfo: [rate, depth] }` | tables `analog pulse vocal glass digital organ harmonic sync` |
| `formant` | a voice: five formants of a vowel; `unison` = a choir (#22) | `{ vowel: a\|e\|i\|o\|u (ah eh ee oh oo) or [ah, oh] or [[0, ah], [0.8, oh]], voice: auto\|soprano\|alto\|tenor\|bass, breath: 0.1, drift: 4 }` | a vowel |
| `modal` | struck resonator: mallets, bells, metal | `{ material, strike: 0.5 (mallet hardness), decay: s at C4 }` | `marimba vibraphone xylophone glass bell tubular kalimba steel_drum wood metal membrane` |
| `supersaw` | seven detuned saws (trance, hoover with `pitch_env` + chorus) | `{ spread: 30 (cents), mix: 0.6 }` | - |

`pluck` and `modal` ring by themselves: their default `env` holds while the note does and damps on release (0.3 s,
modal 1 s). `bowed`/`formant` take `vibrato` like any instrument (a section: `vibrato: [5.2, 0.12, 0.3]`). `auto`
bodies and voices follow the instrument's `range`.

```yaml
  g: { name: nylon, osc: pluck, pluck: nylon, voices: 6, range: [E2, B5] }
  v: { name: strings, osc: bowed, unison: 6, detune: 6, voices: 6, env: [0.25, 0, 1, 0.6], vibrato: [5.2, 0.1, 0.3], range: [G3, E6], fx: [ensemble] }
  c: { name: choir_ah, osc: formant, formant: { vowel: [ah, oh], voice: bass }, unison: 5, detune: 8, voices: 4, env: [0.4, 0, 1, 0.8], range: [E2, C4] }
  m: { name: marimba, osc: modal, modal: { material: marimba, strike: 0.4 }, voices: 4, range: [C3, C6] }
  o: { name: organ, osc: additive, additive: { drawbars: "888000000" }, voices: 4, fx: [{ chorus: { rate: 6, depth: 1.5, mix: 0.4 } }] }
  w: { name: glassy, osc: wavetable, wavetable: { table: glass, env: [0.5, 1.0, 0.3, 1.0], env_amount: 0.6 }, voices: 4 }
  t: { name: muted_trumpet, sample: vsco2/trumpet_sus, mute: harmon }
```

### Effects (`fx`)

Applied in order to each note after it's rendered (and after a mono voice is cut, so echoes ring on); LFOs start
with the note, so a note sounds the same wherever it's played (loops and flow clips stay exact). Rates and times
take Hz/seconds or a **note value** that follows the song's tempo: `"1/4"`, dotted `"1/8."`, triplet `"1/8t"`, bars
`"2"` (SFX count them at 120 bpm). In stereo songs `chorus`, `ensemble`, `autopan`, `reverb` and a `pingpong` delay
make the note stereo. A shorthand `fx: [chorus]` uses the defaults.

| Effect | Settings (defaults) |
|---|---|
| `chorus` | `rate: 0.8, depth: 3 (ms), delay: 12 (ms), mix: 0.5, voices: 2, width: 1` |
| `ensemble` | `depth: 0.5, mix: 0.6, width: 1` (the string-machine ensemble: lush strings and pads) |
| `flanger` | `rate: 0.25, depth: 2 (ms), delay: 1.5 (ms), feedback: 0.5, mix: 0.5` |
| `phaser` | `rate: 0.4, depth: 0.8, stages: 4, center: 900 (Hz), mix: 0.5` |
| `delay` | `time: 0.3, feedback: 0.35, mix: 0.3, damp: 5000 (Hz, each echo darker), pingpong: false` |
| `reverb` | `mix: 0.3, decay: 1.5` (its own space, on top of the project room) |
| `drive` | `amount: 0.5, tone: 8000 (Hz), mix: 1` (saturation, oversampled) |
| `crush` | `bits: 8, rate: 0 (Hz)` |
| `comb` | `ratio: 1 (x the note), feedback: 0.7, mix: 0.4` (metallic resonance) |
| `ring` | `ratio: 2 (x the note) or freq: Hz, mix: 0.5` |
| `tremolo` | `rate: 5, depth: 0.5, shape: sine\|square` |
| `autopan` | `rate: 0.5, depth: 0.7` |
| `filter` | `type, cutoff: 1200, resonance: 0.3, lfo: [rate, octaves]` (auto-wah, tempo-synced sweeps) |

Echoes and reverb lengthen a song's loop file like a long release does (W019 if it runs more than 2 bars past the song).

### Samples (orchestral and other recorded instruments)

`sample:` replaces `osc`/`drum`; envelope, filter, vibrato, pitch keyframes, gain, voices and crush still apply.

```yaml
instruments:
  v: { name: violins, sample: vsco2/violins_sus, voices: 4, env: [0.04, 0, 1, 0.35] }   # library instrument
  r: { name: harp, sample: vsco2/harp, voices: 8 }                                        # one-shot: rings to its end
  T: { name: timpani, sample: vsco2/timpani, voices: 2 }
  B: { name: bass_drum, sample: vsco2/bass_drum }                                        # unpitched: drum lanes
  g: { sample: { sf2: samples/GeneralUser.sf2, preset: 48, bank: 0 } }                   # SoundFont preset (number or name)
  k: { sample: { sfz: samples/keys.sfz, velocity: 100 } }                                # always that velocity layer
  z: { sample: { wav: samples/zap.wav, root: A4, loop: true } }                           # one WAV, pitched from root
```

- **Library** `vsco2` = VSCO 2 Community Edition (CC0, Versilian Studios): strings (sections: `violins_`, `violas_`,
  `cellos_` `sus|trem|pizz|spic`, `basses_sus|pizz`, `violin_solo`, `harp`), brass (`horn_`, `trumpet_`, `trombone_`,
  `tuba_` `sus|stac`), woodwinds (`flute_`, `oboe_`, `clarinet_`, `bassoon_` `sus|stac`, `piccolo`), percussion
  (`timpani`, `timpani_roll`, `glockenspiel`, `marimba`, `xylophone`, `bass_drum`, `snare`, `crash`, `sus_cymbal`,
  `tam_tam`, `triangle`, `tambourine`), `piano`. `segan samples list` shows them with sizes and key ranges (`range` in `--json`; unpitched = none); the audio isn't in
  SEGAN: `segan samples fetch vsco2 violins_sus harp ...` downloads only those (pinned commit, checked) into a
  user cache shared by every project. Lint says what to fetch if a kit needs more. Every library instrument is
  levelled to the same loudness, so kit `gain` is pure balance.
- Paths (wav/sfz/sf2) are relative to the project folder (the one with segan.toml). WAV: PCM 8-32-bit or float,
  any rate, mono or stereo (mixed to mono; tracks pan and the room widens). `smpl` loops are used.
- `env` defaults to the file's own (SFZ `ampeg_*`, SF2 volume envelope); `range` defaults to the mapped keys
  (E007 outside). Note velocity picks the layer: plain notes 80 (mf), accents `X` 120, ghosts `o` 28.
- Sustained samples (`_sus`) play while the note is held, then release; a note held longer than its sample
  is silent at the end (W014: shorten it or re-strike). One-shots (`pizz`, `stac`, `harp`, percussion, SFZ
  `loop_mode=one_shot`, `one_shot: true`) ring to their natural end whatever the note length; `voices` caps how
  many ring at once. In an SFX layer, `length:` chokes a one-shot (then its `env` release).
- SFZ subset: `<control> <global> <master> <group> <region>`, `sample default_path key lokey hikey
  pitch_keycenter lovel hivel tune transpose volume amplitude offset end loop_mode loop_start loop_end
  seq_length seq_position lorand hirand trigger ampeg_*`, `#define`. SF2: key/velocity zones, root key, tuning,
  loops, attenuation, volume envelope (modulators, filters and effects are ignored).
  `segan samples list file.sf2` lists a SoundFont's presets.
- Sampled songs render slower than synth ones (a 30 s orchestral loop ~20 s cold); renders are cached.

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
`length` (s), `pitch` (note, Hz or keyframes; a note can carry a cents offset, `A4+15c` / `C6-30c`, for detuned
copies of a layer) (+ `slide`), `gain` keyframes, `cutoff` keyframes (`[[t, Hz], ...]`; adds a low-pass if the
layer has no filter), `distort` (0-1; the layer's `gain` applies after it, so gain never changes the grit), `ring` (`{ freq: Hz, mix: 0-1 }` ring modulation), `delay`
(`{ time: s, feedback: 0-0.95, mix: 0-1 }`).

More SFX fields:
- `variations`: `count` 1-32, `seed` (change it for a different set), `pitch` (+/- semitones), `timbre` (0-1:
  duty, filter, envelope jitter), `gain` (+/- dB), `timing` (+/- seconds each layer's start moves, 0-0.5; never
  before 0: bursts and bubbles land at different moments), `envelope` (0-1: each layer's attack/decay/release up to
  2x longer or shorter), `length` (0-0.5: the whole sound - duration, starts, lengths, keyframe times - up to that
  much longer or shorter). Each variation is its own WAV, all normalised to the target
  (a +dB variation aims above the target: near the limiter cap it gets W001). `include_main: false` builds only
  `<name>.1..N.wav` (no `<name>.wav`) when the game plays the randomizer.
- `room: 0-1`: this SFX's room send (x `[mix] room`; 0 = dry, no tail). Default: its category's `[room]` entry, else 1.
- `phases`: `{ <name>: { duration, loop, crossfade, layers } }` - each phase is its own output `<name>.<phase>.wav`
  (layers default to the SFX's own); e.g. a looping `charge` and a one-shot `release`.
- `loop: true` + `crossfade` (s, default 0.05): a seamless loop (engine hum, alarm): the end blends into the start.
  For a seam you can't hear: give held layers a `length:` past the loop end (so nothing releases inside the loop),
  and make every keyframe curve (pitch, gain, cutoff) end on the value it starts with; check W007 and the seam view.
- `normalize: false`: keep the level as written (W013 if it's more than 1 LU off its target).
- `extends: <template>`: start from a file with `template: true` in sfx/ (templates aren't built). Layers merge by
  `id` (fields you give change, the rest stays), other layers are added, `remove: [ids]` drops template layers.
  Own fields (name, description, tags, status, style_version) aren't inherited.
- `preset` works like `extends` with a built-in template (layers merge by id, `remove: [ids]` drops preset layers;
  `segan new sfx --preset P` lists the preset's layer ids). `segan bake sfx <name> [--in-place]` writes everything out.
- The output is `duration` plus the room tail (cut at `[mix] tail_trim_db`, default -70 dB below the peak). Every output is normalised to its category
  target, however quiet or loud the layers are written (`normalisation_gain_db` in the analysis); write gains for
  the balance between layers, not for the absolute level.

### Recorded layers (realistic SFX)

```yaml
name: lion_roar
description: "Big cat roar, distant, ~2 s: a CC BY recording pitched down and stretched, with a sub growl."
duration: 2.2
layers:
  - id: roar
    sample: freesound:123456       # in sounds.lock (`segan sounds add freesound:123456`); or a file: sounds/roar.wav
    trim: [0.12, 2.0]              # seconds of the file: [start, end] (or just the start)
    shift: -4                      # semitones, the length stays (-24..24)
    stretch: 1.15                  # x the length, the pitch stays (0.25-4)
    fade: [0, 0.4]                 # seconds: [in, out]
    filter: { type: lp, cutoff: 3000 }
  - { id: sub, osc: sine, pitch: [[0, A1], [1.6, E1]], slide: true, env: [0.05, 0.6, 0.4, 0.5], gain: -8 }
variations: { count: 3, seed: 1, gain: 1 }
```

`sample:` in an SFX layer makes it a **recorded layer** when it is a sound file path (`.wav`, `.ogg`, `.flac`,
`.mp3`; relative to the project; ogg/flac/mp3 need `pip install "segan[ogg]"`), `freesound:<id>`, or a list of
them (one is picked per variation, from the seed; the same every render). A recorded layer plays its file as
recorded: one-shot, mixed to mono, peak-normalised (so `gain` is the balance against the other layers, whatever
level it was recorded at). Its own fields: `trim`, `reverse: true`, `fade: [in, out]`, `shift` (semitones) and
`stretch` (x length): pitch and length change **independently** (phase vocoder with phase locking; transients
soften a little at big stretches). Applied in that order: trim, reverse, stretch/shift, fades. Every other layer
field works too: `pitch` keyframes are varispeed (C4 = as recorded: `pitch: [[0, C4], [1, G3]]` slows down like
tape), `gain`/`cutoff` keyframes, `filter`, `env` (default: plays as recorded), `length` (chokes it, then
`env`'s release), `distort`, `ring`, `delay`, `start`. `osc`/`drum`/`instrument` can't be on a recorded layer:
synth sounds go on their own layers (they mix freely). The mapping form `sample: { wav: x.wav, root: A4 }` stays
a pitched sampled instrument.

**Licences** (E020): only CC0 and CC BY (any version), never non-commercial, share-alike or unknown. A Freesound
sound's licence, author and page come from `sounds.lock`; a local file needs `licence:` (`CC0`, `CC-BY-4.0`, or the
creativecommons.org URL), `source:` (the page it came from, or "own recording") and, for CC BY, `author:` on
the layer, or a sounds.lock entry (`segan sounds add sounds/x.wav --licence CC-BY-4.0 --source URL --author NAME`).

**sounds.lock** (next to segan.toml; commit it): one `[sounds."<ref>"]` table per sound with `name`, `author`,
`licence`, `licence_url`, `url` (the Freesound page) or `source`, `file` (`preview-hq-ogg`, `local`), `download`,
`sha256`. Freesound files live in the user cache (`$SEGAN_SOUNDS`, else `~/.cache/segan/sounds`), fetched on first
use and checked against the sha256 (a mismatch is E019); `segan sounds vendor` copies them into
`<project>/sounds/freesound/`, which builds use first. SEGAN fetches Freesound's HQ Ogg preview (~192 kbit/s;
the API key alone allows it); originals need an OAuth2 login and aren't supported.

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
only), `seed` (the song's own seed: change it for another take of the humanize; default from the name),
`category` (default `music`: loudness target), `normalize: false`, `sample_rate` (22050 |
32000 | 44100 | 48000) and `channels` (`mono` | `stereo`): this song's own output format over `[mix]`'s (a chip
loop at 22050 Hz mono is a quarter of the size; it aliases more, which lint checks at that rate), `extends` (a
song with `template: true`; tracks, patterns, sections, variants merge by name), and the common fields below.

### Long-form music: section changes and `flow`

An 8-bar loop on repeat wears players out within minutes. Write more material cheaply, and let the game walk it:

**Section changes.** A section is a pattern list or a mapping that changes its patterns' notes as they play:

```yaml
sections:
  verse: [a, b, a, c]
  verse_up: { from: verse, semitones: 2 }                  # same section a tone higher (a key change)
  chorus: { patterns: [d, d, e, f] }
  chorus_soft: { from: chorus, mute: [drums], velocity: 0.7, instrument_swap: { p: q } }
  breakdown: { patterns: [a, b], mute: [lead, harmony] }
  bridge: { patterns: [g, h], key: A major }               # same scale degrees in another key/mode
```

`patterns` or `from` (another section: its patterns and changes, then this one's fields over them), `transpose`
(scale steps), `semitones`, `key`, `instrument_swap`, `group_swap`, `mute` (tracks), `velocity` (0.05-2, or
`{ track: scale }`). Pitch changes apply at play time, so `semitones: 2` doesn't need the rows to exist; a song
variant applies first, the section's changes on top. Ranges (E007) and voices (E014) are checked per section.

**Flow (the game picks the next section).** Without `flow`, a song is one arrangement with one loop. With it,
the game (SEGAN's Godot director, or your own player from the manifest) chains sections at run time:

```yaml
arrangement: [intro, verse, chorus, verse_up, chorus, bridge, chorus]   # still the linear version (preview, simple games)
flow:
  start: intro                       # or a list: one is picked
  next:                              # which sections may follow which: a list, or weights
    intro: [verse]
    verse: { chorus: 3, breakdown: 1 }
    verse_up: [chorus]
    chorus: { verse: 2, verse_up: 1, bridge: 1, chorus_soft: 1 }
    chorus_soft: [verse, bridge]
    breakdown: [chorus]
    bridge: { chorus: 1, verse_up: 1 }
  end: outro                         # optional: played when the game ends the song (any section may go to it)
  no_repeat: true                    # never the same section twice in a row unless it's the only way on (default)
  variants: [danger]                 # variants that get flow clips too (default: none)
```

Every flow section must be whole bars (E017); every section reachable from `start` and able to go on (or be
the `end`). Each section is built as clips: `flow/<song>/<section>.head.wav` (its first bar(s), cold),
`<section>.from.<prev>.wav` (the same bars with the previous section's ring-out baked in), `<section>.wav` (the
rest) and `<section>.tail.wav` (its ring-out when the music stops after it). Chained back to back they equal a
linear render of that path, so every seam is clean whatever order the game picks. W015: a section shorter than
the ring-out before it (that ring-out gets cut).

Writing for flow: 5-10 sections of 4-8 bars with real contrast (a breakdown, a bridge, a key change, a soft
chorus) give minutes before an order repeats; derive most of them with section changes. Keep each section's
first bar playable after any of its predecessors (the harmony joins), and end each section on a cadence that
can lead into all of its `next` sections. `segan preview <song> --output walk` (or `walk:<seed>`) renders a
3-minute seeded walk from the clips (`<song>.walk1.wav`, sections marked on the sheet, `join_error` in
the analysis: max difference from a straight render of the path, < 0.001): listen to that, not just the arrangement.

## Soundtrack - `music/<name>.soundtrack.yaml`

Which songs a game plays in which state, and how it moves between states (played by the Godot director):

```yaml
name: main
start: explore
states:
  explore: { songs: { overworld: 2, village: 1, cave: 1 }, play: [120, 240], gap: [10, 40], fade_out: 3, crossfade: 4 }
  combat: { songs: [combat, overworld.danger] }      # `song.variant`
  menu: [title]                                      # a list = songs only
families:                                            # songs that cross-fade into each other inside a state
  a_minor: [overworld, village]                      # (`overworld` is the main version; list variants as `song.variant`)
transitions:                                         # most specific wins: "from>to", "from>*", "*>to", "*"
  "*": { at: bar, fade: 2 }                          # the default is { at: bar, fade: 2 }
  explore>combat: { at: beat, fade: 0.5, stinger: hit, start: main }
  combat>explore: { at: section, fade: 4, fade_in: 2 }
```

State: `songs` (list, or weights; never the same song twice in a row when there are others), `play` (seconds a
song plays before it ends, a number or [min, max]; a flow song then finishes its section and plays `end` or
its tail, a looping song fades out over `fade_out`; default: forever when the state has one song and no gap,
else [120, 240]), `gap` (seconds of silence between songs, number or [min, max]: silence makes music last),
`crossfade` (seconds; when the next song is in the same family as the one ending, it comes in on the next bar
and the two overlap this long, no gap; songs of different families still fade out, wait the gap and start;
default 0 = never). `families`: family -> songs (each song in one family; a song in none is its own family).
A big shuffled pool of short loops: put the loops of one key/tempo in a family, give the state a `crossfade`
and a short `play` (e.g. [30, 60]), and they flow into each other; changing family gets a breath of silence.
Transition: `at` (`now`, `beat`, `bar`, `section`, `end`: when the switch happens, on the old song's grid),
`fade` (seconds the old song fades out; 0 with `at: section` lets a flow song ring out naturally), `fade_in`,
`stinger` (an SFX played at the switch), `start` (a section of the new song to start at). E018: unknown
state/song/variant/SFX/section or family member, or a bad field; W016: a cross-fade between songs whose keys
clash, in a transition or a family (keep fades between related keys, or use a short fade with a stinger).

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
export = ["wav"]              # + "godot" (.import loops/compression, randomizer/synchronized .tres), "stems",
                              #   "ogg" (music as Ogg Vorbis, ~10x smaller; SFX stay WAV; pip install "segan[ogg]")
style_version = 1
seed = 4417312093             # the project seed (`segan init` picks one): suggestions and rolled kits branch from it; renders don't use it

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
tail_trim_db = -70.0          # room tail cut this far below the peak (-40 = shorter files)

[room]                        # room send per category, 0-1 x mix.room (unlisted: 1); e.g. ui = 0 (dry, no tail)

[loudness]                    # LUFS per category, -60..-5 (songs: integrated; SFX: loudest 400 ms; unlisted categories, songs too, use sfx)
music = -16.0
sfx = -14.0
ui = -20.0
foley = -22.0                 # add any category: boss = -12

[godot]
compress = "qoa"              # qoa | ima | none

[sfx]
source = "auto"               # auto: synthesise stylised sounds, record real-world ones (the skill's rule);
                              # synth: no recordings (W020); recorded: prefer recordings

[ogg]
quality = 0.4                 # Vorbis quality 0-1 (0.4 is about 128 kbit/s stereo)

[lint]
disable = []
max_seam_click = 0.02         # W007
max_leading_silence_ms = 5    # W005
max_instruments = 8           # W003
max_aliasing_db = -50.0       # W010
max_limiting_db = 3.0         # W001: the most the limiter may take off before the target counts as out of reach
max_dc_offset = 0.01          # W008
loudness_tolerance = 1.0      # W001/W013, LU
max_similarity = 0.85         # W024-W026: how alike (0-1) two songs' first 8 bars may be

[similarity]
local_store = false           # true: keep song fingerprints in ~/.cache/segan/fingerprints (on build and `segan similarity`)
                              #   and compare with your other projects on this machine (W026)
shipped = true                # compare with SEGAN's own examples (W025)
```

## Commands (all accept `--json`; non-zero exit on errors)

Songs and SFX render in several processes (`-j N` on lint/build, or `SEGAN_JOBS=N`; default: the CPU count up to 8;
`1` = one process); the output is identical. Renders are cached per asset and keyed on the kit instruments the
asset actually plays, so editing one instrument re-renders only what uses it.

| Command | Purpose |
|---|---|
| `segan init [dir] [--open] [--style chiptune\|synth\|orchestral\|"<words>"] [--godot DIR]` | create a project with a random project `seed` and a starter kit (words, e.g. `--style "cold ship, warm crew"`: a kit `core` rolled from the seed, with an `identity` group); `--godot` builds into `DIR/assets/generated/audio`, or `DIR/assets/audio` when a PAGAN project there already builds into `assets/generated`; warns when the two output folders are the same or nested |
| `segan new kit <name>` / `new song <name> [--kit K] [--key "A minor"] [--tempo 120] [--meter 3/4] [--bars 2]` / `new sfx <name> [--preset P] [--kit K]` | starter files (always pass `--description`); a song without `--key`/`--tempo` gets the seeded suggestion (below), away from the project's songs |
| `segan suggest song <name> [--mood "words"] [--take N]` | a plan for a new song away from the project's songs: key and mode, tempo, meter, opening texture, opening voicing (inversion, spread, register), progression, instruments (the kit's identity + extras, maybe a new one), a `seed`, and the `segan new song` command; seeded by the project seed (`--take` = another plan) |
| `segan kit roll <name> --style "words" [--around KIT] [--samples\|--no-samples] [--take N] [--dry-run] [--force]` | a kit from style words and the project seed: `identity` group (2-3 signature instruments), bass, harmony, colour, 3-5 drums, from the models, effects and drums above (samples when the words ask for acoustic/orchestral, or `--samples`); `--around` keeps another kit's identity instruments |
| `segan samples list [library\|file.sf2]` / `segan samples fetch <library> <instrument...> [--all]` | sample libraries: instruments, key ranges and what's downloaded / download instruments |
| `segan sounds search "<query>" [--max-seconds N] [--licence cc0\|cc-by] [--limit 15] [--sort score\|rating_desc\|...]` | Freesound search (needs `FREESOUND_API_KEY`): ref, name, author, licence, duration, rating, tags; only CC0 / CC BY |
| `segan sounds add freesound:<id>` / `add <file> --licence L --source URL [--author A]` | check the licence, fetch the HQ preview into the user cache, record it in `sounds.lock` (a local file: its licence, source, author) |
| `segan sounds inspect <ref...>` | length, peak, loudness, brightness (centroid), pitch, onsets of recordings (a Freesound ref is fetched into the cache, not recorded) |
| `segan sounds credits [--out FILE]` | `SOUND_CREDITS.md`: attribution for every recorded sound (required for CC BY) |
| `segan sounds vendor [--all]` | copy the Freesound sounds in use into `<project>/sounds/` (offline builds; off by default) |
| `segan kit show [kits]` | every instrument playing a test phrase: `previews/kits/<kit>.listen.png` + WAVs; `--json` gives each instrument's `range` |
| `segan lint [paths] [--warnings-as-errors] [--no-render] [-j N]` | errors + warnings (audio warnings render the asset; cached); exits 1 on errors, 0 when there are only warnings, 1 on warnings too with `--warnings-as-errors` (CI) |
| `segan preview <asset...> [--output main\|variant:X\|variation:N\|phase:X\|stem:T\|mix:M\|flow:CLIP\|walk[:SEED] ...] [--from 5 --to 8]` | WAV + listen sheet (+ seam view for loops) per output in `previews/<asset>/`, analysis in `--json` (SFX: `layers` = each layer dry on its own, `peak_db`/`lufs`/`crest_db`, plus the dry mix); flow songs also get a walk; `--output reel` (an SFX): the main sound and every variation back to back, 0.4 s apart, to judge the variety; `--format ogg\|mp3` also writes each preview compressed, to share (needs `segan[ogg]`) |
| `segan render <asset...>` | WAVs only |
| `segan gallery` | every asset's waveform + spectrum and a loudness chart by category |
| `segan bake sfx <name> [--in-place]` | expand a preset/template into every field |
| `segan import midi <file.mid> [--kit K] [--key K] [--quantize 16] [--bars-per-pattern 2]` | MIDI -> song + change report |
| `segan similarity [songs] [--shipped] [--machine] [--top 15]` | how alike songs are: pairs by `overall` with `harmony` (chroma per bar), `rhythm` (onsets), `timbre` (instruments), `register`, `tempo` (0-1 each), `same_opening`, `same_pitch_set`, `opening_score` (what W024 compares); `closest` per song. `--shipped` adds SEGAN's examples, `--machine` other projects (local_store) |
| `segan build [--verify-godot] [-j N]` | final WAVs + manifest (+ Godot files); `--verify-godot` loads and plays everything headless |
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
`sounds_search`, `sounds_add`, `sounds_inspect`, `sounds_credits` (recorded sounds; search needs `FREESOUND_API_KEY`),
`build` (`verify_godot` needs `--allow-godot`), `manifest`. Resources: `segan://workflow`, `segan://reference`,
`segan://brief`, `segan://sound`, `segan://manifest`, `segan://kit/{name}`, `segan://asset/{name}`,
`segan://audio/{name}`. Prompts: `setup_new_game`, `make_sound`, `change_the_sound`, `review_asset`.

## Lint rules

Errors (the build stops): E000 command/usage, E001 YAML/field problem, E002 unknown character in a lane,
E003 row width or row count wrong, E004 missing pattern/section/marker target, E005 kit problem, E006 variant
problem (unknown key/group, group sizes differ, a key with no instrument), E007 note outside an instrument's
range (also in variants), E008 bad loop/phase/crossfade, E009 inline instruments in strict mode, E010 derived
pattern problem, E011 row label doesn't match its row, E012 duplicate asset name, E013 SFX problem, E014 more
notes at once than an instrument's voices, E015 hold with nothing to hold, E016 `stems:` problem (a track in no
group or two, unknown stem in a mix), E017 `flow:` problem (unknown or unreachable section, dead end, bad weight,
a section that isn't whole bars), E018 soundtrack problem (unknown state, song, variant, stinger SFX or start
section; a bad field), E019 recorded sound can't be used (file missing or undecodable, not in sounds.lock, sha256
mismatch, fetch failed), E020 recorded sound's licence (missing, not CC0/CC BY, no source, CC BY without an author).

Warnings: W001 loudness target out of reach without more limiting than `max_limiting_db` (too short/spiky:
stagger layer starts 3-9 ms, tame the peakiest layer (`preview --json` `layers`), give it body, or a quieter category; for a percussive song: `category: music_soft` + `music_soft = -19` under
`[loudness]`), W002 unused pattern or section, W003 too many instruments in one song,
W004 silent pattern or sound, W005 lead-in silence in an SFX, W006 made under an older style version, W007
click at a loop point, W008 DC offset, W009 tracks clash (minor 2nd/tritone) on a beat (the felt beat: every 3 units in 6/8, 9/8, 12/8; a held note counts while above -30 dB), W010 aliasing (raise
`[mix] oversample` or play lower), W011 SFX still sounding at `duration`, W012 note cut at the end of its
pattern, W013 loudness off target with `normalize: false`, W014 a note held longer than its sample (no loop):
it goes silent before it ends, W015 a flow section shorter than the ring-out of a section before it, W016 a
soundtrack cross-fade between songs in clashing keys, W017 a stem mix that can't reach its target even with its
trim, W018 an SFX noise layer whose filter removes more than 12 dB of its level (a narrow band-pass): raise its gain,
W019 a looping song's file runs more than 2 bars past the song because its last notes ring that long: give those
instruments `max_ring`, W020 a recorded layer in a project with `[sfx] source = "synth"`.
Sameness (songs are compared with every other song of the project; `segan similarity` shows the numbers): W021 two
songs open on the same notes (step 1, two or more notes), W022 more than half of the songs share one pitch set (D minor
= F major) or sit within 10 bpm, W023 every song plays one kit with nearly the same instruments, W024 two songs' first 8
bars score over `lint.max_similarity` (harmony, rhythm, instruments), W025 a song close to SEGAN's own examples (the
demo, reference.md's generator example), W026 a song close to one from another project on this machine (`[similarity]
local_store`). W022/W023 are reported on segan.toml.
Turn warnings off for one asset with `lint: { disable: [...] }`, for every asset of a category with
`[lint.<category>] disable = ["W017"]` (e.g. `[lint.battle_music]`), project-wide with `[lint] disable`.

## Build output (any engine)

`manifest.json` in `output_dir` is the contract with the game. Per asset: `kind`, `category`, `description`,
`tags`, `status`, `style_version`, `sample_rate`, and
- every audio file as `{ file, seconds, samples, channels, loop }` (`loop` = `{start, end}` in samples, end
  exclusive, or null), `lufs`, `target_lufs`, `limiting_db`;
- SFX: `lufs`/`target_lufs`/`limiting_db` on the main sound and on each variation; `dry_seconds` on every one-shot file entry (the sound without its room tail: how long a voice pool should
  count it busy; `seconds` includes the tail), `variations` (list, + `pitch_offset_semitones`), `godot_randomizer`, `phases` (name -> file entry);
- songs: `bpm`, `meter`, `steps_per_beat`, `key`, `beat_seconds`, `beat_count`, `bars`, `sections` (name ->
  start/end in samples, seconds and bars, first occurrence), `arrangement` (every section in order), `markers`
  (name -> sample, seconds, bar), `loop` (`start`/`end` in the file + `offset`: the loop points sit that many
  samples (whole bars, usually one) after the loop section's start and the song's end, because the file carries
  that much of the loop's start again with the end's tail ringing into it; `section`), `variants` (name -> file entry + timing),
  `stems` (stem -> file entry + `tracks`), `stem_mixes` (mix -> `stems`, `lufs`, `trim_db`), `stems_normalised_over` and
  `godot_stems`. With `main_mix: false` / `include_main: false` the entry has no `file` (timing and loop stay).
- flow songs: `flow` = `start`, `next` (section -> {successor: weight}), `end`, `no_repeat`, `head_bars`, `sections`
  (name -> `samples` (its length: play the next section exactly this many samples after it starts), `seconds`,
  `bars`, `head_samples`, `head`/`rest`/`tail` files and `from` (previous section -> head file; when the previous
  section isn't listed, the cold `head`)), `variants` (variant -> the same clips). A walk plays, per section, the
  head (`from[prev]` or `head`) for `head_samples` samples, then `rest` for `samples - head_samples`; after the
  last section, its `tail`. Clip files carry 32 extra samples (Godot stops a WAV a few samples before its end):
  play each for its stated length, not to its end.
Top level: `soundtracks` (name -> `start`, `states` (state -> `songs` [{song, variant, weight, family}], `play`,
`gap`, `fade_out`, `crossfade`), `families`, `transitions` ("from>to" -> `at`, `fade`, `fade_in`, `stinger`,
`start`), `default_transition`).
Files: `music/<song>.wav`, `music/<song>.<variant>.wav`, `stems/<song>/<track>.wav`, `flow/<song>[.<variant>]/<clip>.wav`,
`sfx/<name>.wav`, `sfx/<name>.<n>.wav`, `sfx/<name>.<phase>.wav`. WAVs are 16-bit PCM with a `smpl` loop chunk and `cue` markers.
With `"ogg"` in `export`, every music file (songs, variants, stems, flow clips) is `.ogg` instead (same samples
count; a looping file ends exactly at its loop end, the loop restarts at `loop.start`); SFX stay `.wav`.
The build only rewrites files that changed and deletes outputs (and their `.import`) it no longer produces.

## Godot

With `export = ["wav", "godot"]` and `output_dir` inside a Godot 4 project, SEGAN writes each WAV's loop points
and compression into its `.import` (Godot keeps the rest; an `.ogg` gets `loop` and `loop_offset`), `sfx/<name>.tres` (AudioStreamRandomizer over the
variations: play it and Godot picks one, never the same twice in a row) and `stems/<song>.tres`
(AudioStreamSynchronized: all stems in sync; change `stream_N/volume` to layer them).
A new file gets a minimal `.import` (importer, type, SEGAN's params); Godot adds `uid`, `path` and `dest_files` the
first time it imports it, so the first commit after a build is followed by one more `.import` diff once the editor
(or `segan build --verify-godot`) has run. Commit that too; it doesn't recur, and SEGAN keeps Godot's additions.

```gdscript
$Music.stream = load("res://assets/generated/audio/music/overworld.wav")   # loops by itself
$Music.play()
$Coin.stream = load("res://assets/generated/audio/sfx/coin.tres")          # a random variation each play
$Coin.play()
```

**Music director** (`segan_music.gd`, written next to `manifest.json` when the project has a flow song or a
soundtrack). Add it as an autoload named `SeganMusic` (Project Settings > Globals > Autoload), then:

```gdscript
SeganMusic.play_soundtrack("main")             # the soundtrack's start state
SeganMusic.set_state("combat")                 # its transitions decide when and how (beat/bar/section, fades, stinger)
SeganMusic.play_song("overworld", "danger")    # one song directly; a flow song walks its sections until stopped
SeganMusic.queue_section("bridge")             # a flow song's next section, instead of a random pick
SeganMusic.stop(2.0)                           # fade out over 2 s (stop(0.0, "section") lets a flow song ring out)
SeganMusic.section_started.connect(func(song, section): print(song, " ", section))
```

Signals: `song_started(song, variant)`, `section_started(song, section)`, `song_finished(song)`,
`state_changed(state)`. Properties: `bus` (default `Master`), `buffer_seconds` (0.3: audio queued ahead; changes
land after it), `random_seed` (0 = a different walk every run). It chains sections sample-exactly (an
AudioStreamGenerator fed from the clips); a new song starts on the old one's grid within one audio mix chunk.
Native `AudioStreamInteractive`/`AudioStreamPlaylist` aren't generated: in Godot 4.7 the first switches a mix
chunk early and cuts tails, the second clicks at every seam.

## Generator scripts: `segan.api`

For many similar sounds or procedural music, write a Python script with `segan.api` (stable, `API_VERSION`):
`note("A4")`, `scale(key, low, high)`, `chord(degree, key, octave, size=3)`, `progression("i VI III VII", key)`,
`euclid(hits, steps, rotate)`, `arpeggiate(notes, steps, rate, order)`, `humanize(row, seed, amount)`,
`invert(notes, inversion)`, `voicing(notes, inversion, spread="close"|"open"|"wide", octave, bass)`, `Rng(seed, ...)`
(seeded `random()`, `choice()`, `range()`, `weighted()`: the same on every machine),
`Track.roll(name, key, low, high)`, `Track.drums(name, keys)`, `Pattern(length).note(track, step, pitch, length,
key, velocity=None)` (written as a `velocity:` row) / `.hit(track, step, drum, mark)` / `.row(track, drum, "x...x...")` / `.lane(track)`,
`song_yaml(name, tracks=..., patterns=..., sections=..., arrangement=..., key=..., tempo=..., loop=...)`,
`sfx_yaml(name, layers=[...], ...)` (both take `comments={"patterns.chorus": "text", ...}`: `#` lines above
those keys). `dedupe(patterns, sections)` merges identical patterns (sections follow); `derive("a", a, b, tracks)`
writes `b` as `{from: a, transpose, mute, shift}` when it is one (else None). Write the result to a file, then lint and preview it like any other.

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
