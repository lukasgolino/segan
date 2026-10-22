# SEGAN — Sound Effect Grammar And Notation

SEGAN translates between AI and game audio. It defines a small text notation for sound effects and music —
instrument kits, step-grid songs and layered synth SFX, all YAML — that an AI agent can write fluently, and a
Python tool that lints it, renders **listen sheets** (pictures of the sound an agent can look at), and builds
engine-ready WAVs, `manifest.json` and Godot resources. It is the sister library of
[PAGAN](https://github.com/lukasgolino/pagan) (Pixel Art Grammar And Notation): same design, sound instead of pixels.

```yaml
patterns:
  a:
    length: 16
    lead: |
      ....|....|..p-|....  F5
      ....|..p-|....|p---  E5
      p-..|....|....|....  A4
    drums: |
      x...|....|x.x.|....  k
      ....|X...|....|X..o  s
```

- **Kits are the palette**: songs write one-character instrument keys; roll rows are the notes of the song's
  key, so an off-key note can't be written. Row labels are checked, so a missing row can't shift the grid.
- **SFX are synth layers** with pitch/gain/filter keyframes, 11 presets (coin, jump, laser, explosion, hit, hurt,
  powerup, blip, select, door, step), variations, phases and seamless loops.
- **Recorded SFX** for real-world sounds: `segan sounds search` finds recordings on Freesound (CC0 and CC BY
  only), `segan sounds add` records them in `sounds.lock` (fetched into a user cache, checked by sha256, nothing
  copied into the repo), and an SFX layer plays them (`sample: freesound:<id>` or a file) trimmed, reversed,
  faded, pitch-shifted and time-stretched independently, layered with synth sounds. `segan sounds credits`
  writes the attribution CC BY requires. See [examples/demo/sfx/boss_gong.sfx.yaml](examples/demo/sfx/boss_gong.sfx.yaml).
- **Sampled instruments**: `sample:` plays WAVs, SFZ maps and SoundFonts (`.sf2`), and the `vsco2` library
  (VSCO 2 Community Edition, CC0: string sections, brass, woodwinds, harp, timpani, percussion, piano) downloads
  on demand with `segan samples fetch`. See [examples/orchestra](examples/orchestra).
- **One shared mix** (`[mix]`: room, tone, crush, oversampling, loudness targets, true-peak limiter) for every
  asset, so a game's sounds belong together; change it once and everything re-renders.
- **Deterministic**: same sources, byte-identical WAVs (band-limited oscillators, table-based maths, no RNG
  drift). Every command takes `--json` and exits non-zero on errors; lint findings carry rule id, file, line
  and a fix hint.

> **Status:** v0.2: the full pipeline works (kits, SFX, songs, lint, listen sheets, build, Godot 4, MIDI
> import, MCP server, Claude skill), with synth and sampled instruments. See [PLAN.md](PLAN.md) and
> [CHANGELOG.md](CHANGELOG.md).

## Install

Requires Python 3.11+. SEGAN isn't on PyPI yet; install a tagged release from GitHub:

```sh
pip install "git+https://github.com/lukasgolino/segan.git@v0.10.0"                 # the CLI + library
pip install "segan[mcp] @ git+https://github.com/lukasgolino/segan.git@v0.10.0"    # + the MCP server
pip install "segan[ogg] @ git+https://github.com/lukasgolino/segan.git@v0.10.0"    # + Ogg Vorbis music export, .ogg/.flac/.mp3 recordings
segan --version
```

Development:

```sh
git clone https://github.com/lukasgolino/segan.git && cd segan
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
mypy && pytest
```

## Quick start

```sh
segan init audio --style chiptune   # segan.toml, BRIEF.md, SOUND.md, kits/chip.kit.yaml
cd audio
segan kit show                      # every instrument playing a test phrase: previews/kits/chip.listen.png + WAVs
segan new sfx coin --preset coin --description "bright two-note pickup"
segan new song theme --key "A minor" --tempo 120 --description "exploration loop"
segan lint                          # format errors + warnings from the source and the rendered audio
segan preview coin theme            # WAV + listen sheet (+ loop seam view) per output; numbers with --json
segan gallery                       # every asset side by side + loudness by category
segan build                         # WAVs + manifest.json (+ Godot resources) into output_dir
```

The demo project in [`examples/demo/`](examples/demo) has three kits (`nes`, `fm_soft`, `arcade_synth`), the
preset SFX and looping songs with variants; [`examples/godot/`](examples/godot) is the Godot 4.7 project it
builds into (run `segan build` in `examples/demo` first, then open it in Godot and press Play).

## Listen sheets: how an agent "hears"

An agent can't hear, so `segan preview` draws the sound: a header with the numbers (length, peak, true peak,
LUFS vs. target, limiter, lead-in, loop seam click), the arrangement and a piano roll per track (from the
source), the waveform (clipping in red), a log-frequency spectrogram with octave lines, the intended pitch
(white) and the detected pitch (cyan), and the loudness over time. `--json` adds onsets, per-note pitch checks
in cents, spectral centroid and more. What it can't judge is taste: every asset stays `status: draft` until a
human listens and runs `segan mark <asset> --status approved`.

## Using the output in a game

`segan build` writes WAVs (16-bit, loop points in a `smpl` chunk, markers as cues) and `manifest.json`: per
asset its files, lengths and loop points in samples; songs also their tempo, sections, arrangement and markers
in samples, seconds and bars, variants and stems; SFX their variations and phases. With `export = ["wav",
"godot"]` and an `output_dir` inside a Godot 4 project, SEGAN also writes each WAV's loop points and compression
into its `.import`, an `AudioStreamRandomizer` per SFX with variations and an `AudioStreamSynchronized` per song
with stems (`export` + `"stems"`):

```gdscript
$Music.stream = load("res://assets/generated/audio/music/overworld.wav")   # loops seamlessly by itself
$Music.play()
$Coin.stream = load("res://assets/generated/audio/sfx/coin.tres")          # a different variation each time
$Coin.play()
```

## Using SEGAN with Claude

SEGAN ships a Claude skill that teaches an agent the whole workflow (setting up a game's audio, writing kits,
SFX and songs, reading listen sheets honestly, changing the sound over time):

```sh
segan skill install          # copies it to <repo>/.claude/skills/segan/
```

## Using SEGAN from any agent (MCP)

```sh
pip install "segan[mcp] @ git+https://github.com/lukasgolino/segan.git@v0.10.0"
segan mcp --project path/to/audio      # stdio MCP server: 22 tools, listen sheets as images, WAVs as audio
```

## Generator scripts and MIDI

`segan.api` (keys, chords, progressions, Euclidean rhythms, arpeggios, a pattern builder and YAML writers) is a
stable API for scripts that generate many sounds or procedural music. `segan import midi song.mid --kit nes`
converts a MIDI file into a song: quantized to the grid, snapped to the key, parts mapped to kit instruments,
with a report of every change.

## License

MIT. See [LICENSE](LICENSE).
