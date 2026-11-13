# Build

After approval: build, manifest.json and what to report.

## After approval: build and report

`segan build` (add `--verify-godot` when a Godot binary is available) writes WAVs, `manifest.json` and Godot
resources into `output_dir`. Report what the game needs, from `manifest.json`:
- the file (`res://...` in Godot), length, `loop` `{start, end}` in samples (end exclusive);
- songs: `bpm`, `sections` and `markers` in samples, seconds and bars (for syncing game events), `variants`,
  `stems` (+ `godot_stems`, an AudioStreamSynchronized: set each stream's volume to bring layers in and out);
- SFX: `variations`, `takes` (+ `godot_randomizer`: play that one stream, it picks a variation or take each time), `phases`,
  `playback` hints; with `[bus]` in segan.toml, each asset's `bus` and the top-level `buses` (category volumes).
Frequent sounds (gunfire, footsteps, bursts of pickups) get `playback: { max_instances, min_gap_s,
repeat_attenuation_db }` and quiet categories a `[bus.<category>] volume_db`, so the game doesn't invent its own
dB table; `segan_sfx.gd` (autoload `SeganSfx`, `SeganSfx.play("coin")`) applies both (`segan docs godot`).
In Godot, loops already loop (SEGAN writes the loop points into each WAV's `.import`); play SFX with an
AudioStreamPlayer/2D/3D on an "SFX" bus and music on a "Music" bus. Flow songs and soundtracks are played by
the director `segan_music.gd` (written next to the manifest): autoload it as `SeganMusic`, then
`SeganMusic.play_soundtrack("main")` / `set_state("combat")` / `play_song(...)` / `stop(...)` (`segan docs godot`).


## Build output (any engine)

`manifest.json` in `output_dir` is the contract with the game. Per asset: `kind`, `category`, `description`,
`tags`, `status`, `style_version`, `sample_rate`, and
- every audio file as `{ file, seconds, samples, channels, loop }` (`loop` = `{start, end}` in samples, end
  exclusive, or null), `lufs`, `target_lufs`, `limiting_db`;
- with `[bus]`: `bus` on every asset whose category is listed;
- SFX: `playback` (the SFX's hints, when it has them); `lufs`/`target_lufs`/`limiting_db` on the main sound and on each variation; `dry_seconds` on every one-shot file entry (the sound without its room tail: how long a voice pool should
  count it busy; `seconds` includes the tail), `variations` (list, + `pitch_offset_semitones`), `godot_randomizer`, `phases` (name -> file entry);
  with `takes:`, the entry itself is take 1 and `takes` lists the others: `{ take: k, file..., lufs..., variations: [...] }`
  (no `file` when that take's `include_main` is false);
- songs: `bpm`, `meter`, `steps_per_beat`, `key`, `beat_seconds`, `beat_count`, `bars`, `sections` (name ->
  start/end in samples, seconds and bars, first occurrence), `arrangement` (every section in order), `markers`
  (name -> sample, seconds, bar), `loop` (`start`/`end` in the file + `offset`: the loop points sit that many
  samples (whole bars, usually one) after the loop section's start and the song's end, because the file carries
  that much of the loop's start again with the end's tail ringing into it; `section`), `variants` (name -> file entry + timing),
  `stems` (stem -> file entry + `tracks`), `stem_mixes` (mix -> `stems`, `lufs`, `trim_db`), `stems_normalised_over` and
  `godot_stems`. With `main_mix: false` / `include_main: false` the entry has no `file` (timing and loop stay).
- flow songs: `flow` = `start`, `next` (section -> {successor: weight}), `end`, `no_repeat`, `head_bars`, `sections`
  (name -> `samples` (its length: play the next section exactly this many samples after it starts), `seconds`,
  `bars`, `head_samples`, `head`/`rest`/`tail` files and `from` (previous section -> head file; when the previous
  section isn't listed, the cold `head`)), `variants` (variant -> the same clips). A walk plays, per section, the
  head (`from[prev]` or `head`) for `head_samples` samples, then `rest` for `samples - head_samples`; after the
  last section, its `tail`. Clip files carry 32 extra samples (Godot stops a WAV a few samples before its end):
  play each for its stated length, not to its end.
Top level: `buses` (with `[bus]` only: category -> `bus`, `volume_db`), `godot_bus_layout` (with `[bus]` and
export "godot": `segan_buses.tres`), `soundtracks` (name -> `start`, `states` (state -> `songs` [{song, variant, weight, family}], `play`,
`gap`, `fade_out`, `crossfade`), `families`, `transitions` ("from>to" -> `at`, `fade`, `fade_in`, `stinger`,
`start`), `default_transition`).
Files: `music/<song>.wav`, `music/<song>.<variant>.wav`, `stems/<song>/<track>.wav`, `flow/<song>[.<variant>]/<clip>.wav`,
`sfx/<name>.wav`, `sfx/<name>.<n>.wav`, `sfx/<name>.t<k>.wav`, `sfx/<name>.t<k>.<n>.wav`, `sfx/<name>.<phase>.wav`. WAVs are 16-bit PCM with a `smpl` loop chunk and `cue` markers.
With `"ogg"` in `export`, every music file (songs, variants, stems, flow clips) is `.ogg` instead (same samples
count; a looping file ends exactly at its loop end, the loop restarts at `loop.start`); SFX stay `.wav`.
The build only rewrites files that changed and deletes outputs (and their `.import`) it no longer produces.
