# Sound brief

The long-term memory for this demo project's audio (a stand-in for a small top-down action-adventure game).
Agents read this (with SOUND.md) before making or changing any sound, and keep it up to date.

## The game

- **Title / working name:** SEGAN demo
- **Genre and core loop:** top-down action adventure; explore, fight, collect, shop
- **Sound style:** chiptune first (NES-like `nes` kit), with a soft FM kit for calm places and an 80s synth kit for combat
- **Mood / references:** bright and adventurous overworld, tense combat, cosy towns
- **Engine:** Godot 4.7 (`../godot`, builds into `assets/generated/audio`)

## Key sounds and music

- **SFX** (`sfx/`): the 11 presets as a starting set (coin, jump, laser, explosion, hit, hurt, powerup, blip,
  select, door, step) and `door_creak` (slow eerie creak, ~1 s).
- **overworld** (`music/`): exploration loop, A minor, 120 bpm, `nes` kit; variants `danger` and `calm` (fm_soft).
- **combat**: battle loop, E minor, 150 bpm, `arcade_synth` kit; variant `boss`.
- **shop**: cosy item-shop loop, F major, 100 bpm, `fm_soft` kit.

## Wishlist

- [ ] Title-screen jingle (non-looping, ~6 s)
- [ ] Engine/ambient hum loop for a machine room

## Done

- (nothing approved yet)

## Awaiting a listen

Everything in the project: agents made them and checked listen sheets and numbers, but nobody has heard them.

- `door_creak` (sfx), `shop` (song): made by a fresh agent from the skill alone (2026-10-19).
- all presets, `overworld`, `combat`: made while building SEGAN (2026-10-19).

## Decisions and feedback log

- 2026-10-19: door_creak and shop made on request (orchestrator); drafts, not yet heard.
