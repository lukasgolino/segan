---
name: segan
description: Make and maintain game audio with SEGAN (Sound Effect Grammar And Notation) - sound effects (coin, jump, laser, explosion, hit, footsteps, doors, UI blips, engine hums), music loops and long-form soundtracks (exploration, combat, menus, shops, jingles; section graphs, game states, transitions), instrument kits, adaptive stems and variants, realistic SFX from recordings (Freesound, CC0/CC BY) - and change a game's sound over time (brighter, warmer, more reverb, lo-fi, louder or quieter). Use whenever a user or an orchestrating agent asks for game audio, a sound, an SFX, music, a song, a loop, a jingle or a kit, or mentions segan / segan.toml.
---

# SEGAN: making game audio as text

SEGAN turns text into game audio. You write instrument kits, songs (step grids, like pixel grids) and SFX
(synth layers and processed recordings) in YAML; the `segan` CLI lints them, renders **listen sheets** (PNG pictures of the sound) and
numbers you can check, and builds engine-ready WAVs, `manifest.json` and Godot resources. Full notation:
[reference.md](reference.md). Everything below is the workflow.

## 0. You can't hear. Read this first.

You will never hear what you make. SEGAN gives you two substitutes, and you must use both every time:

1. **The listen sheet** (`previews/<asset>/<output>.listen.png`, open it with the Read tool). Top to bottom,
   on one time axis:
   - header: length, peak, true peak, **LUFS vs. target**, limiter reduction, lead-in (SFX), **seam click** (loops);
   - sections/patterns strip and a **piano roll per track drawn from your source** (songs): what you wrote;
   - waveform (red = clipped): attack shape, decay, gaps, how dense it is;
   - log-frequency **spectrogram** with octave lines (C1...C9): bright horizontal lines = pitched tones, their
     overtones stacked above; vertical smears = noise/percussion; **white lines = the pitch you asked for,
     cyan dots = the pitch SEGAN detected** (SFX). Lines that run the wrong way (falling when your sweep rises)
     or faint mirrored lines high up are aliasing (lint W010);
   - LUFS curve (songs): loudness over time; the green line is the target.
2. **The numbers** (`segan preview --json`): `lufs` vs. `target_lufs`, `true_peak_dbtp`, `leading_silence_ms`,
   `seam_click`, `onsets_s` (when each hit starts), `pitch_hz` (SFX start/end/min/max), `pitch_check` (songs:
   every note's detected pitch vs. the written one, in cents; only tracks that play one note at a time; low notes
   are also read as their 3rd/5th harmonic; `detune_cents` = an instrument whose notes all share one offset, e.g. a sample
   recorded slightly sharp: its notes count as off only relative to that),
   `notes_per_pattern` (songs: compare with what you meant to write; a dropped note shows here first),
   `centroid_hz` (brightness), `clipped_samples`, `normalisation_gain_db` (how much the build had to raise or
   lower it: large values are fine, the level is set by the target either way).

What the sheet and numbers **can** show: timing, rhythm, pitch and pitch movement, envelope shape, noise vs.
tone, loudness, clicks, aliasing, silence, a wrong row. What they **cannot** show: whether a melody is good,
whether a sound is pleasant or fits the game, whether the mix balance feels right. So:

