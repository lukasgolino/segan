# Commands

Every command and its flags.

## Commands (all accept `--json`; non-zero exit on errors)

Songs and SFX render in several processes (`-j N` on lint/build, or `SEGAN_JOBS=N`; default: the CPU count up to 8;
`1` = one process); the output is identical. Renders are cached per asset and keyed on the kit instruments the
asset actually plays, so editing one instrument re-renders only what uses it.

| Command | Purpose |
|---|---|
| `segan init [dir] [--open] [--style chiptune\|synth\|orchestral\|"<words>"] [--godot DIR]` | create a project with a random project `seed` and a starter kit (words, e.g. `--style "cold ship, warm crew"`: a kit `core` rolled from the seed, with an `identity` group); `--godot` builds into `DIR/assets/generated/audio`, or `DIR/assets/audio` when a PAGAN project there already builds into `assets/generated`; warns when the two output folders are the same or nested |
| `segan new kit <name>` / `new song <name> [--kit K] [--key "A minor"] [--tempo 120] [--meter 3/4] [--bars 2]` / `new sfx <name> [--preset P] [--kit K]` | starter files (always pass `--description`); a song without `--key`/`--tempo` gets the seeded suggestion (below), away from the project's songs |
| `segan suggest song <name> [--mood "words"] [--take N]` | a plan for a new song away from the project's songs: key and mode, tempo, meter, opening texture, opening voicing (inversion, spread, register), progression, instruments (the kit's identity + extras, maybe a new one), a `seed`, and the `segan new song` command; seeded by the project seed (`--take` = another plan) |
| `segan kit roll <name> --style "words" [--around KIT] [--samples\|--no-samples] [--take N] [--dry-run] [--force]` | a kit from style words and the project seed: `identity` group (2-3 signature instruments), bass, harmony, colour, 3-5 drums, from the models, effects and drums above (samples when the words ask for acoustic/orchestral, or `--samples`); `--around` keeps another kit's identity instruments |
| `segan samples list [library\|file.sf2]` / `segan samples fetch <library> <instrument...> [--all]` | sample libraries: instruments, key ranges and what's downloaded / download instruments |
| `segan sounds search "<query>" [--max-seconds N] [--licence cc0\|cc-by] [--limit 15] [--sort score\|rating_desc\|...]` | Freesound search (needs `FREESOUND_API_KEY`): ref, name, author, licence, duration, rating, tags; only CC0 / CC BY |
| `segan sounds add freesound:<id>` (or the sound's page URL; without `FREESOUND_API_KEY` the public page is read) / `add <file> --licence L --source URL [--author A]` | check the licence, fetch the HQ preview into the user cache, record it in `sounds.lock` (a local file: its licence, source, author) |
| `segan sounds inspect <ref...>` | length, peak, loudness, brightness (centroid), pitch, onsets of recordings (a Freesound ref is fetched into the cache, not recorded) |
| `segan sounds credits [--out FILE]` | `SOUND_CREDITS.md`: attribution for every recorded sound (required for CC BY) |
| `segan sounds remove <ref...> [--force]` / `segan sounds prune [--dry-run]` | drop sounds from `sounds.lock` (remove refuses while an SFX plays them; prune drops every entry no SFX plays: lint W028) |
| `segan sounds vendor [--all]` | copy the Freesound sounds in use into `<project>/sounds/` (offline builds; off by default) |
| `segan kit show [kits]` | every instrument playing a test phrase: `previews/kits/<kit>.listen.png` + WAVs; `--json` gives each instrument's `range` |
| `segan lint [paths] [--warnings-as-errors] [--no-render] [-j N]` | errors + warnings (audio warnings render the asset; cached); exits 1 on errors, 0 when there are only warnings, 1 on warnings too with `--warnings-as-errors` (CI) |
| `segan preview <asset...> [--output main\|variant:X\|variation:N\|take:K\|take:K:variation:N\|phase:X\|stem:T\|mix:M\|flow:CLIP\|walk[:SEED] ...] [--from 5 --to 8] [--summary]` | WAV + listen sheet (+ seam view for loops) per output in `previews/<asset>/`; `--summary` prints one flat row per output (asset, output, seconds, dry, LUFS, target, peak, true peak; `--json`: a `summary` list); analysis in `--json` (SFX: `layers` = each layer dry on its own, `peak_db`/`lufs`/`crest_db`, recorded layers' `ends_s` (where they end
uncut, after trim/stretch/varispeed), plus the dry mix); flow songs also get a walk; `--output reel` (an SFX): the main sound, every variation and every take back to back, 0.4 s apart, to judge the variety; `--format ogg\|mp3` also writes each preview compressed, to share (needs `segan[ogg]`) |
| `segan render <asset...> [--output main\|stem:T\|mix:M\|variant:X ...]` | WAVs only, from the render cache (no analysis or sheets: fast for long stemmed songs); `--json` lists each output's WAV, length and loop |
| `segan gallery` | every asset's waveform + spectrum and a loudness chart by category |
| `segan bake sfx <name> [--in-place]` | expand a preset/template into every field |
| `segan import midi <file.mid> [--kit K] [--key K] [--quantize 16] [--bars-per-pattern 2]` | MIDI -> song + change report |
| `segan similarity [songs] [--shipped] [--machine] [--top 15]` | how alike songs are: pairs by `overall` with `harmony` (chroma per bar), `rhythm` (onsets), `timbre` (instruments), `register`, `tempo` (0-1 each), `same_opening`, `same_pitch_set`, `opening_score` (what W024 compares); `closest` per song. `--shipped` adds SEGAN's examples, `--machine` other projects (local_store) |
| `segan build [--verify-godot] [-j N]` | final WAVs + manifest (+ Godot files); `--verify-godot` loads and plays everything headless |
| `segan status [--fast]` | catalogue + what needs attention |
| `segan mark <asset...> [--status approved\|draft] [--current] [--outdated]` | record reviews |
| `segan style bump "note"` | new style version; flags older assets (W006) |
| `segan config show` / `get <key>` / `set <key> <value>` / `unset <key>` | every setting with its default and meaning |
| `segan mix adjust [--brightness dB] [--warmth dB] [--room d] [--crush bits] [--loudness LU] [--dry-run]` | change the whole project's sound |
| `segan docs [topic...] [--search words]` | these docs: list the topics, print one, or find the paragraphs you need |
| `segan skill install [dir]` | install this skill into a repo's `.claude/skills/segan/` |
| `segan mcp [--project DIR] [--allow-godot]` | MCP server over stdio (needs `segan[mcp]`) |

Slow steps print `segan: ...` progress lines on stderr (`--quiet` or `SEGAN_QUIET=1` turns them off).

**MCP tools** (same JSON as the commands): `status`, `docs` (these topics), `read_docs`, `write_doc`, `log_feedback`, `config_show`/
`config_set`/`config_unset`, `kit_list`, `kit_show` (image), `kit_write`, `mix_adjust` (dry run by default),
`scaffold`, `read_asset`, `write_asset` (writes + lints + listen sheet image), `lint`, `preview` (image: sheet or
seam; `audio: true` adds the WAV), `gallery` (image), `mark`, `style_bump`, `import_midi` (path or base64),
`sounds_search`, `sounds_add`, `sounds_inspect`, `sounds_credits` (recorded sounds; search needs `FREESOUND_API_KEY`),
`build` (`verify_godot` needs `--allow-godot`), `manifest`. Resources: `segan://workflow`, `segan://docs/{topic}`,
`segan://brief`, `segan://sound`, `segan://manifest`, `segan://kit/{name}`, `segan://asset/{name}`,
`segan://audio/{name}`. Prompts: `setup_new_game`, `make_sound`, `change_the_sound`, `review_asset`.
