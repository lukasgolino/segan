# Godot

Godot: imports, randomizers, stems, the music director and SFX player.

## Godot

With `export = ["wav", "godot"]` and `output_dir` inside a Godot 4 project, SEGAN writes each WAV's loop points
and compression into its `.import` (Godot keeps the rest; an `.ogg` gets `loop` and `loop_offset`), `sfx/<name>.tres` (AudioStreamRandomizer over the
variations, and with `takes:` over every take's variations, or the take itself when it has none: play it and Godot
picks one, never the same twice in a row) and `stems/<song>.tres`
(AudioStreamSynchronized: all stems in sync; change `stream_N/volume` to layer them).
A new file gets a minimal `.import` (importer, type, SEGAN's params); Godot adds `uid`, `path` and `dest_files` the
first time it imports it, so the first commit after a build is followed by one more `.import` diff once the editor
(or `segan build --verify-godot`) has run. Commit that too; it doesn't recur, and SEGAN keeps Godot's additions.

```gdscript
$Music.stream = load("res://assets/generated/audio/music/overworld.wav")   # loops by itself
$Music.play()
$Coin.stream = load("res://assets/generated/audio/sfx/coin.tres")          # a random variation each play
$Coin.play()
```

**Music director** (`segan_music.gd`, written next to `manifest.json` when the project has a flow song or a
soundtrack). Add it as an autoload named `SeganMusic` (Project Settings > Globals > Autoload), then:

```gdscript
SeganMusic.play_soundtrack("main")             # the soundtrack's start state
SeganMusic.set_state("combat")                 # its transitions decide when and how (beat/bar/section, fades, stinger)
SeganMusic.play_song("overworld", "danger")    # one song directly; a flow song walks its sections until stopped
SeganMusic.queue_section("bridge")             # a flow song's next section, instead of a random pick
SeganMusic.stop(2.0)                           # fade out over 2 s (stop(0.0, "section") lets a flow song ring out)
SeganMusic.section_started.connect(func(song, section): print(song, " ", section))
```

Signals: `song_started(song, variant)`, `section_started(song, section)`, `song_finished(song)`,
`state_changed(state)`. Properties: `bus` (default `Master`), `buffer_seconds` (0.3: audio queued ahead; changes
land after it), `random_seed` (0 = a different walk every run). It chains sections sample-exactly (an
AudioStreamGenerator fed from the clips); a new song starts on the old one's grid within one audio mix chunk.
Native `AudioStreamInteractive`/`AudioStreamPlaylist` aren't generated: in Godot 4.7 the first switches a mix
chunk early and cuts tails, the second clicks at every seam.

**SFX player** (`segan_sfx.gd`, written next to `manifest.json` when the project has a `[bus]` table or any SFX
has `playback` hints). Add it as an autoload named `SeganSfx`, then:

```gdscript
SeganSfx.play("coin")                        # its randomizer (or file), on its category's bus at its volume_db
SeganSfx.play_2d("hit", global_position)     # / play_3d(name, Vector3): positional players
var hum = SeganSfx.play("engine", -6.0)      # extra dB on top; returns the player (null: dropped by min_gap_s)
SeganSfx.stop("engine")
```

It applies `playback` hints (min gap, instance cap stealing the oldest, repeat attenuation) and adds any bus the
manifest names that the game's layout lacks (`add_missing_buses`, default on). `segan_buses.tres` is an
AudioBusLayout with those buses (0 dB, sending to Master); SEGAN never writes `default_bus_layout.tres`. To use
it: `AudioServer.set_bus_layout(load("res://.../segan_buses.tres"))`, or copy its buses into your own layout.
`bus_for(name)`, `volume_db_for(name)` and `stream_for(name)` serve a game that plays through its own players.
