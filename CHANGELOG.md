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

### Added

- Project scaffolding: package, `segan --version`, CI on Python 3.11-3.13.
