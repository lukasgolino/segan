# Changelog

All notable changes to SEGAN are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Game projects should pin a release tag
(e.g. `pip install "git+https://github.com/lukasgolino/segan.git@v0.1.0"`).

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
