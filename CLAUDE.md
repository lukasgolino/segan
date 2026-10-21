# CLAUDE.md

SEGAN (Sound Effect Grammar And Notation) is PAGAN's sister library: a standalone Python CLI that translates
between AI and game audio. Agents write sound effects and music as palette-keyed YAML (instrument kits,
step grids, parametric SFX); SEGAN lints them, renders previews an agent can look at (listen sheets), and
builds engine assets (WAV, manifest.json, Godot). Read [PLAN.md](PLAN.md) for the brief, milestones and progress.
The reference implementation of every convention is PAGAN at `/home/lgolino/repos/PAGAN` (read-only).

## Setup and commands

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
segan --version          # or: python -m segan --version
mypy                     # strict type check (config in pyproject.toml)
pytest
```

CI (`.github/workflows/ci.yml`) runs install + mypy + pytest + `segan lint --warnings-as-errors` on the demo on
Python 3.11-3.13, and a `godot` job that downloads Godot 4.7.2, rebuilds the demo into `examples/godot/`
(failing if the committed text outputs differ), verifies every stream loads, loops and plays, and runs
`tests/test_godot.py` (skipped locally unless `GODOT=/path/to/godot` or `godot` on PATH).
After changing demo sources or rendering: `cd examples/demo && segan build --verify-godot` and commit the
generated text files.

## Layout

- `src/segan/` — the package:
  - `cli.py` argparse commands; `findings.py` Finding/SeganError (rule ids, file:line output, JSON);
  - `yamlio.py` YAML loader (rejects duplicate keys, tracks line numbers via `LineMap`) — copied from PAGAN;
  - `buildinfo.py`, `progress.py` — copied from PAGAN; `settings.py` registry + TOML text edits — adapted from PAGAN;
  - `dsp.py` deterministic primitives (sin/exp2 tables, splitmix64 noise, PolyBLEP/BLAMP, biquads, decimator);
  - `notes.py` note names, keys, scales; `patch.py` instrument fields (shared by kits, inline instruments, SFX layers);
  - `kit.py` kit files; `synth.py` one note -> samples (oscillators, envelopes, filters, drum macros, oversampling);
  - `voices.py` note events -> track buffers (mono voice cuts, pan, note cache); `mix.py` shared bus (room, tone,
    crush, loudness normalisation, true-peak limiter); `analysis.py` LUFS/peaks/onsets/YIN/seam/aliasing;
  - `wavio.py` deterministic WAV with `smpl`/`cue ` chunks; `oggio.py` Ogg Vorbis via soundfile (export "ogg", fixed serial); `listen.py` listen sheets, seam view, gallery;
  - `kitshow.py` `segan kit show`; `project.py` segan.toml + discovery; `templates/` files `segan init` writes;
  - `asset.py` shared metadata, `extends` templates, asset loading; `sfx.py` SFX parsing (+ `presets/*.yaml`);
    `sfxrender.py` SFX rendering (layers, keyframes, effects, variations, phases, loops);
  - `song.py` song parsing (tracks, lanes, labels, derived patterns, sections + section changes, variants, flow,
    E007/E014 checks); `sequence.py` timeline + note events; `songrender.py` song rendering (loop offset, stems);
    `flowrender.py` flow clips (per-section timelines, head/from/rest/tail, walks); `songlint.py` source warnings;
  - `soundtrack.py` `music/*.soundtrack.yaml` (states, transitions; E018/W016) — not an asset: lint/build only;
  - `render.py` outputs + render cache (`.segan-cache/renders/`); `preview.py` / `songpreview.py` listen sheets + analysis;
  - `lint.py` lint (errors from parsing, warnings from source and rendered audio); `yamlwrite.py` YAML writer;
  - `manage.py` long-term management: catalogue (`segan status`), `mark`, `style bump`, `mix adjust` (text edits keep comments);
  - `samples.py` sampled instruments: WAV/SFZ/SF2 readers, zones, variable-rate Hermite playback;
    `libraries/` sample libraries (`vsco2/`: SEGAN's SFZ maps + library.json; audio fetched on demand into the user cache);
  - `api.py` stable Python API for generator scripts (keys, chords, progressions, euclid, arpeggios, Pattern builder, YAML writers);
  - `midi.py` hand-written SMF reader + `segan import midi` (quantize, snap to key, GM -> kit, change report);
  - `mcp_server.py` `segan mcp`: MCP tools/resources/prompts over the CLI handlers (stdout captured, cwd pinned, one lock);
  - `build.py` `segan build` (WAVs, manifest.json, stale cleanup); `exporters/godot.py` `.import` edits, Randomizer /
    Synchronized `.tres`, headless verify (`templates/godot_verify.gd`); `templates/segan_music.gd` the Godot music
    director (flows + soundtracks), copied next to the manifest.
- `examples/godot/` — Godot 4.7 project receiving the demo's build; `scenes/audio_test.tscn` plays everything
  (flow songs and soundtracks through the `SeganMusic` autoload = the generated `segan_music.gd`).
  Only text outputs (manifest, .tres, .import) are committed; run `segan build` in examples/demo first.
- `scripts/check_committed_build.py` — CI: the rebuilt generated folder must match the commit.
- `tests/fixtures/golden/` — golden project (22.05 kHz mono so files stay small); `expected/*.wav` are checked
  renders. After an intended rendering change, look at the output, then `SEGAN_UPDATE_GOLDEN=1 pytest tests/test_golden.py`.
- `examples/demo/` — the demo project (kits: nes, fm_soft, arcade_synth).
- `examples/orchestra/` — sampled-orchestra example (needs `segan samples fetch`; CI job `orchestra` fetches and builds it).
- `scripts/make_vsco2_library.py` — regenerates `src/segan/libraries/vsco2/` (downloads ~1.3 GB once).

## Conventions

- Same as PAGAN's CLAUDE.md unless noted here: Python 3.11+, typed (mypy strict), small modules, every feature
  with tests, deterministic output, `--json`, all findings collected with rule id/file/line/where/fix hint.
- Modules copied from PAGAN say so in their docstring; port fixes between the two on purpose.
- Commits: plain `git commit` under the owner's identity, imperative subject. NEVER AI attribution (no
  Co-Authored-By trailers, no "Generated with" lines). Push to origin main is allowed (owner, 2026-10-19).
- Versioning as PAGAN: bump `version` in pyproject.toml, CHANGELOG.md entry (Keep a Changelog), tag `vX.Y.Z`
  for any change to the notation, segan.toml settings, manifest/exporter output or rendered samples.
- Questions for the owner: ask as you go (tight questions, each with a recommended default).
- Bugs, feature requests and future work live in GitHub issues (`gh issue list --repo lukasgolino/segan`); games
  report through the `agent-report` template. No plan/report files in the repo.
- Dependencies: numpy, scipy, Pillow, PyYAML; extras `mcp`, `ogg` (soundfile); dev: pytest, mypy, types-PyYAML, mcp, soundfile.

## Decisions log

- 2026-10-19: Name SEGAN, sister library of PAGAN, own repo `lukasgolino/segan` (public, like PAGAN). Covers SFX and music.
- 2026-10-19: scipy is a core dependency (approved by default per PLAN.md §14): IIR filters (`sosfilt`), polyphase
  decimation (`resample_poly`), FFT convolution for the room. PyPI name `segan` is free (checked 2026-10-19; not published).
- 2026-10-19: Determinism (PLAN.md §8): no `numpy.random` (noise = splitmix64 hash of the sample index); per-sample
  sin/exp2 from 4097-entry tables built with `math` and rounded to 12 decimals; envelopes are polynomials
  (attack linear, decay/release (1-x)^3); scalar coefficients rounded to 12 decimals. No dither (plain rounding to int16).
- 2026-10-19: Golden tests compare decoded samples within ±1 LSB (cross-machine ulp drift) plus a same-machine
  byte-identical rerun test, mirroring PAGAN's "pixels exact, bytes same-machine".
- 2026-10-19: Oscillators: PolyBLEP saw/pulse (pulse DC removed), PolyBLAMP triangle, table sine, 2-op FM (phase
  modulation), white noise and `bitnoise` (sample-and-hold at 16x the pitch: the NES/sfxr crunch). Decimation by a
  fixed Kaiser FIR (96 taps per factor, passband 0.9 x Nyquist) via `resample_poly`.
- 2026-10-19: Aliasing metric (W010): a steady tone of the instrument (modulation off) at its top note; energy away
  from the harmonics vs. on them (Blackman-Harris FFT; floor ~-88 dB). Measured at 2x: saw/pulse -50..-67 dB, 4x
  -67..-89. Default `oversample = 2` (plan), threshold `lint.max_aliasing_db = -50`. Noise and inharmonic FM skip it.
- 2026-10-19: Loudness: songs are measured integrated (BS.1770-4, exact K-weighting for any rate); SFX by their
  loudest 400 ms window (max momentary, zero-padded for short sounds), so a long tail doesn't push a one-shot up.
- 2026-10-19: `segan kit show` normalises the whole kit to the music target with ONE gain, so instrument levels
  stay as the kit's `gain` fields set them.
- 2026-10-19: WAV `smpl` loop end is inclusive (RIFF spec); manifest `loop.end` is exclusive (like Godot's loop_end).
- 2026-10-19: `[mix] crush = {bits, rate}` from the plan is flattened to `crush_bits` / `crush_rate` so
  `segan config set` can edit it (inline tables aren't settable values).
- 2026-10-19: SFX `pitch` keyframe values: strings are notes ("B5"), numbers are Hz; keyframe times are relative
  to the layer's start. `duration` is the hard length of the dry sound (layers still sounding there are cut: W011);
  the room tail is added after it and trimmed at -70 dB.
- 2026-10-19: Presets are SFX-format files in `src/segan/presets/` merged under the SFX like a template; layers
  (in presets and `extends` templates) merge by `id`, the child's fields over the template layer's.
- 2026-10-19: Loudness normalisation never asks the limiter for more than `lint.max_limiting_db` (3 dB): a sound too
  peaky to reach its target stays quieter and W001 reports the shortfall. W001 is therefore "target out of reach
  without heavy limiting" (the plan's "source too hot" has no meaning once everything is normalised).
- 2026-10-19: Added a `foley` loudness category (-22 LUFS) for frequent small sounds (the `step` preset uses it);
  short transients can't reach -14 LUFS momentary without crushing them.
- 2026-10-19: Looping songs: the file is the whole song plus N bars of the loop again (N = whole bars covering the
  longest release + room tail); the loop points are shifted by those N bars from the loop section's start. So the
  intro rings naturally into the loop, the loop's own end rings into its start, and the seam is click-free without
  rendering the song twice. Manifest/WAV loop points are the shifted ones; `loop_offset` says by how much.
- 2026-10-19: Looping SFX/phases blend `crossfade` seconds of overrun into their start (equal power) and get the room
  wrapped around (bus run on three copies, middle kept).
- 2026-10-19: Stems are rendered only when `export` includes "stems" (per-track room/tone, mix = sum, same gain
  curve); otherwise the room runs once on the dry mix. The per-note pitch check (preview) runs on dry track renders.
- 2026-10-19: Mono voices (`voices: 1`) are cut by the next note on the same track and instrument with a 3 ms fade
  (declick), like a chip channel; chords need `voices` > 1 (E014 otherwise).
- 2026-10-19: Kit arpeggio offsets are fixed semitones, so a kit arp instrument should be mode-neutral ([0, 7, 12]);
  the demo `arcade_synth` arp was changed from a major triad for that reason.
- 2026-10-19: Godot 4.7.2 loop semantics (measured by mixing a ramp): a forward loop plays the frames after
  `loop_begin` up to and including `loop_end`. So `.import` gets `loop_begin = start - 1`, `loop_end = end - 1` for a
  loop [start, end), and every SEGAN loop starts at frame >= 1 (looping SFX get one lead-in frame, a copy of the loop's
  last frame). "Detect from WAV" (smpl chunk, spec-inclusive end) would drop one frame per pass, so SEGAN always
  writes the loop into `.import`. QOA keeps the points exact; IMA-ADPCM is off by about a frame (Godot's decoder).
- 2026-10-19: Godot export: `.import` [params] edits (loop_mode/begin/end, compress/mode), a minimal sidecar when
  none exists (Godot fills the rest, verified); AudioStreamRandomizer `.tres` per SFX with variations (Godot's
  default random-no-repeats; verified it cycles); AudioStreamSynchronized `.tres` per song with stems.
  AudioStreamInteractive is deferred: it needs one stream per clip, so the manifest's section offsets are the
  contract for now (PLAN.md §9 allows this).
- 2026-10-19: The demo's generated WAVs (~40 MB per rebuild) aren't committed; manifest.json, `.tres` and `.import`
  are, and CI fails if a rebuild changes them. WAV determinism is covered by golden tests and the byte-identical
  rebuild test.
- 2026-10-19: MIDI import: GM programs pick kit instruments by name hints first (a "bass" instrument for GM basses,
  "lead"/"pad"/"piano"... per family), then bass-ness, then range fit; out-of-range notes move by octaves; off-key
  notes snap to the nearest scale note (ties go down); drums map by GM note (kick/snare/clap/tom/hat/open hat/
  cymbal/ride with fallbacks); identical bars become one reused pattern; tempo changes after the first are reported
  and ignored. The key comes from --key, else the key signature, else Krumhansl-Schmuckler on the notes.
- 2026-10-19: `segan.api` is versioned (`API_VERSION = 1`); its writers use `yamlwrite.py`, so generated sources
  look hand-written (block style, flow leaves, `|` lanes).
- 2026-10-19: Release v0.1.0 tagged and pushed (owner directive §14 allows tags; not published to PyPI).
- 2026-10-19: Samples (owner): WAV + SFZ subset + SF2, hand-written readers. Zones are read at a variable rate with
  4-point Hermite at the oversampled rate (high harp notes carry -23 dB above 16 kHz: rendering at the output rate
  would alias when pitched up). Samples are mixed to mono (tracks pan, the room widens). Note velocity 1.0 = MIDI 80.
- 2026-10-19: Orchestral sounds = VSCO 2 Community Edition (CC0), fetched on demand from a pinned commit and checked
  by git blob id into `$SEGAN_SAMPLES` / `~/.cache/segan/samples` (shared by projects); nothing bundled. SEGAN ships
  its own SFZ maps (the repo has none): folder octave labels measured with YIN (most VSCO folders call middle C
  "C3"), timpani tuned from their rolls, lead-in silence skipped, each instrument levelled to -20 LUFS (median
  sample) so kit gains are balance only.
- 2026-10-19: One-shot samples ring to their audible end (-40 dB); an SFX layer's explicit `length` chokes them.
  A looping song's loop offset now comes from how long its last notes actually ring (voice cuts included), not the
  kit's longest tail (a harp or crash in the kit made every loop file twice as long).
- 2026-10-19: ORCHESTRATOR_PLAN S1-S3: song `stems: { groups, mixes, main_mix }` (stems normalised over the loudest
  listed mix; the full mix is normalised on its own), `variations.include_main`, `[room]` sends, `tail_trim_db`.
  S4 unison phases within a quarter turn. Release v0.2.0.
- 2026-10-20: Long-form music (owner): section changes + `flow` (section graph) + soundtracks + a Godot director.
  Measured on Godot 4.7.2: AudioStreamWAV has no bpm (Interactive ignores beat/bar sync on WAV clips);
  Interactive auto-advance switches one mix chunk (~11.6 ms) early per clip, cuts tails and ignores `next_clip`
  changed while a clip plays; Playlist without fade glitches 2 frames per seam. So no native Interactive/Playlist
  `.tres`: the director feeds an AudioStreamGenerator from clip playbacks with `mix_audio`.
- 2026-10-20: Flow clips: every section has its own timeline (no drift when chained); `H` = whole bars covering
  the longest ring-out; per section a cold head, one head per predecessor (its ring-out baked in; deduped when
  identical), the rest and a tail; one static gain (the linear song's) then the limiter. Head/rest clips carry 32
  frames of continuation (`PAD`): Godot stops a WAV playback ~4 frames before its data ends. A new playback is
  late by 2 frames (resampler history): the director measures that once with an impulse and pre-rolls each clip.
  Godot decodes int16 as x/32767. Flow sections must be whole bars (E017). Section pitch changes apply after
  the song variant's.
- 2026-10-20: Soundtracks are their own source type (like kits), not a third asset kind: no render, preview,
  status or MCP surface; lint checks them against the project's songs/SFX; manifest top-level `soundtracks`.
- 2026-10-20: LOOSE! report (v0.4.0, owner said do all of it). Families: explicit soundtrack `families`, exact
  labels (`song` = the main version only; variants listed as `song.variant`); a state's `crossfade` applies only
  song-to-song inside a family (the next song is picked when the current one starts, so a flow song keeps walking
  past its play time until the bar where the next one comes in). Stem mixes: no per-mix render gain (stems are
  shared between mixes); the manifest gives each mix a `trim_db` the game applies, capped by the true-peak ceiling.
- 2026-10-20: Ogg Vorbis (export "ogg", music only; SFX stay WAV) via soundfile/libsndfile, an optional extra.
  libsndfile picks a random Ogg serial: SEGAN rewrites it (sha256 of the file's name) and recomputes page CRCs, so
  rebuilds are byte-identical on one machine (Vorbis float code may differ across machines; the demo stays WAV).
  Measured on Godot 4.7.2: its Vorbis decode = libvorbis's (1.5e-7), same 2-frame playback latency as WAV, and a
  loop restarts at frame floor(loop_offset * rate) after the file's last frame: `loop_offset` = (start + 0.25) / rate.
- 2026-10-21: ORCHESTRATOR_PLAN.md (open items) and PLAN.md's "Later" list became GitHub issues #1-#35; ORCHESTRATOR_PLAN.md
  and QUESTIONS.md deleted (owner). Questions are asked as you go instead of logged.
