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

- A much bigger synth palette (#76). Instrument models, each with a same-named block or a preset name:
  `pluck` (Karplus-Strong plucked string: guitar, nylon, steel, harp, koto, pizz, bass, muted, harpsichord),
  `bowed` (bowed strings: per-player drift and onsets, bow noise, violin/viola/cello/bass body resonances;
  `unison` = a section), `additive` (harmonic or inharmonic partials with decays, Hammond drawbars, presets from
  organ to bell and glass), `wavetable` (eight bundled mip-mapped tables morphed by position, envelope or LFO),
  `formant` (sung vowels for soprano/alto/tenor/bass with vowel keyframes; `unison` = a choir; closes #22),
  `modal` (struck resonators: marimba, vibraphone, xylophone, glass, bell, tubular, kalimba, steel drum, wood,
  metal, membrane) and `supersaw`.
- 3-4 operator FM (`fm: { algorithm, ops: [...] }`), hard `sync` with an envelope sweep (saw, pulse), a `sub`
  oscillator, 24 dB filters, a filter `lfo`, `notch` filters, and brass `mute: straight | cup | harmon` (#23).
- Seven new drum macros: `rim`, `shaker`, `cowbell`, `block`, `conga`, `brush`, `metal`.
- Per-instrument effects, `fx: [...]`, on any kit instrument or SFX layer: chorus, ensemble, flanger, phaser,
  delay (ping-pong, damped repeats), reverb, drive (oversampled), crush, comb, ring, tremolo, autopan and an
  LFO filter. Rates and times can be note values that follow the song's tempo (`"1/8."`, `"1/4t"`). Effects run
  per note, after mono voice cuts, with LFOs starting at the note, so loops, flow clips and the render cache stay
  exact; their tails count towards ring-outs and loop offsets.
- Sameness checks (#76). Songs are fingerprinted from their notes (opening notes, chroma and onsets per bar for the
  first 8 bars, register, instruments, key, tempo) and compared: W021 songs that open on the same notes, W022 most
  songs in one pitch set or tempo band, W023 every song on one kit with the same instruments, W024 two songs whose
  first bars score over `lint.max_similarity` (0.85), W025 a song close to SEGAN's own examples (fingerprints
  shipped in the package; `[similarity] shipped`), W026 a song close to one from another project on this machine
  (`[similarity] local_store = true`: fingerprints kept in `~/.cache/segan/fingerprints` on build).
- `segan similarity [songs] [--shipped] [--machine]` (and an MCP `similarity` tool): pairwise harmony, rhythm,
  timbre, register and tempo scores, the closest song for each. `segan preview` reports a song's `closest_song`.

### Changed

- `segan.api.song_yaml` takes any mapping of patterns (a `dict[str, Pattern]` type-checks).

## [0.11.0] - 2026-10-22

### Added

- Recorded SFX (#58). An SFX layer plays a recording when its `sample:` is a sound file (`.wav`; `.ogg`, `.flac`,
  `.mp3` with `segan[ogg]`), `freesound:<id>`, or a list of them (one picked per variation, seeded). Recorded layers
  get `trim`, `reverse`, `fade`, and **independent** `shift` (semitones) and `stretch` (x length): a phase vocoder
  with identity phase locking plus polyphase resampling, deterministic, numpy/scipy only. Every other layer field
  still works (varispeed `pitch` keyframes, filters, gain/cutoff keyframes, distort, envelope, variations), and
  recorded and synth layers mix freely.
- The licence rule: recorded sounds must be CC0 or CC BY (any version); never non-commercial, share-alike or
  unknown. E020 when a recorded layer has no allowed licence, no source, or is CC BY without an author (from the
  layer's `licence`/`source`/`author` fields or its sounds.lock entry). E019 when a recorded sound can't be used
  (missing, not in sounds.lock, sha256 mismatch, undecodable).
- `segan sounds search "<query>" [--max-seconds N] [--licence cc0|cc-by]`: Freesound API v2 search with
  `FREESOUND_API_KEY` (id, name, author, licence, duration, rating, tags; allowed licences only, filtered on the
  server and again locally). `segan sounds add freesound:<id>` checks the licence, fetches the HQ Ogg preview into
  the user cache (`$SEGAN_SOUNDS`, else `~/.cache/segan/sounds`) and records it in the project's `sounds.lock`
  (name, author, licence, page URL, file kind, download URL, sha256); `segan sounds add <file> --licence --source
  --author` records a local file. Builds fetch missing files into the cache on first use and check the sha256.
- `segan sounds inspect <ref...>` (length, peak, loudness, spectral centroid, pitch, onsets), `segan sounds credits`
  (`SOUND_CREDITS.md`: TASL attribution for every recorded sound), `segan sounds vendor` (copies the Freesound
  sounds in use into `<project>/sounds/`; off by default). MCP tools `sounds_search`, `sounds_add`,
  `sounds_inspect`, `sounds_credits`.
- `[sfx] source = "auto" | "synth" | "recorded"` in segan.toml (default `auto`); W020 on a recorded layer when it's
  `synth`. The skill has the synth-or-record rule (synthesise UI, retro, lasers, magic, sci-fi, stingers; record
  animals, voices, footsteps, impacts, weapons, fire, water, weather, vehicles, ambience; hybrids), the recorded-SFX
  workflow (with and without a key) and what a game agent should put in a sound request.
- Demo: `boss_gong`, a hybrid SFX from a CC0 recording (a VSCO 2 CE gong hit, shifted an octave down and
  stretched) over synth rumble and sub layers.

### Changed

- **Breaking:** in an SFX layer, `sample: <file>.wav` (the plain string form) is now a recorded layer: one-shot, as
  recorded, and it needs a licence (E020). The mapping form `sample: { wav: x.wav, root: A4 }` is still a pitched
  sampled instrument, and kits are unchanged.
- Listen sheets: a one-shot sample layer's bar runs to the sample's end (it showed only the release).

## [0.10.0] - 2026-10-21

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
- `segan samples list` shows each library instrument's key range (`range` in `--json`, read from the bundled map: no
  download needed), and `segan kit show --json` gives every instrument's `range` (#24).
- Instrument `max_ring: <seconds>`: a note rings at most that long after it ends, then fades out in 50 ms, so long
  one-shots and releases (timpani rolls, tam-tam, crash, low harp) don't make loop files bars longer (#25).
- W019: a looping song's file runs more than 2 bars past the song because its last notes ring that long (#25).
- `segan lint` and `segan build` render songs and SFX in parallel processes (`-j N` / `SEGAN_JOBS`; default the CPU
  count up to 8); output is identical to one process (#26).
- `segan preview --format ogg|mp3` also writes every preview compressed (`.ogg` / `.mp3` next to the WAV, in `--json`)
  for sharing auditions; needs `segan[ogg]` (MP3: libsndfile 1.1+) (#28).

### Changed

- **Rendering:** a distorted SFX layer's `gain` (fixed or keyframes) now applies after `distort`, so changing the
  gain only changes its level, not its timbre. SFX layers with `distort` sound different; set their gain by ear
  again (#7).
- Docs: seamless SFX loops: hold layers past the loop end and end keyframe curves where they start; `segan lint`'s exit
  codes (1 on errors; warnings only fail with `--warnings-as-errors`) (#8).
- `[loudness]` targets can go down to -60 LUFS (was -40), for very quiet categories such as a hover tick; `segan mix
  adjust` clamps to the same range (#9).
- Docs: why a new `.import` sidecar changes once more after Godot's first import (Godot adds `uid`/`dest_files`) (#14).
- A song's render cache is keyed on the kit instruments it plays (notes and swaps), not the whole kit: editing an
  instrument re-renders only the songs that use it (#26).

### Fixed

- `segan init` catches a PAGAN output folder that contains (or sits inside) SEGAN's, including a PAGAN project elsewhere
  in the Godot project (e.g. `game/art/pagan.toml`); with `--godot` the audio then goes to `assets/audio` instead of
  inside PAGAN's `assets/generated` (#12).
- The preview pitch check reads low notes (below C3) as their 3rd or 5th harmonic when that fits (low harp notes no
  longer show ~-500 cents), and reports a shared offset of an instrument's notes as `detune_cents` instead of
  flagging every note (a sample recorded a bit flat) (#27).

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
  features) as GitHub issues: a minimal-repro draft, a duplicate check, and filing only once approved.
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

[Unreleased]: https://github.com/lukasgolino/segan/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/lukasgolino/segan/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/lukasgolino/segan/compare/v0.9.0...v0.10.0
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
