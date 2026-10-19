# Changelog

All notable changes to SEGAN are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Game projects should pin a release tag
(e.g. `pip install "git+https://github.com/lukasgolino/segan.git@v0.2.0"`).

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

[Unreleased]: https://github.com/lukasgolino/segan/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lukasgolino/segan/releases/tag/v0.1.0
