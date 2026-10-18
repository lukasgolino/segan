# Sound bible

How this game sounds. Agents check every new sound and song against it; SEGAN enforces what it can
(kits, scales, the shared [mix], loudness targets, lint) and the rest is for listening.

## 1. Palette (kits)

- Default kit: `$kit` (`segan kit show $kit` plays every instrument).
- What each instrument is for, e.g. `p` lead melodies, `b` bass lines only, `k s h` the only drums.
- Instruments not in a kit don't exist: add them to the kit (and get them approved) before using them.

## 2. Music

- Keys and modes: TODO (e.g. minor keys for dungeons, major/mixolydian for towns).
- Tempo range: TODO (e.g. 90-140 bpm); meter 4/4 unless stated.
- Loops: every in-game track loops seamlessly (W007 clean); intros are separate sections.
- Length: 8-32 bars per loop; reuse patterns with derived patterns instead of writing new ones.
- Arrangement: at most 4-5 tracks (lead, harmony/arp, bass, drums); bass stays below C4.

## 3. Sound effects

- Short and immediate: no leading silence (W005), the attack in the first 5 ms.
- One family per action: pickups bright and rising, damage low and noisy, UI soft and short.
- Frequent sounds (steps, shots, hits) get `variations` so repeats don't fatigue.
- Categories: `sfx` (default), `ui` (quieter), add more in segan.toml [loudness].

## 4. Mix

- One room for everything ([mix] room); no per-asset reverb.
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
