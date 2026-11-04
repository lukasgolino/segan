# Setup

Setup check, first-time setup, project layout.

## Setup check

1. `segan --version`. If it's missing, install it the way the project pins it (its requirements file / tag,
   e.g. `pip install "git+https://github.com/lukasgolino/segan.git@v0.4.1"`). Never swap a pinned install for an
   editable checkout unless you are developing SEGAN itself.
2. Find the audio project: `segan status` (it says so if there's no `segan.toml` here or above), or
   `find . -name segan.toml -not -path '*/node_modules/*'`. That folder is the game's **audio home**:
   - `BRIEF.md` - what the game is, its key sounds and music, the wishlist, what awaits a listen, a dated feedback log
   - `SOUND.md` - how the game must sound (kits, keys, tempos, loudness, do/don't), with a versioned changelog
   - `segan.toml` - default kit, the shared `[mix]` (room, crush, oversample...), `[loudness]` targets, output dir
   - `kits/`, `music/`, `sfx/` - the sources; every asset has a `description`
3. **Always read BRIEF.md and SOUND.md and run `segan status` before making or changing anything.** They are
   your memory between sessions. `segan status` also lists every kit with its instrument keys and names, and says
   when BRIEF.md or SOUND.md is missing: then write short ones (what the game needs; which kit and instrument
   does what, keys and tempos per mood, loudness) from what you know, and list your assumptions for the owner.
4. No `segan.toml` yet -> first-time setup (below).

**SEGAN as MCP tools:** if you have SEGAN tools (`status`, `write_asset`, `preview`...), use them instead of
the CLI; the workflow is the same (`write_asset` lints and returns the listen sheet image).

**Who you work for:** often an orchestrator agent building the game. Batch questions into ONE message, each
with a recommended default, and proceed on the defaults if nobody answers. Report results a program can use:
asset name, files and loop points from `manifest.json`, the listen sheet path, the WAV path, decisions made.


## First-time setup (a new game)

Ask once, in one message, with defaults:
1. **The game**: genre, mood, setting (for BRIEF.md).
2. **The sound, in words**: what it should feel like ("cold ship, warm crew", "dusty lo-fi jazz", "bright 8-bit",
   "eerie folk horror"). Not a menu: synths, the instrument models (plucked and bowed strings, choirs, mallets,
   organs, FM, wavetables), effects and real recorded instruments (pianos, guitars, strings, brass, winds, world
   percussion, drum kits: sample libraries fetched on request) can all sit in one kit.
3. **The identity**: 2-3 signature instruments or sounds every song should share (default: the rolled kit's
   `identity` group), and any motif the game has.
4. **References**: games or soundtracks it should evoke.
5. **Engine**: Godot 4 (default; path to the project) or plain WAVs + manifest.
6. **Mix**: dry or roomy (`[mix] room`, default 0.15), lo-fi crush or clean (default clean).

Then: `segan init audio --style "<the words>" [--godot <godot project>]` (writes `segan.toml` with a random project
`seed`, BRIEF.md, SOUND.md and a kit `core` rolled from the seed and the words; `--style chiptune|synth|orchestral`
gives a fixed starter kit instead). Two projects with the same brief get different kits, by design: don't copy
another project's kit. `segan kit show core` and **look at the kit sheet**; adjust the kit (`segan docs kits`) until every
instrument is distinct and in a sensible range (`segan kit roll core --style ... --take 1 --force` rolls again), then
ask the owner to listen to `previews/kits/<kit>.wav`. Fill in BRIEF.md (game, key sounds, music list) and SOUND.md
(the identity, which instrument does what, how songs vary, loudness). Log the owner's answers in BRIEF.md's
feedback log.


## Project layout

```
segan.toml   BRIEF.md   SOUND.md
kits/<name>.kit.yaml     music/<name>.song.yaml     sfx/<name>.sfx.yaml     music/<name>.soundtrack.yaml
previews/  (scratch: WAVs, listen sheets; gitignored)    .segan-cache/ (render cache; gitignored)
```

Notes are written like `A4` (= 440 Hz, MIDI 69), `C#5`, `Bb2`, `C-1`. Keys are a root and a scale:
`A minor`, `C major`, `D dorian`, `E phrygian`, `F lydian`, `G mixolydian`, `B locrian`, `A harmonic_minor`,
`A melodic_minor`, `C pentatonic_major`, `A pentatonic_minor`, `A blues`, `C whole_tone`, `C chromatic`.
