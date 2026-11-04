# Models

Instrument models (pluck, bowed, formant, modal, additive, wavetable, supersaw, fm) and effects (fx).

## Instrument models

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

## Effects (`fx`)

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
| `filter` | `type, cutoff: 1200, resonance: 0.3, bandwidth: octaves (bp/notch; overrides resonance), lfo: [rate, octaves]` (auto-wah, tempo-synced sweeps) |

Echoes and reverb lengthen a song's loop file like a long release does (W019 if it runs more than 2 bars past the song).
