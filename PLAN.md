# PLAN.md — SEGAN (Sound Effect Grammar And Notation)

> **To the agent reading this:** this is your brief for a new tool. Read it fully, then read PAGAN's
> `PLAN.md`, `CLAUDE.md` and `src/pagan/skill/` (in `lukasgolino/PAGAN`). The new tool copies PAGAN's
> design almost one-for-one, so you need to know it. The owner is busy: batch your questions, give each one a
> recommended default, and keep building on the defaults while you wait for answers.
>
> Name (owner, 2026-10-19, final): **SEGAN** (*Sound Effect Grammar And Notation*). It is PAGAN's
> **sister library**: same design, conventions and quality bar, with sound instead of pixels. Despite
> "Sound Effect" in the name, SEGAN covers **both SFX and music** (songs, §5.2). PAGAN lives at
> `/home/lgolino/repos/PAGAN` (GitHub `lukasgolino/pagan`); read it whenever you need to see how something was done.

---

## 0. Verdict

**Feasible. Build it as its own library in its own repo** (`lukasgolino/segan`), as PAGAN's sister library.

### Feasibility

| Part | Confidence | Why |
|---|---|---|
| SFX (coin, jump, laser, hit, explosion, UI) | **High** | sfxr/bfxr/ZzFX showed that ~20 synth parameters cover most game SFX. An LLM can reason about them well ("a laser is a fast falling pitch sweep on a square wave"). |
| Short chiptune/synth loops (8–64 bars) | **Medium-high** | LLMs write ABC/MML/tracker notation reasonably well. A step grid is easy to read as text, the same way a pixel grid is. |
| Long-form or orchestral music, realistic instruments | **Low (out of scope)** | Needs sampled instruments (SoundFonts) and real composition skill. Leave it to "later". |
| Agent self-review | **Medium. This is the crux.** | Claude can't hear. It *can* read images: a spectrogram, a waveform and a piano roll, plus numbers (LUFS, peak, onsets, detected pitch). A spike (2026-10-19) showed rhythm, pitch steps, envelopes **and aliasing** clearly in a 800×420 PNG. It shows correctness; it can't judge musicality. A human must approve music (the `status: draft → approved` flow already exists in PAGAN). |
| Deterministic, byte-identical builds | **High, with care** | numpy synth → int16 WAV gave the same bytes on reruns in the spike. Cross-platform float differences need the same treatment as PAGAN's renderer (see §8). |

The "constraint" idea carries over directly. Pixel art is to images what chiptune/synth is to audio: a small
fixed palette (instrument kit), a grid (step sequencer) and consistent rules (one mix, one loudness target).
That gives cohesion, and it's something an agent can write as text.

### Why its own repo, not inside PAGAN

- **Versioning.** Game repos pin PAGAN tags, and any change to rendered pixels forces a PAGAN release.
  Audio changes would churn pixel-tool tags, and the reverse, for no reason.
- **Name and scope.** PAGAN = *Pixel Art* Grammar And Notation. CLAUDE.md says it stays general-purpose
  *for art*.
- **Skill triggering.** The `pagan` skill's description is about art. A separate `segan` skill keeps both
  descriptions sharp, so agents load the right one.
- **Dependencies.** Audio needs `scipy` (IIR filters, see §4). Pixel-art users shouldn't have to install it.
- **Precedent.** The website already lives in its own repo.
- **Cost:** ~2k lines of PAGAN infrastructure get copied (§3) and can drift apart. That's acceptable. Revisit
  a shared `pagan-core` package only if fixes keep having to be made twice.

---

## 1. The big picture

SEGAN translates between AI and game audio. Agents write sound as palette-keyed YAML: instrument kits,
step-grid patterns and parametric SFX. SEGAN lints them, renders previews the agent can *look at*, and builds
engine-ready assets: WAVs with embedded loop points, `manifest.json`, and Godot resources.

Same principles as PAGAN, unchanged:
- **Text is the source; audio is derived.** No AI audio generators, no hosted services.
- **Keys, not raw values.** Grids use one-character instrument keys from a kit. In strict mode, notes can only
  sit on rows of the song's scale, so an off-key note is impossible by construction (the way off-palette
  colours are in PAGAN).
- **Strict mode** (project kits, project mix) **or open mode** (inline instruments, one-offs).
- **Deterministic builds**, `--json` everywhere, all findings collected with rule id + file:line + `where` + a fix hint.
- **Engine-agnostic.** `manifest.json` is the contract; the Godot export is a convenience.
- **Driven by an orchestrator agent.** Configurable, saved settings; global changes re-render everything.