- Never call a sound or a song "good" or "approved". Say what you checked ("pitch rises B5 -> E6 as asked,
  -14.0 LUFS on target, no lead-in, no clicks").
- Every asset stays `status: draft` until a **human** listens: give them the WAV path. Only they run
  `segan mark <asset> --status approved` (or tell you to).
- Keep a list of what awaits a listen in BRIEF.md ("Awaiting a listen").

## 1. Setup check

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
4. No `segan.toml` yet -> first-time setup (section 2).

**SEGAN as MCP tools:** if you have SEGAN tools (`status`, `write_asset`, `preview`...), use them instead of
the CLI; the workflow is the same (`write_asset` lints and returns the listen sheet image).

**Who you work for:** often an orchestrator agent building the game. Batch questions into ONE message, each
with a recommended default, and proceed on the defaults if nobody answers. Report results a program can use:
asset name, files and loop points from `manifest.json`, the listen sheet path, the WAV path, decisions made.

## 2. First-time setup (a new game)

Ask once, in one message, with defaults:
1. **The game**: genre, mood, setting (for BRIEF.md).
2. **Sound style**: chiptune (default: pulse/triangle/noise, NES/Game Boy era), 80s synth (filtered saws,
   square bass, punchy drums) or orchestral (sampled strings, brass, woodwinds, harp, timpani: the `vsco2`
   library, ~1 GB to download; or the game's own SoundFont/SFZ).
3. **References**: games or soundtracks it should evoke.
4. **Engine**: Godot 4 (default; path to the project) or plain WAVs + manifest.
5. **Mix**: dry or roomy (`[mix] room`, default 0.15), lo-fi crush or clean (default clean).

Then: `segan init audio --style chiptune|synth [--godot <godot project>]` (writes `segan.toml`, BRIEF.md,
SOUND.md and a starter kit). `segan kit show` and **look at the kit sheet**; adjust the kit (section 3) until
every instrument is distinct and in a sensible range, then ask the owner to listen to `previews/kits/<kit>.wav`.
Fill in BRIEF.md (game, key sounds, music list) and SOUND.md (which instrument does what, keys and tempos per
mood, loudness). Log the owner's answers in BRIEF.md's feedback log.

## 3. Kits (the palette)

Pick the kit per song from SOUND.md (e.g. a soft kit for shops, a punchy one for combat); `segan new song`
uses `default_kit` unless you pass `--kit`.

A kit maps one-character keys to instruments; songs write those keys in their grids, so every song made with
a kit sounds like the same game. Keep kits small (6-10 instruments) and give each a job: one or two leads, a
bass, maybe a pad or arpeggio, 3-5 drums.
- `range` on melodic instruments keeps notes where they sound good (bass: E1-C4; leads: C4-C7); lint E007
  enforces it.
- `voices: 1` (default) is a chip channel: a new note cuts the old. Chords need `voices: 3` or more (E014).
- Arpeggio instruments (`arp:`) use fixed semitone offsets, so make them mode-neutral (`[0, 7, 12]`) unless
  every song is in a major key.
- **Sampled instruments** (`sample: vsco2/violins_sus`, `.sfz`, `.sf2`, `.wav`; reference "Samples"): `segan
  samples list` shows the library, `segan samples fetch vsco2 <instruments>` downloads what the kit uses (lint
  names any that are missing). Sections need `voices` for chords; `_sus` instruments hold while the note does
  (W014 if a note outlasts its sample: re-strike long notes), `pizz`/`stac`/harp/percussion ring by themselves.
  Mix them like an orchestra: strings hold chords, one lead line (horn, flute, solo violin), harp or pizz for
  motion, timpani and crash only on downbeats; a bigger room (`[mix] room = 0.3`, `room_decay = 1.6`).
- After any kit edit: `segan kit show <kit>`, look at the sheet (each instrument's segment: pitch lines on the
  white targets, attack/decay shape, no red), check `W010` aliasing, then a human listens.

## 4. Making a sound effect

0. **Synthesise or record?** Read `[sfx] source` in segan.toml (`segan config get sfx.source`): `synth` = never
   record (W020), `recorded` = prefer recordings, `auto` (default) = decide per sound:
   - **Synthesise**: UI, coins and pickups, retro/arcade sounds, lasers, magic, sci-fi, musical stingers. Steps 1-4.
   - **Record**: anything real-world: animals, voices, footsteps, material impacts (wood, metal, glass, gravel),
     weapons (swords, guns, bows), fire, water, weather, vehicles, ambience. "Recorded SFX" below.
   - **Hybrid**: a recording with synth layers for what it lacks: a sub thump under an explosion or a cannon, a
     shimmer on a magic impact, a tail.
   A request that doesn't say: realistic (record) or stylised (synthesise)? Use the game's style in SOUND.md.
1. Start from the closest **preset**: `segan new sfx <name> --preset <coin|jump|laser|explosion|hit|hurt|powerup|blip|select|door|step> --description "..."`
   (no preset fits: `segan new sfx <name>` gives a one-layer starter). Presets are good starting points;
   change one preset layer by its `id` (only the fields you give change; the scaffold lists the preset's layer
   ids), add layers, drop layers with `remove: [id]`, or `segan bake sfx <name> --in-place` to write every field
   out and edit freely.
2. Think in layers: a **body** (pitched tone: pulse/saw/triangle/sine/fm) + a **transient** (short noise
   burst for the attack) + sometimes a **tail** or **sub** (low drum/sine thump). Recipes:
   | Sound | Recipe |
   |---|---|
   | pickup/coin | square, two quick rising notes (pitch keyframes, no slide), short release |
   | jump | square sweeping up (slide) over ~0.15 s |
   | laser/shot | bright square diving 1-2 octaves fast (slide) + a ring-modulated or noisy fizz |
   | explosion | `bitnoise` with falling pitch through a closing low-pass (`cutoff` keyframes) + a deep kick thump |
   | hit/impact | band-passed noise crack + a falling low square knock + a short tom body |
   | hurt | square falling a fifth with fast vibrato + grit |
   | power-up | fast `arp: [0, 4, 7, 12]` climbing an octave + a sparkle |
   | UI blip/confirm | one or two tiny soft tones, category `ui` |
   | footstep | low-passed noise tap + tiny tom, category `foley`, `variations` |
   | door | noise latch click + band-passed saw creak with vibrato + tom thud |
   | engine/hum/alarm | `loop: true` with a `crossfade`, steady layers (or a `phases` loop) |
   | charge-up + release | `phases: { charge: { loop: true, ... }, release: { ... } }` |
3. Things that always matter for SFX:
   - **Start at once**: the main layer at `start: 0` with a fast attack; W005 flags lead-in silence (input lag).
   - `duration` is the hard end of the dry sound; anything still sounding is cut (W011): lengthen it or shorten
     `length`/release.
   - Sounds that repeat a lot (steps, shots, hits) get `variations: { count: 4, pitch: 1, timbre: 0.3 }`;
     Godot gets an AudioStreamRandomizer that cycles them.
   - The file is `duration` plus the shared room's tail (the sheet shows "1.10s + 0.26s room tail"). Short,
     frequent sounds (UI clicks) can go dry: `room: 0` on the SFX or `[room] ui = 0` in segan.toml.
   - `category` picks the loudness target: `sfx` -14, `ui` -20, `foley` -22 LUFS (segan.toml `[loudness]`).
     A sound too short and spiky to reach its target gets W001: `segan preview <name> --json` lists each layer's
     peak/loudness/crest (`layers`); stagger layer starts by 3-9 ms, saturate or lower the peakiest layer, give it
     more body, or use a quieter category.
4. `segan lint <file>` -> fix every error and every warning that's a real problem (a warning you keep on
   purpose goes in the file's `lint: { disable: [...] }` with a comment why); hand over with a clean lint.
   `segan preview <name>` -> **open the listen sheet** and check: the pitch
   movement you wanted (white lines, cyan dots), the attack is instant, the tail decays smoothly, LUFS on
   target, nothing red. Iterate (about 4 rounds at most), then hand the WAV to a human.

### Recorded SFX

Real-world sounds start from recordings that are processed and layered, the way film sound is made (a film lion
is often a tiger pitched down, stretched and layered with a sub growl). Synth recipes can't get there.

1. **Find candidates** (needs `FREESOUND_API_KEY`): `segan sounds search "lion roar" --max-seconds 4 --json`.
   Only CC0 and CC BY sounds come back (never non-commercial). Pick 3-5 by name, tags, duration and rating, then
   `segan sounds inspect freesound:<id> ...` compares them without hearing: length, loudness, peak, brightness
   (`centroid_hz`), pitch, onsets (one clean hit or a clatter of several?). Prefer clean, close, dry recordings:
   a room can be added, never removed.
   **No key?** Say so in your report, and find a sound on the web yourself (a Freesound page, or another site
   with a clear CC0 / CC BY licence), check the licence on its page, download it into the project (`sounds/`) and
   use it as a local file with `licence:`, `source:` (the page URL) and `author:` (or `segan sounds add <file>
   --licence ... --source ... --author ...`, so it's recorded in sounds.lock). Never use a sound whose licence
   you couldn't check.
2. **Keep it**: `segan sounds add freesound:<id>`: checks the licence, fetches the preview into the user cache
   (not the repo) and records it in `sounds.lock` (commit sounds.lock; builds fetch and check the file).
3. **Write the layer**: `sample: freesound:<id>` (or a file path, or a list: one per variation), then shape it:
   `trim: [start, end]` (seconds of the file), `shift: -7` (semitones, length stays), `stretch: 1.5` (x length,
   pitch stays), `reverse`, `fade: [in, out]`, plus the usual `gain`, `filter`, `cutoff` keyframes, `distort`,
   `start`, `length`. Bigger and heavier = shift down a few semitones and stretch a little; distant = low-pass
   (`filter: { type: lp, cutoff: 2500 }`), quieter transient, more room. Add synth layers for weight (a `sine`
   sub or `drum: kick` thump) or sparkle. Variations: a list of 2-4 similar recordings beats pitch jitter.
4. `segan lint` (E019 a missing/changed file, E020 a licence problem), `segan preview` and check the sheet as
   for any SFX (W011 if the recording runs past `duration`: `trim` it or `fade` it out).
5. **Credits**: CC BY requires attribution. `segan sounds credits` writes `SOUND_CREDITS.md`; tell the game
   agent/owner to ship it with the game's credits. `segan sounds vendor` copies the sounds in use into the
   project, only when asked (offline builds).

**What a game agent should put in a sound request** (tell your orchestrator, or ask): what it is and what
makes it ("a lion roar"), realistic or stylised, length ("~2 s"), distance and context ("distant, in a canyon";
"close, UI feedback"), how often it plays (frequent sounds get variations), and the game's style reference.

## 5. Making a song

1. Decide **key, tempo and form** from SOUND.md: e.g. exploration 100-125 bpm in a minor/dorian key; combat
   140-170 bpm; shops/menus 90-110 in major; dungeons phrygian or harmonic minor. Moods: major bright, minor
   sad/tense, dorian adventurous, mixolydian heroic, phrygian menacing, lydian dreamy.
2. `segan new song <name> --key "A minor" --tempo 120 --bars 2 --description "..."` gives tracks with labelled
   empty rows. Rows are the scale's notes, highest first, so **you can't write a wrong note**: pick rows, not
   pitches. Keep the trailing labels on every row (E011 catches a missing or extra row).
3. Write **short patterns** (1-2 bars = 16-32 steps) and reuse them: derived patterns (`from: a` with
   `transpose`, `mute`, `swap`, `shift`, `reverse`, or one lane replaced) and sections (`main: [a, b, a, c]`).
   A 16-bar loop is typically 3-5 written patterns. This keeps files small and the song coherent.
4. Writing music that works (you can't hear it, so follow the craft):
   - Pick a chord per bar (e.g. i VI III VII = Am F C G in A minor; `segan.api.progression` lists the notes).
   - **Bass**: chord roots on the beats (steps 1, 5, 9, 13 of a 16-step bar), octave or fifth hops between.
   - **Melody**: mostly steps between neighbouring rows, a leap now and then followed by a step back; chord
     tones on strong beats (steps 1 and 9); phrases of 2 or 4 bars that answer each other (`transpose` a
     phrase for the answer); rests between phrases. End the loop on a note that leads back to the start.
   - **Harmony/arpeggio**: chord tones in eighths, quieter (track `gain: -3`).
   - **Drums**: kick on 1 and 3 (or every beat for driving music), snare on 2 and 4 (steps 5 and 13), hats in
     eighths; `X` accents and `o` ghosts give groove; a fill in the last bar of a section.
   - W009 flags minor-second/tritone clashes between tracks on a beat (the meter's beat: a dotted quarter in 6/8;
     notes held from earlier count while still above -30 dB): fix them
     unless you want the tension. A dominant seventh (V7, e.g. C7 going to F) contains a tritone on purpose:
     there it's a judgement call between shortening a note and `lint: { disable: [W009] }`.
   - Many similar patterns, or tired of counting dots: generate lanes with `segan.api` (reference.md has a worked
     example) instead of an ad-hoc script.
5. **Loops**: `loop: main` (from the start of that section to the end). The file is the whole song **plus the
   first bar(s) of the loop again**, and the loop points sit that many whole bars later (`loop.offset` in the
   manifest; usually one bar: enough bars to cover the longest release + the room tail). So the loop's own end
   rings into its start, the seam is clean and the intro flows naturally into the first pass. The file is
   therefore longer than the arrangement (8 bars at 100 bpm = 19.2 s, the file 21.6 s): that's expected; engines
   use the loop points. Check `seam_click` and the seam view (`<name>.seam.png`). Intros are their own section
   before the loop.
   **Music the player hears for minutes (exploration, towns, combat) must not be one 8-16 bar loop**: players
   tire of it fast. Write 5-10 contrasting sections (derive most with section changes: `{ from: verse,
   semitones: 2 }`, `{ from: chorus, mute: [drums], velocity: 0.7 }`, a breakdown, a bridge) and a `flow:` graph
   so the game picks the next section at run time; preview `--output walk` and look at the whole walk. Plan the
   game's music as a soundtrack (`music/<name>.soundtrack.yaml`): states with song pools, play times and
   silence gaps (silence between songs is what keeps music fresh), and transitions (sync point, fades,
   stingers). A pool of short loops: group same-key loops into `families` and give the state a `crossfade`
   so they flow into each other. reference.md: "Long-form music" and "Soundtrack".
6. **Variants** in one line each: `danger: { tempo: 150, instrument_swap: { q: r } }`, `calm: { kit: soft_kit }`,
   `night: { semitones: -2 }`, `major: { key: A major }`; combinations with `variant_axes`. Adaptive layering:
   add `"stems"` to `export` (one WAV per track, Godot AudioStreamSynchronized), or a `stems:` block with `groups`
   (one WAV per layer) and `mixes` (the layer combinations the game plays: normalised over the loudest of them;
   each quieter mix gets a `trim_db` the game adds to the stem volumes while it plays that mix).
   Size: many long songs add up (a 3-minute stereo WAV is 30 MB). `"ogg"` in `export` writes music as Ogg
   Vorbis (~10x smaller); a simple chip song can set `sample_rate: 22050` and `channels: mono` for itself.
7. `segan lint`, then `segan preview <song>`: look at the piano roll (is it what you meant?), the spectrogram
   (busy where you expect, bass at the bottom, no smear of clashing notes), the LUFS curve (no holes or spikes),
   `pitch_check` (every note within 50 cents), the seam. Long songs: `--from 9 --to 16` (bars) shows a window.
   Then a human listens to the WAV.
8. Existing music as MIDI: `segan import midi file.mid --kit <kit>` (quantized, snapped to the key, mapped to
   the kit, with a report of every change); then lint, preview and tidy the patterns.

## 6. After approval: build and report

`segan build` (add `--verify-godot` when a Godot binary is available) writes WAVs, `manifest.json` and Godot
resources into `output_dir`. Report what the game needs, from `manifest.json`:
- the file (`res://...` in Godot), length, `loop` `{start, end}` in samples (end exclusive);
- songs: `bpm`, `sections` and `markers` in samples, seconds and bars (for syncing game events), `variants`,
  `stems` (+ `godot_stems`, an AudioStreamSynchronized: set each stream's volume to bring layers in and out);
- SFX: `variations` (+ `godot_randomizer`: play that one stream, it picks a variation each time), `phases`.
In Godot, loops already loop (SEGAN writes the loop points into each WAV's `.import`); play SFX with an
AudioStreamPlayer/2D/3D on an "SFX" bus and music on a "Music" bus. Flow songs and soundtracks are played by
the director `segan_music.gd` (written next to the manifest): autoload it as `SeganMusic`, then
`SeganMusic.play_soundtrack("main")` / `set_state("combat")` / `play_song(...)` / `stop(...)` (reference.md, Godot).

## 7. Changing the sound over time

Global changes go through the shared mix, so **every asset changes at once** and the set stays consistent:

| Owner says | Do |
|---|---|
| "too dry" / "too much echo" | `segan mix adjust --room 0.1` / `--room -0.1` |
| "brighter" / "darker", "muddy" | `segan mix adjust --brightness 2` / `-2` |
| "warmer" / "thinner" | `segan mix adjust --warmth 2` / `-2` |
| "more retro / lo-fi" | `segan mix adjust --crush 8` (`0` = off) |
| "everything too loud" | `segan mix adjust --loudness -2` (all targets) or `segan config set loudness.sfx -16` |
| "UI too loud" | `segan config set loudness.ui -23` |
| "high notes sound harsh/buzzy" | `segan config set mix.oversample 4` (less aliasing) |
| "the lead should be softer" | edit the kit instrument (every song using it changes); `segan kit show` |
| "make the music more tense" | variants (`tempo`, `key`, `instrument_swap`) or new sections |

Always `--dry-run` first, then `segan gallery` (every asset side by side + a loudness chart by category) and
log the change in BRIEF.md. When existing sources must be rewritten (a new kit, new drum style):
`segan style bump "what changed"`, update SOUND.md, go through the assets `segan status` flags (W006), and
`segan mark <name> --current` each one after a human listened.

## 8. Rules of thumb

- Kits are the palette: don't invent instruments inside songs (strict mode makes it an error, E009).
- Short patterns, many references; labelled rows; one job per track.
- Look at every listen sheet you make; report numbers, not opinions; humans approve.
- Previews are for checking; `segan build` output is what the game uses. Don't hand-edit build output.
- Don't commit or push unless asked. If SEGAN itself seems wrong (a crash, a misleading message), say so and offer
  to report it (section 9).

## 9. Help us improve SEGAN: report what got in your way

SEGAN is young, and it gets better mostly through reports from agents like you using it on real games. When
something gets in your way, please tell us in a GitHub issue at https://github.com/lukasgolino/segan/issues. It
is the most useful thing you can do for the project. Whether you do is entirely up to you and your user.

Worth reporting: a crash or traceback; a wrong or misleading message or lint rule; output that looks or behaves
wrong; a workaround you had to invent; a feature you needed and didn't have; this skill or the reference
misleading you.

1. Note it as you go; don't interrupt the task for it.
2. At a natural break (the end of the task, your report), draft the issue: a one-line title; `segan --version`;
   what you did (commands, a minimal source snippet); what you expected and what you got; the workaround, if
   any. End the body with "Reported by an agent using SEGAN." Keep it to a minimal repro: no game names, private
   asset content, paths or anything else from the user's project unless they OK it.
3. Look for an existing issue first: `gh issue list --repo lukasgolino/segan --search "<keywords>"`; if one
   fits, offer a comment on it instead.
4. Show the user the draft and ask whether to file it. Issues are public and posted under their GitHub account,
   so **never file without their OK**. If they agree:
   `gh issue create --repo lukasgolino/segan --title "..." --body-file <draft>`, or give them the link
   https://github.com/lukasgolino/segan/issues/new?template=agent-report.md to file it themselves. If they
   decline, drop it.
