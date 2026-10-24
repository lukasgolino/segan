# Sound bible

How this game sounds. Agents check every new sound and song against it; SEGAN enforces what it can
(kits, scales, the shared [mix], loudness targets, lint) and the rest is for listening.

## 1. Palette (kits)

- Default kit: `$kit` (`segan kit show $kit` plays every instrument).
- **Identity**: the 2-3 signature instruments every song shares (the kit's `identity` group) and the game's motifs:
  TODO. This is what makes every song sound like the same game.
- **Variation**: every song adds 1-2 instruments of its own from the wider palette (models, effects, samples; more
  kits with `segan kit roll <name> --style "..." --around $kit`).
- What each instrument is for, e.g. `p` lead melodies, `b` bass lines only, `k s h` the only drums.
- Instruments not in a kit don't exist: add them to the kit (and get them approved) before using them.

## 2. Music

- Songs differ: key and mode, tempo, meter, register, opening texture and instruments vary from song to song
  (`segan suggest song` proposes them; `segan similarity` checks; no two songs open on the same notes).
- Keys and modes by mood: TODO (e.g. phrygian or harmonic minor for dungeons, lydian for dreams, mixolydian for towns).
- Tempo range: TODO (e.g. 60-170 bpm across the game); meters TODO (4/4, 3/4, 6/8...).
- Songs so far (keep this list current): TODO (name, key, tempo, meter, texture, extras).
- Loops: every in-game track loops seamlessly (W007 clean); intros are separate sections.
- Length: 8-32 bars per loop; reuse patterns with derived patterns instead of writing new ones.
- Arrangement: 4-6 tracks (identity instruments + the song's extras); dynamics (`velocity:` rows, `dynamics:`
  ramps) and `humanize` so nothing sounds mechanical.

## 3. Sound effects

- Short and immediate: no leading silence (W005), the attack in the first 5 ms.
- One family per action: pickups bright and rising, damage low and noisy, UI soft and short.
- Frequent sounds (steps, shots, hits) get `variations` so repeats don't fatigue.
- Categories: `sfx` (default), `ui` (quieter), add more in segan.toml [loudness].

## 4. Mix

- One room for everything ([mix] room); instrument `fx` (delay, chorus, a reverb send) shape single instruments.
- Loudness: music -16 LUFS, SFX -14, UI -20 (segan.toml [loudness]); the build normalises.
- Lo-fi: crush settings in [mix] only, so every asset matches.

## 5. Do / don't

- Do keep melodies inside the scale (strict roll rows make this automatic).
- Do write row labels on every grid row (E011 catches shifted rows).
- Don't stack more than the instrument's `voices` notes at once (E014).
- Don't approve your own music: a human listens first (`status: draft` until then).

## 6. Reference sounds

2-4 approved assets that define the sound (listen sheets in previews/). Compare new ones against them.

## Changelog

Versions of this sound bible; segan.toml `style_version` is the current one (`segan style bump` adds entries).

- v1: first version.