---

## 2. PAGAN → SEGAN concept map

This table is the design. Every PAGAN power has an audio equivalent.

| PAGAN | SEGAN | Notes |
|---|---|---|
| palette `*.pal.yaml` (key → colour) | **kit** `kits/*.kit.yaml` (key → instrument patch) | one char per instrument; `.`, `-`, `|` reserved |
| ramps (dark → light) | **groups** (instrument families: leads, bass, drums) | used by `group_swap` variants |
| *(implicit: the colour space)* | **scale/key** per song (`key: A minor`) | roll rows = scale degrees, so off-key notes can't happen |
| sprite frames (pixel grids) | **patterns** (step grids, one lane per track) | |
| `.` transparent | `.` rest; `-` hold | |
| animations (frames + fps + loop) | **sections + arrangement** (patterns in order, tempo, loop point) | |
| derived frames `{from, flip, shift}` | **derived patterns** `{from, transpose, shift, reverse, mute, swap}` | |
| `mirror: horizontal` | `repeat:` / call-and-response (`{from: a, transpose: 2}`) | |
| `outline: auto` | **auto-declick** (micro-fades at note/sample edges) | on by default, can be turned off |
| 3D model + project camera/light | **SFX patch** `sfx/*.sfx.yaml` + project **`[mix]`** | every SFX gets the same room, crush and loudness, so they match |
| headings `directions: 8` | **`variations: N`** (seeded timbre/pitch variants) | → Godot `AudioStreamRandomizer` |
| pose animations | **SFX phases** (e.g. `charge`, `release`, `loop`) | |
| `supersample` | **`oversample`** (synth at 2–4×, decimate) | anti-aliasing, same idea |
| `light.baked = false` + normal maps | **stems** export (one WAV per track, sample-aligned) | for adaptive/vertical mixing in the engine |
| variants `key_swap` / `ramp_swap` / `palette:` | `instrument_swap` / `group_swap` / `kit:` + `tempo`, `transpose`, `key` | "danger" or "underwater" versions in one line |
| `variant_axes` (`a+b`) | same | e.g. `{intensity: [calm, combat]} × {zone: [day, night]}` |
| `extends` template models | `extends` template SFX/songs | weapon families |
| `pagan palette adjust` (OKLab) | **`segan mix adjust`** (brightness/EQ tilt, warmth, room, crush, loudness) | everything re-renders |
| `pagan import png` (snap to palette) | **`segan import midi`** (quantize + snap to scale/kit, with a change report) | |
| preview PNG / contact sheet / GIF | **listen sheet PNG** + WAV (see §6) | how the agent "looks" at audio |
| tiling check | **loop-seam check** (end→start splice view + click metric) | |
| gallery | **gallery** (every SFX side by side + a loudness chart) | catches inconsistencies across the set |
| `pagan.api` (Canvas, corner_tiles…) | `segan.api` (scales, chords, euclid, arpeggiate, pattern writers) | for generator scripts |
| BRIEF.md / STYLE.md / style_version | BRIEF.md / **SOUND.md** / style_version | same flow (W006, `mark`, `style bump`) |
| `pagan status / mark / config / mcp / skill` | identical commands | copy them |
| SpriteFrames / TileSet `.tres` | `.import` loop/compress edits, `AudioStreamRandomizer` / `AudioStreamPlaylist` / `AudioStreamInteractive` `.tres` | |

---

## 3. Repository and reuse

New repo `SEGAN/`, `src/` layout like PAGAN. Python 3.11+, setuptools, MIT, mypy strict, pytest, CI on 3.11–3.13.

