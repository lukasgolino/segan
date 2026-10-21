# Changelog

All notable changes to SEGAN are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Game projects should pin a release tag
(e.g. `pip install "git+https://github.com/lukasgolino/segan.git@v0.4.1"`).

A new version (and tag) is cut for **any** change to:
- the notation (kit, song or SFX files),
- `segan.toml` settings,
- `manifest.json` or exporter output (WAV layout, Godot resources),
- rendering results (the samples a given source produces),
- the CLI's `--json` output and the MCP tools (names, arguments, result keys).

While on 0.x, a minor bump (0.1 -> 0.2) may change any of these; entries marked **Breaking** say what to
check before upgrading. Patch bumps never change existing behaviour. Every release changes the manifest's
`generator` (`"segan X.Y.Z"`), so expect every manifest to change once per upgrade.

## [Unreleased]

### Added

- W018: an SFX noise layer whose filter removes more than 12 dB of its level (a narrow band-pass), so it plays far
  quieter than its gain says (#7).
- `segan.api`: `dedupe(patterns, sections)` merges identical patterns, `derive("a", a, b, tracks)` writes a
  pattern as a derived one (`from` + `transpose`/`mute`/`shift`) when it is, and `song_yaml`/`sfx_yaml` take
  `comments={"patterns.chorus": "..."}` for `#` lines in generated files (#11).
- Manifest `dry_seconds` on SFX one-shot file entries (main, variations, phases): the sound without its room tail,
  so a voice pool doesn't hold a voice through an inaudible tail (#13).
- `variations.envelope` (0-1: envelope times per layer up to 2x either way) and `variations.length` (0-0.5: the
  whole sound stretched or shortened), and each variation's `lufs`/`target_lufs`/`limiting_db` in the manifest (#16).
- `[lint.<category>] disable = ["W017"]` in segan.toml: warnings off for every song or SFX of that category (#19).
- `segan preview <sfx> --output reel`: the main sound and every variation back to back in one WAV and listen sheet
  (`takes` in `--json` gives each start), to judge the variety in one listen (#20).

### Changed

- **Rendering:** a distorted SFX layer's `gain` (fixed or keyframes) now applies after `distort`, so changing the
  gain only changes its level, not its timbre. SFX layers with `distort` sound different; set their gain by ear
  again (#7).
- Docs: seamless SFX loops: hold layers past the loop end and end keyframe curves where they start; `segan lint`'s exit
  codes (1 on errors; warnings only fail with `--warnings-as-errors`) (#8).
- `[loudness]` targets can go down to -60 LUFS (was -40), for very quiet categories such as a hover tick; `segan mix
  adjust` clamps to the same range (#9).
- Docs: why a new `.import` sidecar changes once more after Godot's first import (Godot adds `uid`/`dest_files`) (#14).

### Fixed

- `segan init` catches a PAGAN output folder that contains (or sits inside) SEGAN's, including a PAGAN project elsewhere
  in the Godot project (e.g. `game/art/pagan.toml`); with `--godot` the audio then goes to `assets/audio` instead of
  inside PAGAN's `assets/generated` (#12).

## [0.9.0] - 2026-10-21

### Added

- SFX `pitch:` notes (single or keyframes) take a cents offset: `A4+15c`, `C6-30c` (up to an octave), so detuned
  copies of a layer don't need hand-computed Hz (#6).

## [0.8.0] - 2026-10-21

### Added

- Exponential envelopes: `env: [a, d, s, r, exp]` or `{ ..., curve: exp }`. Decay falls 60 dB (towards the
  sustain) per `decay` seconds and keeps going, so a bell rings out instead of stopping dead; release takes
  `release` seconds to -60 dB, then reaches zero. The default (1 - x)^3 curve is unchanged (#5).

### Changed

- W009 knows how long an `exp` note stays above -30 dB (#5).

## [0.7.0] - 2026-10-21

### Added

- `variations.timing` (0-0.5 s): each variation moves every layer's start by up to that much, earlier or later
  (seeded per layer, never before 0), so bursts and bubbles don't land at the same moments every time (#3).

## [0.6.0] - 2026-10-21

### Changed

- W009 (clash on a beat) checks the felt beat: the dotted quarter in compound meters (6/8, 9/8, 12/8, every 3 beat
  units), not every eighth; and a held note counts only while its envelope is above -30 dB, so a decayed sustain-0
  bell no longer clashes for the rest of its gate (#2).

## [0.5.0] - 2026-10-21

### Added

- `segan preview --json` gives SFX outputs a `layers` readout: each layer rendered dry on its own at its place in
  the sound (`peak_db`, `lufs` = loudest 400 ms, `crest_db`), plus the dry mix, so the layer that makes a sound
  peaky is easy to find (#1).

### Changed

- W001's hint for SFX says what works: stagger layer starts by 3-9 ms, saturate or lower the peakiest layer, then
  body or a quieter category (#1).

## [0.4.1] - 2026-10-21

### Added

- The skill asks agents to report what got in their way (crashes, misleading messages, workarounds, missing
  features) as GitHub issues: a minimal-repro draft, a duplicate check, and filing only with the user's OK.
  `.github/ISSUE_TEMPLATE/agent-report.md` and the `agent-report` label. Run `segan skill install` to update a
  project's copy of the skill.

### Fixed

- `--verify-godot` runs Godot's import again when it crashes (Godot 4.7.2 sometimes segfaults at the end of a
  large threaded import, seen once in CI).

## [0.4.0] - 2026-10-20

The LOOSE! report (ORCHESTRATOR_PLAN.md): shuffled pools of loops, stem mix levels, file size.

### Added

- Soundtrack `families` (family -> songs) and state `crossfade` (seconds): when the next song in a state is in
  the same family it comes in on the bar and overlaps the last one, no gap; other songs still fade out, wait the
  gap and start. Manifest: `families`, each state song's `family`, the state's `crossfade`. E018 for unknown or
  repeated family members; W016 also for cross-fades within a family in clashing keys.
- Stem mixes get a `trim_db` (manifest `stem_mixes.<mix>.trim_db`, preview `stem_mixes_trim_db`): what the game
  adds to the stem volumes while it plays that mix to bring it to the target, capped by the limiter ceiling.
  W017: a mix that can't reach its target even with its trim.
- Song `sample_rate` and `channels`: a song's own output format over `[mix]`'s (lint checks aliasing at that rate).
- `export` value `"ogg"`: music (songs, variants, stems, flow clips) as Ogg Vorbis, SFX stay WAV; `[ogg] quality`
  (default 0.4); optional extra `segan[ogg]` (soundfile). Byte-identical rebuilds on one machine; Godot `.import`
  gets `loop`/`loop_offset`; `--verify-godot` checks OGG loops; the director chains OGG flow clips sample-exactly.

### Changed

- W001 on a song suggests a quieter category of its own (percussive songs).

## [0.3.0] - 2026-10-20

Long-form music: songs the game walks section by section, and soundtracks of game states.

### Added

- Section changes: a section can be `{ patterns | from, transpose, semitones, key, instrument_swap, group_swap,
  mute, velocity }`, applied at play time (key changes without new rows), on top of a variant. E004/E007/E014
  checked per section.
- Song `flow: { start, next, end, no_repeat, variants }`: a weighted section graph the game walks at run time.
  Each flow section builds as clips (`flow/<song>/<section>.head.wav`, `.from.<prev>.wav` with the previous
  section's ring-out baked in, the rest, `.tail.wav`); chained, they equal a linear render of the path. Manifest
  `flow`. E017 (graph problems, sections not whole bars), W015 (a section shorter than the ring-out before it).
- `segan preview <song> --output walk[:seed]`: a 3-minute seeded walk through the flow from its clips, with the
  sections on the sheet and `join_error` (max difference from a straight render of the path).
- Soundtracks (`music/<name>.soundtrack.yaml`): game states with weighted song pools, play times and silence gaps,
  and transitions (`at` now/beat/bar/section/end, `fade`, `fade_in`, `stinger`, `start`). Manifest
  `soundtracks`. E018, W016 (a cross-fade between clashing keys).
- Godot music director `segan_music.gd`, written next to the manifest when the project has a flow song or a
  soundtrack: `play_soundtrack`, `set_state`, `play_song`, `queue_section`, `stop`, signals. Chains clips
  sample-exactly through an AudioStreamGenerator (checked against the clip files in headless Godot).
  `--verify-godot` also loads every flow clip and runs the director.
- Demo: `dungeon` (a seven-section flow song) and the `main` soundtrack; the example Godot project autoloads the
  director (`SeganMusic`) and has a "walk sections" button per flow song and a button per soundtrack state.

### Changed

- `manifest.json` always has a top-level `soundtracks` object (empty without soundtracks).
- W002 no longer flags sections that only the flow plays or that other sections derive `from`.

## [0.2.0] - 2026-10-19

Sampled instruments, and the fixes and features from the first game's reports (ORCHESTRATOR_PLAN.md S1-S12).

### Added

- Sampled instruments: `sample:` on kit instruments and SFX layers plays a WAV (`root`, `loop`, any PCM/float
  format), an SFZ map (subset) or a SoundFont 2 preset (hand-written readers); round robins, velocity layers,
  loops, the file's envelope, pitch curves and vibrato. W014: a note held longer than its sample.
- Sample library `vsco2` (VSCO 2 Community Edition, CC0): 45 instruments mapped by SEGAN (octave labels and
  lead-in silence measured, levels matched); `segan samples list`, `segan samples fetch` (pinned commit, checked
  by git blob id, user cache `SEGAN_SAMPLES`). `segan init --style orchestral`; `examples/orchestra`.
- Song `stems: { groups, mixes, main_mix }`: one WAV per group of tracks, normalised over the loudest listed mix;
  `preview --output mix:<name>`, `stem_mixes_lufs`; manifest `stems.<group>.tracks`, `stem_mixes`,
  `stems_normalised_over`. E016.
- SFX `variations.include_main: false` and song `stems.main_mix: false`: build only what the game plays.
- `[room]` per-category room send, SFX `room:`, `[mix] tail_trim_db`.
- `preview --output` repeats (one render for all outputs).

### Changed

- **Breaking (sound):** unison voices start within a quarter turn of each other (was evenly spread: two voices
  started in antiphase and swelled in). Every `unison > 1` instrument sounds different.
- **Breaking (files):** a looping song's loop offset now covers how long its last notes really ring (voice cuts
  included), not the kit's longest release: many songs get a shorter file and new loop points.
- `centroid_hz` is a power-weighted log-frequency centroid; SFX `pitch_hz` ignores periods with no energy of their
  own; minor-family keys spell flats like their relative major (D harmonic minor: Bb).
- `pitch_check` waits out the previous note's release and skips one-shot samples.

### Fixed

- A sparse looping song (last note ending early) crashed the build (S12).
- `preview --output stem:X`: header said "0 bars later", the roll showed every track, no pitch check (S7).
- Loop header printed bar offsets like 0.999993 (S6).

## [0.1.0] - 2026-10-19

First release: milestones 0-7 of PLAN.md.

### Added

- Project scaffolding: package, `segan --version`, CI on Python 3.11-3.13.
- Synth core: band-limited oscillators (PolyBLEP/BLAMP), FM, noise, envelopes, filters, drum macros, oversampling.
- Kits (`kits/*.kit.yaml`), `segan init`, `segan new kit`, `segan kit show` (listen sheet + WAVs per instrument).
- SFX (`sfx/*.sfx.yaml`): layers with pitch/gain/cutoff keyframes, effects, 11 presets, variations, phases, loops,
  `extends` templates; `segan new sfx`, `segan bake sfx`.
- Songs (`music/*.song.yaml`): roll and drum lanes with checked row labels, derived patterns, sections, arrangement,
  seamless loops, markers, swing, variants and variant axes; `segan new song`.
- `segan render`, `segan preview` (WAV + listen sheet + seam view + analysis JSON), `segan gallery`, `segan lint`
  (E000-E015, W001-W013), render cache.
- `segan build [--verify-godot]`: WAVs (smpl loop points, cue markers), stems, `manifest.json` (loops, sections,
  markers and variants in samples/seconds/bars), stale cleanup; Godot `.import` loop/compression edits,
  AudioStreamRandomizer and AudioStreamSynchronized resources, headless verification.
- Example Godot 4.7 project (`examples/godot`) that lists and plays every demo asset.
- Long-term management: `segan status`, `segan mark`, `segan style bump` (SOUND.md changelog, W006),
  `segan config show|get|set|unset` (every setting in one registry), `segan mix adjust` (brightness, warmth, room,
  crush, loudness for the whole project), BRIEF.md/SOUND.md templates.
- `segan mcp`: SEGAN as an MCP server (optional extra `segan[mcp]`): 22 tools mirroring the CLI, listen sheets
  returned as images and WAVs as audio, resources (workflow, reference, BRIEF/SOUND, manifest, kits, assets) and prompts.
- `segan.api` for generator scripts: `scale`, `chord`, `progression`, `euclid`, `arpeggiate`, `humanize`, `Track`,
  `Pattern`, `song_yaml`, `sfx_yaml` (`API_VERSION = 1`).
- `segan import midi`: standard MIDI files to songs (quantize, snap to the key, GM programs/drums to kit instruments,
  reused patterns, a change report).

[Unreleased]: https://github.com/lukasgolino/segan/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/lukasgolino/segan/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/lukasgolino/segan/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/lukasgolino/segan/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lukasgolino/segan/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/lukasgolino/segan/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/lukasgolino/segan/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/lukasgolino/segan/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lukasgolino/segan/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lukasgolino/segan/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/segan/releases/tag/v0.1.0
