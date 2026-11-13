# Kits

Kits: the palette, identity vs variation, kit notation.

## Kits (the palette)

A kit maps one-character keys to instruments; songs write those keys in their grids. Think of a game's sound as
two layers:
- **Identity** (fixed for the game, in SOUND.md and the kit's `identity` group): 2-3 signature instruments and the
  game's motifs. This is what makes every song sound like the same game.
- **Variation** (per song): 1-2 extra instruments drawn from the wider palette, its own key, mode, tempo, meter,
  register and texture. This is what keeps 20 songs from sounding like one.

So a game has a core kit and more around it: `segan kit roll <name> --style "<words for this part of the game>"
--around core` keeps the identity instruments and rolls the rest (a combat kit, a town kit); or put more
instruments in one kit than any song uses. A song uses its kit's identity instruments plus its own extras: songs
that all play the same 6 instruments blur together (lint W023). Give each instrument a job: one or two leads, a
bass, harmony (pad, strings, choir, organ, keys), colour (pluck, mallet, bell, arpeggio, texture), 3-5 drums.
- **The palette** (`segan docs kits`, `segan docs models`): basic oscillators, models (`pluck` guitar/harp/koto, `bowed` strings with
  real bodies, `formant` voices and choirs, `modal` marimba/vibes/glass/bells/metal, `additive` organs and bells,
  `wavetable`, `supersaw`, 3-4 operator `fm`), `sync`, `sub`, filter LFOs, brass `mute`s, and per-instrument `fx`
  (chorus, ensemble, phaser, flanger, tempo-synced delay, reverb, drive, crush, comb, ring, tremolo, autopan).
  "Strings" are `bowed` or samples, not a detuned saw; a choir is `formant` (or `neosound/voice_oohs`).
- `range` on melodic instruments keeps notes where they sound good (bass: E1-C4; leads: C4-C7); lint E007
  enforces it.
- `voices: 1` (default) is a chip channel: a new note cuts the old. Chords need `voices: 3` or more (E014).
- Arpeggio instruments (`arp:`) use fixed semitone offsets, so make them mode-neutral (`[0, 7, 12]`) unless
  every song is in a major key.
- **Sampled instruments** (`sample: vsco2/violins_sus`, `vcsl/grand_piano`, `karoryfer/brush`, `.sfz`, `.sf2`,
  `.wav`; `segan docs samples`): any kit may mix them with synths. `segan samples list` shows the libraries (vsco2
  orchestra; vcsl keys, mallets, winds, world percussion; karoryfer guitars, basses, erhu, a drum kit; neosound
  voice, steel guitar, flute), `segan samples fetch <library> <instruments>` downloads only what the kit uses into
  the user cache (lint names any that are missing). Sections need `voices` for chords; `_sus` instruments hold while the note does
  (W014 if a note outlasts its sample: re-strike long notes), `pizz`/`stac`/harp/percussion ring by themselves.
  Mix them like an orchestra: strings hold chords, one lead line (horn, flute, solo violin), harp or pizz for
  motion, timpani and crash only on downbeats; a bigger room (`[mix] room = 0.3`, `room_decay = 1.6`).
- After any kit edit: `segan kit show <kit>`, look at the sheet (each instrument's segment: pitch lines on the
  white targets, attack/decay shape, no red), check `W010` aliasing, then a human listens.


## Kit - `kits/<name>.kit.yaml`

```yaml
name: nes
description: "2A03-flavoured: pulse leads, triangle bass, noise drums."
instruments:                  # key = ONE letter or digit (any Unicode letter works too); "." "-" "|" are reserved
  p: { name: pulse_lead, osc: pulse, duty: 0.25, env: [0.004, 0.08, 0.65, 0.09], gain: -7, range: [C4, C7] }
  q: { name: pulse_soft, osc: pulse, duty: 0.5, env: [0.02, 0.2, 0.5, 0.2], gain: -10, vibrato: [5.5, 0.12, 0.15] }
  b: { name: tri_bass, osc: triangle, env: [0.002, 0.05, 0.95, 0.04], gain: -2, range: [E1, C4] }
  w: { name: strings, osc: bowed, unison: 5, detune: 6, env: [0.3, 0, 1, 0.6], voices: 4, fx: [ensemble] }
  k: { name: kick, drum: kick, tune: 50, decay: 0.22 }
  s: { name: snare, drum: snare, noise: 0.7, decay: 0.14, gain: -5 }
  h: { name: hat, drum: hat, decay: 0.035, gain: -13 }
groups:                       # instrument families, for group_swap variants
  leads: [p, q]
```

Instrument fields (a source is required; everything else optional):

| Field | Meaning |
|---|---|
| `osc` | `sine`, `triangle`, `saw`, `pulse` (all band-limited), `noise` (white), `bitnoise` (sample-and-hold noise pitched by the note: NES/sfxr crunch), `fm` (2-operator, or 3-4 operators), `impulses` (sparse random clicks, ticks or bubbles: crackle, debris, fizz; below), and the models `pluck`, `bowed`, `additive`, `wavetable`, `formant`, `modal`, `supersaw` (below) |
| `drum` | `kick`, `snare`, `hat`, `clap`, `tom`, `cymbal`, `rim`, `shaker`, `cowbell`, `block` (wood block), `conga`, `brush` (brush swish), `metal` (struck scrap metal/anvil) - macros with `tune` (Hz), `decay` (s), `tone` (Hz), `noise` (0-1 mix), `click` (0-1), `punch` (semitones of pitch drop) |
| `sample` | recorded sound instead of a synth (see Samples below): `vsco2/violins_sus` (library), `samples/x.sfz`, `samples/gm.sf2` + `preset`, `samples/hit.wav` + `root` |
| `duty` | pulse width 0.01-0.99 (0.5 square, 0.25 and 0.125 thinner, NES-like) |
| `pwm` | `[rate_hz, depth]` pulse-width modulation |
| `fm` | `{ ratio, index, env }`: modulator frequency ratio (whole numbers = harmonic, e.g. 1, 2; 3.5 = bell-like), modulation index (brightness), optional index envelope. 3-4 operators: `{ algorithm: stack\|pairs\|branch\|stack3\|parallel, ops: [{ ratio, index, out, env, detune, mod }, ...] }` (op 1 is heard; `stack` = 4 -> 3 -> 2 -> 1, `pairs` = 2 -> 1 + 4 -> 3, `branch` = 2 -> 1 <- 3 <- 4, `stack3` = 3 -> 2 -> 1 + 4, `parallel` = all heard; an op's `mod: [3, 4]` overrides the routing) |
| `sub` | sub-oscillator: `-1` / `-2` (octaves) or `{ octave, wave: sine\|square\|triangle, level: dB }` |
| `impulses` | for `osc: impulses`: `{ density: 30 (per second, random Poisson timing), shape: click\|tick\|bubble, pitch: [300, 3000] (low, high: Hz or notes, picked per impulse, log-uniform), decay: 0.02 (s per impulse), level: [0.5, 1] (amplitude range per impulse) }`. `click` = a 1-2 ms noise burst (fire crackle, gravel, sparks; `pitch` and `decay` unused), `tick` = a short decaying sine at the picked pitch (debris, ticking metal), `bubble` = a sine rising ~30% over its decay (water, boiling, sinking). The note's pitch doesn't move it; in an SFX layer the `gain` keyframes scale both the level and the density (a fade thins the impulses out). Seeded like `noise`: every variation gets its own pattern |
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
| `filter` | `{ type: lp\|hp\|bp\|notch, cutoff: Hz, resonance: 0-1, bandwidth: octaves, env_amount: octaves, env: [...], keytrack: 0-1, lfo: [rate_hz, octaves], slope: 12\|24 }` (`lfo` sweeps the cutoff up and back from each note's start; `bandwidth` (bp/notch only, 0.05-4) is the width between the -3 dB points and overrides `resonance`: `bandwidth: 0.3, slope: 24` is a narrow, steep band for zips and whistles) |
| `gain` | dB (relative level inside the kit) |
| `pan` | -1 left .. 1 right (stereo music only) |
| `range` | `[lowest, highest]` notes it may play (E007 outside) |
| `voices` | notes at once (default 1: a new note cuts the previous one, like a chip channel; E014 if a track stacks more) |
| `crush` | `{ bits: 1-16, rate: Hz }` lo-fi for this instrument only |
| `note` | the pitch it plays as a one-shot (drum lanes, SFX layers without `pitch`); default C4 |
