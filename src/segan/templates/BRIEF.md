# Sound brief

The long-term memory for this project's audio: what the game is, what it needs, and decisions made along
the way. Agents read this (with SOUND.md) before making or changing any sound, and keep it up to date.
`segan status` lists what exists; this file says what's *wanted* and why.

## The game

- **Title / working name:** TODO
- **Genre and core loop:** TODO (e.g. top-down action; explore, fight, collect)
- **Sound style:** $style
- **Mood / references:** TODO (games, soundtracks or eras the sound should evoke)
- **Engine:** TODO (Godot 4 / other; where the audio folder is)

## Key sounds and music

For each: what it is, when it plays, length, looping or one-shot, variations. Example:

- **Coin pickup** (`sfx/coin.sfx.yaml`): bright two-note chime, < 0.3 s, 4 variations.
- **Overworld theme** (`music/overworld.song.yaml`): upbeat A-minor loop, 120 bpm, a "danger" variant.

## Wishlist

What's still needed, roughly in priority order. Move items to "Done" with the asset name when made.

- [ ] TODO

## Done

- (nothing yet)

## Awaiting a listen

Assets an agent made that a human hasn't approved yet (agents can't hear: they check listen sheets and numbers).

- (nothing yet)

## Decisions and feedback log

Dated notes on what the owner asked for and decided, so later sounds stay consistent with it. Example:

- 2026-01-01: "Everything sounds too dry" -> `segan mix adjust --room +0.1` (applies to every asset).
