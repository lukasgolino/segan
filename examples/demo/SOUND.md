# Sound bible

How the demo game sounds. Agents check every new sound and song against it.

## 1. Palette (kits)

- `nes` (default): `p` pulse lead (melodies), `q` soft pulse (arpeggios/harmony), `r` thin pulse (danger
  variants), `b` triangle bass (bass lines only), `n` crunch (noise effects), `k s h o c` drums.
- `fm_soft`: calm places (shops, towns, the overworld's `calm` variant): `f` flute lead, `e` electric piano
  chords (4 voices), `a` FM bass, `l` bell accents, `w` pad, `k s h t` soft drums.
- `arcade_synth`: combat: `l` filtered saw lead, `a` power-chord arpeggio, `m` square bass, `z` zap, `k s c h` drums.

## 2. Music

- Keys: minor/dorian for exploration, minor for combat, major for towns and shops.
- Tempos: exploration 100-125, combat 140-170, towns/shops 90-110 bpm; 4/4 on a sixteenth grid.
- Every in-game track loops seamlessly from its main section; intros are separate sections.
- 8-16 bar loops built from 1-2 bar patterns and derived patterns; 3-4 tracks (lead, harmony, bass, drums).

## 3. Sound effects

- Immediate: the attack in the first 5 ms, no lead-in.
- Pickups bright and rising; damage low and noisy; UI tiny and soft (category `ui`); footsteps `foley`.
- Repeating sounds (steps, shots, hits) have `variations`.

## 4. Mix

- One room for everything ([mix] room 0.15); loudness music -16, sfx -14, ui -20, foley -22 LUFS.

## Changelog

- v1 (2026-10-19): first version.
