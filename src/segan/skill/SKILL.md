---
name: segan
description: Make and maintain game audio with SEGAN - sound effects, music loops and long-form soundtracks, instrument kits, stems and variants, realistic SFX from CC0/CC BY recordings - and change a game's sound over time (brighter, warmer, lo-fi, louder). Use whenever a user or an orchestrating agent asks for game audio, a sound, an SFX, music, a song, a loop, a jingle or a kit, or mentions segan / segan.toml.
---

# SEGAN: game audio as text

You write instrument kits, songs (step grids) and SFX (synth layers, processed recordings) in YAML; the `segan`
CLI lints them, renders **listen sheets** (PNG pictures of the sound) and numbers you can check, and builds WAVs,
`manifest.json` and Godot resources. This page is the core. Everything else is a topic: **`segan docs <topic>`**
prints one, `segan docs --search <words>` finds the paragraphs you need. Read only the topics your task needs.

| Topic | When |
|---|---|
| `listening` | reading a listen sheet and the `--json` numbers in full |
| `setup` | no `segan.toml` yet; project layout; what to ask the owner |
| `kits`, `models`, `samples` | the palette: kit notation, instrument models + effects, recorded instruments |
| `sfx`, `recorded` | sound effects: presets, layer recipes, notation; Freesound recordings |
| `songs`, `long-form`, `soundtrack` | music: patterns, craft, loops, variants, stems; flow graphs; game states |
| `build`, `godot`, `engines` | after approval: the manifest, what to report, engine wiring |
| `config`, `commands`, `lint` | segan.toml, every command and flag, every lint rule (`segan docs lint`) |
| `api` | generator scripts (`segan.api`), with a worked example |
| `evolve` | "brighter", "too loud", "more retro": changing every asset at once |
| `report` | filing what got in your way |

## You can't hear

You never hear what you make. Use both substitutes every time (`segan docs listening` explains every panel):
1. **The listen sheet** `previews/<asset>/<output>.listen.png` (Read it): header (length, LUFS vs target, peaks,
   seam click), piano roll per track (songs: what you wrote), waveform (red = clipped), spectrogram (white = the
   pitch you asked for, cyan = detected), LUFS curve.
2. **The numbers** (`segan preview <name> --json`): `lufs` vs `target_lufs`, `true_peak_dbtp`,
   `leading_silence_ms`, `seam_click`, `onsets_s`, `pitch_hz`, `pitch_check` (songs), `notes_per_pattern`.

They show timing, pitch, envelope, loudness, clicks, aliasing. They can't show whether it is good. So: never
call a sound good or approved; say what you checked. Every asset stays `status: draft` until a **human**
listens (give them the WAV path); only they approve (`segan mark <asset> --status approved`). Keep "Awaiting a
listen" in BRIEF.md.

## Every task

1. `segan --version` (missing: install the version the project pins). `segan status` finds the audio home
   (the folder with `segan.toml`), lists kits and keys, flags stale assets. No project: `segan docs setup`.
2. **Read BRIEF.md and SOUND.md first**: they are your memory between sessions (what the game needs, how it must
   sound, what awaits a listen).
3. Make or change the asset:
   - SFX: `segan new sfx <name> --preset <coin|jump|laser|explosion|hit|hurt|powerup|blip|select|door|step>
     --description "..."`; real-world sounds (animals, impacts, weather...) come from recordings (`recorded`).
   - Song: `segan suggest song <name> --mood "..."`, then `segan new song <name> --bars 2 --description "..."`.
     Rows are scale notes: pick rows, not pitches. Short patterns, reused (`songs`).
   - Kit: `segan kit show <kit>` and look at the sheet after any kit edit.
4. `segan lint <file>`: fix every error and every real warning (a kept warning goes in `lint: { disable: [...] }`
   with a comment). `segan preview <name>`: its text already lists the numbers you check (LUFS, peaks, pitch,
   lead-in, pitch check, notes per pattern, closest song); `--json` only for more. Open the listen sheet, check
   it against what you meant. About four rounds at most, then hand the WAV to a human.
5. After approval: `segan build` and report from `manifest.json` (`build`).

**MCP:** with SEGAN tools (`status`, `write_asset`, `preview`, `docs`...), use them instead of the CLI; same workflow.
**Orchestrators:** batch questions into one message, each with a default, and go on with the defaults.
Report what a program can use: asset name, files, loop points, sheet and WAV paths, decisions.

## Spend few tokens

- `segan docs <topic>` instead of reading SEGAN's source or a whole reference. A question the topics don't
  answer is worth a report (`report`).
- Prefer `--json` and read only the fields you need; the listen sheet once per change, not per command.
- One command that answers the question beats several probes: `segan status`, `segan kit show --json`,
  `segan preview --json`.

## Rules of thumb

- Kits are the palette: don't invent instruments inside songs (strict mode: E009).
- Short patterns, many references; labelled rows; one job per track.
- Same game, different songs: identity instruments in every song, everything else varies (key, mode, tempo,
  meter, register, texture). Defaults (A minor at 120, I-vi-IV-V, a detuned-saw pad) are starting points every
  project shares: move away from them.
- Report numbers, not opinions; humans approve. Don't hand-edit build output. Don't commit or push unless asked.
- SEGAN seems wrong (a crash, a misleading message)? Say so and offer to report it (`segan docs report`).
