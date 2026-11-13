# Sfx

Making a sound effect: presets, layers, recipes, SFX notation.

## Making a sound effect

0. **Synthesise or record?** Read `[sfx] source` in segan.toml (`segan config get sfx.source`): `synth` = never
   record (W020), `recorded` = prefer recordings, `auto` (default) = decide per sound:
   - **Synthesise**: UI, coins and pickups, retro/arcade sounds, lasers, magic, sci-fi, musical stingers. Steps 1-4.
   - **Record**: anything real-world: animals, voices, footsteps, material impacts (wood, metal, glass, gravel),
     weapons (swords, guns, bows), fire, water, weather, vehicles, ambience. "Recorded SFX" below.
   - **Hybrid**: a recording with synth layers for what it lacks: a sub thump under an explosion or a cannon, a
     shimmer on a magic impact, a tail.
   A request that doesn't say: realistic (record) or stylised (synthesise)? Use the game's style in SOUND.md.
1. Start from the closest **preset**: `segan new sfx <name> --preset <coin|jump|laser|explosion|hit|hurt|powerup|blip|select|door|step> --description "..."`
   (no preset fits: `segan new sfx <name>` gives a one-layer starter). Presets are good starting points;
   change one preset layer by its `id` (only the fields you give change; the scaffold lists the preset's layer
   ids), add layers, drop layers with `remove: [id]`, or `segan bake sfx <name> --in-place` to write every field
   out and edit freely.
2. Think in layers: a **body** (pitched tone: pulse/saw/triangle/sine/fm) + a **transient** (short noise
   burst for the attack) + sometimes a **tail** or **sub** (low drum/sine thump). Recipes:
   | Sound | Recipe |
   |---|---|
   | pickup/coin | square, two quick rising notes (pitch keyframes, no slide), short release |
   | jump | square sweeping up (slide) over ~0.15 s |
   | laser/shot | bright square diving 1-2 octaves fast (slide) + a ring-modulated or noisy fizz |
   | explosion | `bitnoise` with falling pitch through a closing low-pass (`cutoff` keyframes) + a deep kick thump |
   | hit/impact | band-passed noise crack + a falling low square knock + a short tom body |
   | hurt | square falling a fifth with fast vibrato + grit |
   | power-up | fast `arp: [0, 4, 7, 12]` climbing an octave + a sparkle |
   | UI blip/confirm | one or two tiny soft tones, category `ui` |
   | footstep | low-passed noise tap + tiny tom, category `foley`, `variations` |
   | door | noise latch click + band-passed saw creak with vibrato + tom thud |
   | fire crackle / debris / bubbles | `osc: impulses` with `shape: click` / `tick` / `bubble` (one layer of random impulses, not many hand-placed ones); `gain` keyframes fade the density too |
   | engine/hum/alarm | `loop: true` with a `crossfade`, steady layers (or a `phases` loop) |
   | charge-up + release | `phases: { charge: { loop: true, ... }, release: { ... } }` |
3. Things that always matter for SFX:
   - **Start at once**: the main layer at `start: 0` with a fast attack; W005 flags lead-in silence (input lag).
   - `duration` is the hard end of the dry sound; anything still sounding is cut (W011): lengthen it or shorten
     `length`/release.
   - Sounds that repeat a lot (steps, shots, hits) get `variations: { count: 4, pitch: 1, timbre: 0.3 }`;
     Godot gets an AudioStreamRandomizer that cycles them. When the jitter still sounds samey, add `takes:` (other
     layer mixes, envelopes and lengths of the same sound, merged by layer `id`): one asset, one randomizer over all.
   - The file is `duration` plus the shared room's tail (the sheet shows "1.10s + 0.26s room tail"). Short,
     frequent sounds (UI clicks) can go dry: `room: 0` on the SFX or `[room] ui = 0` in segan.toml.
   - `category` picks the loudness target: `sfx` -14, `ui` -20, `foley` -22 LUFS (segan.toml `[loudness]`).
     A sound too short and spiky to reach its target gets W001: `segan preview <name> --json` lists each layer's
     peak/loudness/crest (`layers`); stagger layer starts by 3-9 ms, saturate or lower the peakiest layer, give it
     more body, or use a quieter category.
4. `segan lint <file>` -> fix every error and every warning that's a real problem (a warning you keep on
   purpose goes in the file's `lint: { disable: [...] }` with a comment why); hand over with a clean lint.
   `segan preview <name>` -> **open the listen sheet** and check: the pitch
   movement you wanted (white lines, cyan dots), the attack is instant, the tail decays smoothly, LUFS on
   target, nothing red. Iterate (about 4 rounds at most), then hand the WAV to a human.


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
  duty, filter, envelope jitter), `gain` (+/- dB), `timing` (+/- seconds each layer's start moves, 0-0.5; the
  earliest layer stays put, so the attack stays instant, and no layer moves before it: bursts and bubbles land at
  different moments), `envelope` (0-1: each layer's attack/decay/release up to
  2x longer or shorter), `length` (0-0.5: the whole sound - duration, starts, lengths, keyframe times - up to that
  much longer or shorter). Each variation is its own WAV, all normalised to the target
  (a +dB variation aims above the target: near the limiter cap it gets W001). `include_main: false` builds only
  `<name>.1..N.wav` (no `<name>.wav`) when the game plays the randomizer.
- `takes`: structurally different takes of the same sound under one asset (more variety than `variations`' jitter):
  `takes: [{ duration: 0.4, layers: [{ id: crack, gain: -3 }, { id: thud, remove: true }, { id: snap, osc: noise, ... }] }, ...]`.
  Take 1 is the SFX as written; each listed take (2, 3, ...) starts from the SFX's layers and changes them by `id`
  (fields you give change, the rest stays), adds layers with a new id (or none), and drops one with
  `{ id: <id>, remove: true }`. `duration` defaults to the SFX's; `loop`/`crossfade` are the SFX's. Every take gets the
  SFX's `variations` on top (3 takes x 4 variations = 12 files); a take's own `variations:` merges over the SFX's
  (`variations: null`: none for that take; `include_main` applies per take). Files: `<name>.t<k>.wav` and
  `<name>.t<k>.<n>.wav`; one manifest entry and one Godot randomizer over every take. Takes don't apply to phases.
- `room: 0-1`: this SFX's room send (x `[mix] room`; 0 = dry, no tail). Default: its category's `[room]` entry, else 1.
- `playback: { max_instances, min_gap_s, repeat_attenuation_db }`: hints for the game, copied into the manifest
  as given (the render ignores them): at most `max_instances` (1-64) copies at once (the oldest stops), plays
  closer than `min_gap_s` (0-10 s) to the last start dropped, each copy still sounding makes a new one
  `repeat_attenuation_db` (0-24 dB) quieter. For frequent sounds (gunfire, footsteps, pickups in a burst):
  `playback: { max_instances: 4, min_gap_s: 0.03, repeat_attenuation_db: 2 }`. `segan_sfx.gd` honours them (Godot).
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