**Copy from PAGAN and adapt** (keep the copies close to the originals so later fixes port easily, and note
the origin in each module's docstring):

| PAGAN module | Reuse |
|---|---|
| `findings.py`, `yamlio.py` | as is (rename PaganError → SeganError) |
| `project.py` | discovery (walk up to `segan.toml`), open mode, unknown-key errors; new config sections |
| `settings.py` | the registry + safe TOML text edits, as is; new settings |
| `manage.py` | catalogue/status, `mark`, `style bump`, line-level text edits |
| `build.py` | write-only-if-changed, manifest, stale-file cleanup (+ Godot `.import` sidecars) |
| `buildinfo.py`, `__main__.py`, CLI skeleton, `skill install`, `mcp_server.py` (lock, cwd pin, captured stdout, path confinement) | pattern copied |
| `exporters/godot.py` | headless-verify harness, `.import` line editing (as done for `mipmaps`) |
| `templates/` | BRIEF.md, SOUND.md, segan.toml |

New modules: `kit.py`, `synth.py` (oscillators, envelopes, filters, noise, effects), `song.py`
(patterns/tracks/sections parsing), `sfx.py`, `sequence.py` (song → note events), `mix.py` (bus, room,
crush, oversample, normalisation, limiter), `analysis.py` (peak, LUFS, onsets, pitch, seam, aliasing),
`wavio.py` (deterministic WAV writer with `smpl`/`cue` chunks), `listen.py` (listen-sheet images),
`midi.py` (import, hand-written parser; no dependency), `lint.py`, `api.py`, `exporters/godot.py`.

---

## 4. Tech and dependencies

- **numpy** (synthesis, analysis) and **Pillow** (listen sheets), as in PAGAN.
- **PyYAML**, stdlib `tomllib`, stdlib `wave` (+ hand-written chunks; no audio I/O library needed for WAV).
- **scipy**: needs owner approval (§12). It provides `scipy.signal.sosfilt` for the filters, the K-weighting
  (BS.1770 LUFS) and resampling/decimation. Pure-Python per-sample IIR loops are ~100× too slow for songs.
  Time-varying filters (filter envelopes) run in 64-sample blocks, carrying filter state (`zi`) across blocks.
- Optional later: `soundfile` (OGG/Opus export), `mcp` extra (same as PAGAN).
- **Output is WAV only in v1.** It's deterministic and needs no encoder. Engines compress on import (Godot: QOA/IMA-ADPCM).

---

## 5. Source formats (the SEGAN notation)

All YAML. Grids use block scalars (`|`), so they read like pictures. Names: lowercase `[a-z0-9_-]`, matching
the file name, unique across songs and SFX.

### 5.1 Kit — `kits/<name>.kit.yaml` (≈ palette)

```yaml
name: nes
description: "2A03-flavoured: two pulses, triangle bass, noise drums."
instruments:                       # key = ONE letter/digit; "." "-" "|" reserved
  p: { name: pulse_lead, osc: pulse, duty: 0.25, env: [0.005, 0.08, 0.6, 0.12], gain: -6 }
  q: { name: pulse_soft, osc: pulse, duty: 0.5,  env: [0.02, 0.2, 0.5, 0.3], gain: -9, vibrato: [5.5, 0.15] }
  b: { name: tri_bass,   osc: triangle, env: [0.002, 0.05, 0.9, 0.05], gain: -4, range: [E1, C4] }
  k: { name: kick,  drum: kick,  tune: 55, decay: 0.18 }
  s: { name: snare, drum: snare, tone: 190, noise: 0.7, decay: 0.12 }
  h: { name: hat,   drum: hat,   decay: 0.03, gain: -12 }
groups:
  leads: [p, q]
  drums: [k, s, h]
```

Instrument fields (all optional except a source):
- **source**: `osc: sine|triangle|saw|pulse|noise|fm`, or `drum: kick|snare|hat|clap|tom|cymbal` (macros built
  from the same primitives, so the parameters are inspectable). Later: `sample: path.wav` (§11).
- `duty`, `fm: { ratio, index, env }`, `detune` (cents), `unison`.
- `env: [attack, decay, sustain, release]` (seconds, seconds, 0–1, seconds), or the mapping form.
- `pitch_env` (semitones over time), `vibrato: [rate_hz, depth_semitones]`, `tremolo`, `arp` (semitone offsets).
- `filter: { type: lp|hp|bp, cutoff, resonance, env_amount, env }`.
- `gain` (dB), `pan` (−1..1), `range: [low, high]` (playable notes; E-rule outside it), `voices` (polyphony; default 1, as in chiptune).
- `crush: { bits, rate }` per instrument (the project-wide one is in `[mix]`).

`segan kit show <kit>` renders every instrument playing a test phrase (C-major arpeggio, or a single hit for
drums) as one listen sheet + WAVs. This is the `palette show` equivalent: the first thing an owner signs off on.

### 5.2 Song — `music/<name>.song.yaml` (≈ sprite)

```yaml
name: overworld
description: "Upbeat exploration loop, A minor, 120 bpm, chiptune; loops seamlessly."
kit: nes                      # strict: kit name; open mode may inline `instruments:`
tempo: 120                    # bpm
meter: [4, 4]
steps_per_beat: 4             # grid resolution (16ths)
swing: 0.0                    # 0..0.5, delays every off-step
key: A minor                  # root + scale: major|minor|dorian|...|pentatonic_minor|blues|chromatic

tracks:                       # order = mix order; each lane in a pattern refers to a track
  lead:  { roll: [A4, A5], gain: -2 }            # rows = scale notes in range, highest first
  bass:  { roll: [A2, A3] }
  drums: { drums: [k, s, h] }                    # rows = kit drum keys, in this order

patterns:
  a:
    length: 16                # steps; every lane row must be exactly this wide
    lead: |
      ................  A5
      ............p---  G5
      ........p---....  F5
      ....p---........  E5
      ................  D5
      p---............  C5
      ................  B4
      ................  A4
    bass: |
      ................  A3
      ................  G3
      ................  F3
      ................  E3
      ................  D3
      ................  C3
      ................  B2
      b-..b-..b-..b-..  A2
    drums: |
      x...x...x...x...  k
      ....X.......X...  s
      x.x.x.x.xoxox.x.  h
  b:   { from: a, transpose: { lead: 2 } }              # derived: lead up two scale degrees
  fill:                                                 # derived + override one lane
    from: a
    mute: [lead]
    drums: |
      x...x...x.x.x.x.  k
      ....X...X.XXXXXX  s
      ................  h

sections:                     # ≈ animations
  intro: [a]
  main:  [a, b, a, fill]
arrangement: [intro, main]    # play order
loop: main                    # loops from the start of `main` to the end (sample-exact loop points)

variants:
  danger: { tempo: 140, instrument_swap: { q: p } }
  night:  { kit: nes_soft, transpose: -2 }        # transpose in scale degrees; `semitones:` also allowed

markers: { drop: [main, 2] }  # named cue points (section, bar) → manifest + WAV cue chunk
# plus description, tags, status, style_version, lint: as in PAGAN
```

Grid rules:
- **Roll lanes**: one row per scale note in `range`, highest first. Char = kit key (starts a note), `-` holds
  the previous note, `.` is a rest. `pp` = two notes; `p-` = one note two steps long. Stacked rows = chords.
  A track with `chromatic: true` gets all 12 semitones as rows.
- **Drum lanes**: one row per drum key listed in the track. Chars: `x` hit, `X` accent, `o` ghost, `.` rest.
- **Trailing row labels** (`A5`, `k`) are optional, but when present they're checked (E011). They catch the
  classic grid bug of a missing or extra row that shifts everything by one. The skill tells agents to always write them.
- `|` may be used inside a row as a bar separator for readability; it's ignored and doesn't count as a step.
- Lanes left out of a pattern are silent. A note held past the end of a pattern stops there (W012).

### 5.3 SFX — `sfx/<name>.sfx.yaml` (≈ model)

```yaml
name: coin
description: "Bright two-note pickup chime, short, no tail."
category: pickup              # loudness group + bus in the manifest
kit: nes                      # optional: layers may use `instrument: p` from the kit
preset: coin                  # optional starting point: coin|jump|laser|explosion|hit|hurt|powerup|blip|select|door|step
duration: 0.25                # seconds; W011 if an envelope is still sounding at the end
layers:
  - osc: pulse
    duty: 0.5
    pitch: [[0, B5], [0.06, E6]]          # keyframes (t, note|Hz); `slide: true` glides, else steps
    env: [0.002, 0.05, 0.4, 0.15]
  - osc: noise
    filter: { type: hp, cutoff: 6000 }
    env: [0.0, 0.02, 0.0, 0.0]
    gain: -18
variations: { count: 4, seed: 7, pitch: 0.5, timbre: 0.1 }   # → coin.1.wav … coin.4.wav + randomizer
phases:                       # optional; each phase is its own output (≈ pose animations)
  charge:  { duration: 1.0, loop: true, layers: [...] }
  release: { layers: [...] }
extends: weapon_base          # optional template (template: true), same merge rules as PAGAN's R15
```

Layer = instrument fields (§5.1) + `start` (s) + pitch/filter/gain keyframes + effects (`distort`, `delay`,
`crush`, `ring`). `segan bake sfx <name>` writes the effective, fully expanded patch for hand-tuning (≈ `pagan bake`).

### 5.4 Project config — `segan.toml`

```toml
mode = "strict"               # strict | open
default_kit = "nes"
output_dir = "../game/assets/generated/audio"   # NOT the same dir as PAGAN's (both write manifest.json)
preview_dir = "previews"
export = ["wav", "godot"]     # + "stems"
style_version = 1

[mix]                         # ≈ [camera]/[light]: applies to everything, so it all matches
sample_rate = 44100           # Godot's default mix rate
oversample = 2                # 1 | 2 | 4 (synthesis rate multiplier; anti-aliasing)
music_channels = "stereo"
sfx_channels = "mono"
tuning = 440.0
room = 0.15                   # shared small reverb (0 = dry); same space for every asset
crush = { bits = 0, rate = 0 }   # 0 = off; e.g. bits = 8 for a lo-fi era look
declick = true                # ≈ outline: auto
limiter = -1.0                # true-peak ceiling, dBFS

[loudness]                    # integrated LUFS targets per category; build normalises to them
music = -16.0
sfx = -14.0
ui = -20.0
# any SFX `category` not listed uses `sfx`

[lint]
disable = []
max_seam_click = 0.02         # W007 threshold
max_leading_silence_ms = 5    # W005

[godot]
compress = "qoa"              # none | ima | qoa
```

Every setting goes in the `settings.py` registry with a default, a meaning and what it refreshes:
`config set mix.room 0.3` → "every song and SFX re-renders".

---

## 6. Previews: how the agent "looks" at sound

`segan preview <asset>` writes `<asset>.wav` (for the human) and **`<asset>.listen.png`**, and prints the paths.
The skill makes the agent open the PNG every iteration. The listen sheet has, top to bottom, all on one time axis:

1. **Header**: name, duration, tempo/key, peak dBFS, integrated LUFS vs. target, true-peak, seam score.
2. **Arrangement strip** (songs): section/pattern blocks with bar numbers and loop/marker flags.
3. **Piano roll per track** (songs, drawn from the *source*, so exact): notes as bars in the instrument's
   colour, beat/bar grid, key-of-C lines labelled.
4. **Waveform** (min/max per column; clipped samples in red).
5. **Log-frequency spectrogram** with octave lines labelled (C2…C8) and the beat grid. Detected pitch
   track overlaid for SFX.
6. **Loudness curve** (short-term LUFS) for songs.

The spike confirmed you can read these from the image: rhythm, accents, pitch steps, envelope shape, noise
vs. tone, and **aliasing** (mirrored partials from a naive square wave, which is why band-limited oscillators
and `oversample` are mandatory, §8).

Also:
- `--json` analysis: onsets (s), per-note detected pitch vs. intended (cents), spectral centroid, peak, LUFS,
  seam metric, clipping count, leading silence. The agent compares numbers, not just pictures.
- **Seam view** (looping assets): the last 1 s + the first 1 s spliced together, with the splice marked. ≈ tiling check.
- **Gallery** (`segan gallery`): every SFX's mini sheet in a grid plus a bar chart of LUFS by category. Shows
  "one of these is not like the others" across the whole set.
- Scope limits: `--from/--to` (bars or seconds), so long songs are previewed one section at a time at readable resolution.

**What the agent can't judge:** whether a melody is good or a sound is pleasant. The skill says so plainly.
Every asset stays `status: draft` until a human listens and approves. The MCP `preview` tool returns the image
(Claude can see it) plus the WAV as an MCP audio resource (for clients/humans).

---

## 7. Lint rules

Errors (build fails):
- `E000` command/usage error
- `E001` YAML error / missing field / unknown field
- `E002` unknown char in a lane (not a kit key, `.`, `-`, `|`; drum lanes: not `x X o .`)
- `E003` lane row width ≠ pattern `length`, or row count ≠ the track's range/drum list
- `E004` section/arrangement/loop/marker refers to a missing pattern or section
- `E005` kit problem (bad key, duplicate, reserved char, unknown field, group refers to a missing key)
- `E006` variant swap refers to an unknown key/group, or a group swap with different lengths
- `E007` note outside the instrument's `range`
- `E008` bad loop/phase definition (zero length, loop outside the arrangement)
- `E009` inline instruments in a strict-mode project
- `E010` derived pattern problem (unknown `from`, cycle, shift off the grid, transpose out of range)
- `E011` row label doesn't match the expected note/drum (row shift)
- `E012` duplicate asset names
- `E013` SFX problem (unknown preset/shape, bad keyframes, empty)
- `E014` polyphony on a track exceeds the instrument's `voices`
- `E015` hold `-` with no note to hold (start of a lane after a rest)

Warnings:
- `W001` clipping before the limiter / true-peak over the ceiling (the limiter hides it; the source is too hot)
- `W002` unused pattern
- `W003` too many instruments in one song for the project (style drift; configurable)
- `W004` silent pattern/SFX/variation
- `W005` leading silence in an SFX > N ms (adds input latency in games: a real, common bug)
- `W006` asset made under an older `style_version`
- `W007` loop seam discontinuity (click/pop at the loop point) (≈ PAGAN W007, frame churn)
- `W008` DC offset
- `W009` clash: simultaneous minor-2nd/tritone between tracks on a strong beat (heuristic; often intended, so a warning)
- `W010` aliasing energy above threshold (raise `oversample`)
- `W011` SFX envelope still sounding at `duration` (truncated tail → click)
- `W012` note held past the end of its pattern
- `W013` loudness off its category target by > 1 LU when normalisation is off for that asset

Per-asset `lint: { disable: [...] }` as in PAGAN.

---

## 8. Determinism and audio quality (decide these up front)

- **PRNG:** never `numpy.random` distribution methods (NEP 19: streams may change between numpy versions). Use a
  small integer xorshift/PCG written with numpy `uint64` ops, seeded from `(asset name, layer, seed)`.
- **Transcendentals:** numpy `sin/exp` can differ by an ulp across CPUs (SIMD paths). Use phase accumulators +
  wavetables built once and rounded to 12 decimals (PAGAN's trig trick). Envelopes are piecewise linear/exponential
  from rounded tables. Dither is deterministic TPDF from the PRNG (or none; decide in M1).
- **Band-limited oscillators** (PolyBLEP for saw/pulse; triangle by integrating BLEP-square) + `oversample` with a
  fixed polyphase decimator. Non-negotiable: the spike showed naive oscillators alias audibly.
- **Golden tests:** compare decoded samples with a ±1 LSB tolerance across machines, plus a same-machine
  byte-identical-rebuild test. This mirrors PAGAN's "pixels exact, bytes same-machine" decision. Document it in the decisions log.
- **WAV writer:** fixed header, `smpl` chunk with loop points (many engines read it; Godot's "detect from WAV"
  does), `cue `/`LIST adtl` chunk for markers. No timestamps, no `LIST INFO` software tag.
- **Render cache** in `.segan-cache/`, keyed by source text + kit + `[mix]` + `RENDERER_VERSION` (as for PAGAN models).
- **Performance target:** a 2-minute stereo song at 2× oversample renders in < 5 s cold. Vectorise per note
  (render each note's buffer in numpy, then sum); block-process only the time-varying filters.

---

## 9. Build and export

`segan build` (always the whole project, like PAGAN):
- `music/<song>.wav` (+ `<song>.<variant>.wav`), `sfx/<sfx>.wav`, `sfx/<sfx>.<n>.wav` (variations; variant names
  must start with a letter, so there's no clash), `sfx/<sfx>.<phase>.wav`.
- `stems/<song>/<track>.wav` when `export` has "stems" (sample-aligned, same length, same loop points).
- Loudness normalisation to the category target, then a true-peak limiter at `[mix] limiter`.
- **`manifest.json`** (the contract): per asset: kind, files, duration (s + samples), sample_rate, channels,
  `loop: {start, end}` in samples, `bpm`, `meter`, `beat_count`, `sections: {name: {start, end}}` (samples, seconds
  and bars), `markers`, `category`, LUFS, peak, variations/phases/variants, description, tags, status, style_version, generator.
- Write only changed files; delete outputs (and their `.import` sidecars) that the previous manifest listed but
  this build no longer produces.

**Godot exporter** (verify every format against what Godot 4.7.2 itself writes, as PAGAN did, never from memory):
- WAV `.import`: edit only the loop (`edit/loop_mode`, `edit/loop_begin`, `edit/loop_end`) and `compress/mode`
  lines. Write a minimal file if none exists and let Godot fill in the rest (same approach as PAGAN's `mipmaps`).
- `AudioStreamRandomizer` `.tres` per SFX with variations (`random_pitch`/`random_volume_offset_db` from the source).
- `AudioStreamPlaylist` or `AudioStreamInteractive` `.tres` for songs with sections (clips = sections,
  transitions on bar boundaries). If the 4.7 format is awkward, ship the section offsets in the manifest first and add the `.tres` in a later step.
- `AudioStreamSynchronized` `.tres` for stems (adaptive layering).
- `--verify-godot`: headless Godot loads every resource and plays each stream for one frame without errors.
- Example Godot project `examples/godot/` with a scene listing every asset (buttons to play, a loop toggle,
  a layer slider for stems). CI job like PAGAN's: rebuild the demo, fail on diff, verify the load.

---

## 10. Commands

Same shape and flags as PAGAN (`--json`, non-zero exit on error, project discovery from the target path, open mode without `segan.toml`):

`init [--open] [--style chiptune|synth] [--godot DIR]` · `new kit|song|sfx <name> [--preset P]` · `lint` ·
`render` · `preview [--from --to] [--seam]` · `gallery` · `kit show` · `build [--verify-godot]` · `bake sfx` ·
`import midi <file> [--kit K] [--quantize 16]` · `status` · `mark` · `style bump` · `config show|get|set|unset` ·
`mix adjust [--brightness --warmth --room --crush --loudness]` · `mcp` · `skill install`.

MCP tools mirror PAGAN's 1:1 (`status`, `read_docs`, `write_doc`, `log_feedback`, `config_*`, `kit_list/show/write`,
`mix_adjust`, `scaffold`, `read_asset`, `write_asset` (lints + previews), `lint`, `preview`, `gallery`, `mark`,
`style_bump`, `import_midi`, `build`, `manifest`) plus the same resources/prompts (`segan://workflow`, `segan://reference`, …).

`segan.api` for generator scripts: `scale(key)`, `note("A4")`, `chord(degree, key)`, `progression("i VI III VII")`,
`euclid(hits, steps)`, `arpeggiate`, `humanize(seed)` (deterministic), `Pattern` builder → lane text, `song_yaml`/`sfx_yaml` writers. Versioned (`API_VERSION`).

---

## 11. Milestones

Each one ends like PAGAN's: tests + mypy green, CLAUDE.md updated, a summary to the owner listing **which WAVs
and listen sheets to check**, and a commit (plain git under the owner's identity, never AI attribution, never push unasked).

### ☑ Milestone 0 — Scaffolding
Repo exists (`/home/lgolino/repos/SEGAN`, GitHub `lukasgolino/segan`, this file is its `PLAN.md`). Copy and adapt PAGAN's infrastructure (§3). CLI skeleton,
`segan --version`, CI (3.11–3.13), CLAUDE.md with a decisions log, MIT licence. Check the PyPI name. **Done when:**
install + mypy + pytest pass and CI is in place.

### ☑ Milestone 1 — Synth core + kits
`synth.py` (band-limited oscillators, noise PRNG, ADSR, pitch env, vibrato, FM, SVF/biquad filters in blocks,
drum macros), `oversample` + decimator, `wavio.py` (`smpl`/`cue` chunks), `analysis.py` (peak, LUFS BS.1770,
onsets, YIN pitch, aliasing metric), `listen.py` (waveform + spectrogram + header), kit parsing/validation,
`kit show`, `init`, `new kit`. Ship 3 demo kits (e.g. `nes`, `fm_soft`, `arcade_synth`). Golden tests (±1 LSB)
+ determinism test. **Done when:** the owner listens to the kit-show WAVs and picks/tweaks; aliasing metric < threshold on the pulse/saw tests.

### ☑ Milestone 2 — SFX
SFX format (layers, keyframes, presets, variations, phases, extends), lint E013/W004/W005/W008/W010/W011,
`render`, `preview` (pitch overlay), `gallery`, `bake sfx`. **Done when:** a fresh agent with only the reference
makes the 11 preset SFX in `examples/demo/`, they're lint-clean, and the owner approves at least 8 by ear.

### ☑ Milestone 3 — Songs
Tracks, roll/drum lanes, labels, patterns, derived patterns, sections/arrangement/loop/markers, swing, variants
+ axes, sequencer → events → mix; piano roll + arrangement strip + seam view in the listen sheet; E002–E015,
W002/W003/W007/W009/W012. **Done when:** two demo loops (exploration + combat), each with a variant, loop without
a click (W007 clean) and the owner judges them listenable.

### ☑ Milestone 4 — Build + manifest + Godot
Loudness normalisation + limiter, stems, manifest, stale cleanup, the Godot exporter (§9), example Godot project,
headless verify, CI godot job. **Done when:** the Godot demo scene plays everything, loops are seamless in-engine,
and the randomizer cycles variations.

### Milestone 5 — Long-term management
`status`, `mark`, `style bump`, `config` registry, `mix adjust`, BRIEF.md/SOUND.md templates, render cache.
**Done when:** `config set mix.room 0.3` + build re-renders everything, and `style bump` flags all assets.

### Milestone 6 — Skill + MCP + API
The `segan` skill (workflow + `reference.md`) built from what actually happened in M1–M5, including the honest
"you can't hear: here's what to check in the image and numbers, and humans approve" section; `segan mcp`;
`segan.api`. **Done when:** a fresh agent given "make a door-creak SFX and a short shop-music loop" in the demo
project produces lint-clean assets on its own.

### Milestone 7 — Import
`import midi` (hand-written SMF parser): quantize to the grid, snap pitches to the key (≈ snap to palette) and
instruments to the kit (GM program → nearest kit instrument), with a change report (notes moved, dropped, merged).

### Later (don't start unless asked)
Sampled instruments (`sample:` + SoundFont `.sf2` via a pure reader; licensing!), OGG/Opus export, MIDI export,
`segan play` (local playback), audio-to-SFX parameter fitting, tracker (`.xm`) export, other engines, and a
**PAGAN ↔ SEGAN link**: PAGAN animation frame events (`footstep` on `walk_2`) referencing SEGAN SFX, merged
by the orchestrator via both manifests.

---

## 12. Questions for the owner (defaults used until answered)

1. ~~Name~~: decided, SEGAN (*Sound Effect Grammar And Notation*). PyPI availability still to be checked (don't publish).
2. ~~Repo~~: decided, public GitHub repo `lukasgolino/segan` (like `lukasgolino/pagan`); pushing is allowed.
3. **scipy** as a core dependency for filters/LUFS/resampling (default: yes; the alternative is a slower
   pure-numpy block filter and more code).
4. **Aesthetic scope v1**: synth/chiptune only, samples later (default). Say if the first game needs realistic instruments.
5. **Sample rate**: 44.1 kHz (default; Godot's mix rate) vs. 48 kHz.
6. **Golden tolerance**: ±1 LSB across machines, byte-exact on the same machine (default, mirrors PAGAN).

---

## 13. Risks

- **Musical quality** is the real unknown. Mitigation: kits and presets carry most of the quality; songs stay
  short, loop-based and grid-constrained; humans approve. Get the owner to judge M3 output before investing further in music.
- **Agent blind spot**: spectrograms show correctness, not taste. Don't overclaim in the skill.
- **Copied infrastructure drifts** from PAGAN. Note in each copied module where it came from; port fixes on purpose.
- **Godot audio resource formats** (`AudioStreamInteractive` especially) are newer and less stable than
  SpriteFrames. Verify against 4.7.2 and keep the manifest as the fallback contract.
- **Output-dir clash** with PAGAN: both write `manifest.json`. Default `output_dir` uses an `audio/` subdirectory; `init` warns if it finds a `pagan.toml` pointing at the same dir.
- **Token cost of long rolls**: 64 steps × 15 rows × 4 tracks ≈ 4k chars per pattern. Keep patterns to 1–2 bars
  and use derived patterns and sections; the skill should push agents towards reuse.

---

## 14. Owner directives (2026-10-19): autonomous build

The owner is away and won't review as you go. Build SEGAN **to completion (Milestones 0–7)** without waiting:
- **Don't block on questions.** Use the defaults in §12 and log every question that's open or decided
  by default in `QUESTIONS.md` (repo root), each with your recommendation, so the owner can answer in the morning.
  Treat scipy as approved-by-default (log it).
- **Commit and push** to `origin main` at every milestone (and more often if useful). You may tag releases
  (`v0.1.0`, ...) and push tags, following PAGAN's versioning/CHANGELOG conventions. **Never publish to PyPI.**
- Commits are plain `git commit` under the owner's configured identity. **Never any AI attribution**: no
  `Co-Authored-By`, no "Generated with ...". A local commit-msg hook rejects these.
- Keep CI green on GitHub (`gh run list` / `gh run view --log-failed` to check after pushing).
- Follow PAGAN's principles and conventions (its `CLAUDE.md`), and read `/home/lgolino/repos/PAGAN` whenever
  you need a reference implementation. **Never modify the PAGAN repo.**
- "Done" means: every milestone's done-criteria met, by your own judgement where the plan says "the owner
  approves by ear" (you can't hear: use the listen sheets + analysis, and record which assets need the owner's ear in QUESTIONS.md).
