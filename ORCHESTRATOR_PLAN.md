# ORCHESTRATOR_PLAN.md — reports from game orchestrators

Bug and feature reports filed by agents orchestrating games that consume SEGAN (same scheme as PAGAN's
ORCHESTRATOR_PLAN.md). Append-only; newest at the bottom.
Each report: id, type, severity, version, context, repro, expected, actual, impact, proposal.

---

## Age of Boom (`~/repos/age-of-boom`), first full audio set — 2026-10-19, segan v0.1.0 (a850729), Godot 4.7.2

Context: the game replaced its procedural GDScript audio with SEGAN: kit `band` (folk-synth ship's band), 6 songs
(4 looping with base/calm/combat layers as stems, 2 one-shot stings) and 15 SFX (8 with variations, 1 loop), built
into `assets/audio/` with `export = ["wav","godot","stems"]`. Three agents (composer, SFX designer, Godot developer)
worked from the skill alone. Overall: the pipeline worked end to end on the first try; lint, listen sheets and
determinism did their job. The reports below are what slowed the agents down or needed workarounds. Game-side log:
`age-of-boom/SEGAN_LOG.md`.

### S1 · feature · high · Adaptive layers: stems are normalised by a mix the game never plays
- **Context:** Adaptive music = base layer always + calm OR combat layer (crossfaded). Encoded as track-name prefixes
  (`base_*`, `calm_*`, `combat_*`); the game sums stems per layer.
- **Actual:** loudness normalisation measures the full mix (all layers at once). base+calm landed ~3 LU and
  base+combat ~1.5 LU under the music target. Workaround: a separate `music_layers = -14` category per song.
- **Also:** no way to preview a layer combination (the composer summed stems through `segan.render` internals), and
  one WAV per track means 7-8 stems per song where the game needs 3 layers.
- **Proposal:** `stems: { groups: { base: [base_*], calm: [calm_*], combat: [combat_*] }, mixes: { calm: [base, calm], combat: [base, combat] } }`:
  one WAV per group, normalisation over the loudest listed mix (or each mix reported in `preview --json`), and
  `segan preview <song> --output mix:calm`. Godot: one AudioStreamSynchronized with the groups.

### S2 · feature · medium · Build always writes outputs the game doesn't use
- **Actual:** a stemmed song writes the full mix too; an SFX with variations writes `<id>.wav` plus `<id>.1..N.wav`.
  The set is 255 MB of WAV, ~1/3 unused, and Godot imports and exports all of it unless the game excludes them.
- **Proposal:** `export` options `"no_main_mix"` (stems only) and SFX `variations: { include_main: false }`, or list
  unused files in the manifest under `unused_by_default` so exporters can skip them.

### S3 · feature · medium · Room tail can't be shortened per asset or category
- **Repro:** `ui_click` with `duration: 0.05` → 0.43 s file ("0.04s + 0.43s room tail"); hit/splash 0.4 → 0.6 s.
- **Impact:** engines manage voices by file length; frequent short sounds now hold voices 50-800 % longer.
- **Proposal:** per-asset / per-category `room` send (`[mix.category.ui] room = 0`) and a `tail_trim_db` (default
  −70) that can be raised for SFX.

### S4 · bug · medium · Unison voices start out of phase and cancel
- **Actual:** `_tone` starts unison voice k at phase k/voices; `unison: 2` on sine/fm with a small detune starts near
  silent and swells in over ~1/(2·Δf) (≈165 ms at 5 cents on C6). Seen in sting_big, kill.
- **Proposal:** phase 0 for sine/fm (or deterministic pseudo-random phases), or a lint warning.

### S5 · friction · medium · W001 on short, peaky SFX: the advice doesn't help
- **Actual:** "give it more body" barely moved peak-to-loudness; what worked was staggering layer starts 3-9 ms
  and saturating noise layers. No per-layer peak/loudness readout (the agent wrote its own script on
  `sfxrender.render_layer`). Related: `variations.gain` shifts each variation's target, so +dB variations at the
  limiter cap always get W001 (undocumented).
- **Proposal:** `preview --json` per-layer `peak_db`, `lufs`, `crest_db`; W001 hint "stagger layer starts / reduce
  transient peaks"; document the variation-gain interaction.

### S6 · bug · low · Analysis numbers that disagree with the sheet
- `room_tail_s` is 0.0 in `preview --json` while the sheet header says "+0.21s room tail" (cannon, splash).
- `pitch_hz` reports phantom pitches on multi-partial SFX (difference tone of G6/C7 in `buy`; the thump under a bell).
- `centroid_hz` 7.7 kHz on a low-heavy sea ambience (linear centroid dominated by the noise floor; log/perceptual
  centroid would match the sheet).
- 6/8 at tempo 204: header "played from 0.999993 bar(s) later (bars 1.99999-26)" (float formatting).
- Piano roll names flats as sharps (Bb → A#) in D harmonic minor.

### S7 · bug · low · `preview --output stem:X` is half-done
- Sheet draws every track's roll, not just the stem's; header says "0 bar(s) later" (stem lacks `loop_offset`);
  no pitch_check; one `--output` per call, so each stem costs a full ~5 s re-render.
- **Proposal:** accept several `--output`s per call (render once), fix the header, filter the roll.

### S8 · friction · low · W009 clash lint too strict in compound meters and after decay
- 6/8 checks every eighth (meter unit) rather than the dotted-quarter beat; a sustain-0 bell held 16 steps is
  treated as sounding the whole gate. **Proposal:** beat = meter's beat (dotted quarter in 6/8), and count a note
  only while its envelope is above e.g. −30 dB.

### S9 · feature · low · SFX authoring gaps
- `variations.timing` (± s jitter on layer starts): bursts/bubbles land at the same moments in every variation.
- A sparse random-impulse source (crackle, debris, bubbles): `sink` needed 8 hand-placed bubble layers.
- Exponential decay option: (1−x)³ reaches zero exactly, bells stop dead (kill flatlines at 0.75 s).
- `pitch:` cents offsets (detuned copies need hand-computed Hz).
- `distort` is applied after layer `gain`, so gain changes timbre (contradicts "gain = balance"); narrow band-pass
  noise comes out ~15 dB quiet with no warning.

### S10 · doc · low · Small doc gaps
- Seamless SFX loops need `length:` past the loop end and keyframes that start/end on the same value.
- Unlisted loudness categories fall back to `sfx` for songs too (docs mention SFX only).
- `[loudness]` targets are limited to −40..−5 LUFS (a game's quiet hover tick sat at −45: needed a game-side offset).
- `segan lint` exits 1 with 0 errors when there are warnings (fine, but say so).
- Per-note release is impossible (a sting's last chord can't ring longer than the kit instrument's release).
- `segan.api`: no helper to dedupe/derive patterns, no way to emit comments.

### S11 · friction · low · `init --godot .` nests output inside PAGAN's output_dir
- **Repro:** game with `art/pagan.toml` `output_dir = "../assets/generated"`; `segan init sound --godot .` →
  `output_dir = "../assets/generated/audio"`. The template comment says to keep it apart from PAGAN's output, and
  PLAN §13 says init warns on a clash, but nesting isn't detected. **Proposal:** default `<godot>/assets/audio`,
  or detect a `pagan.toml` whose output_dir contains the chosen dir.

### S12 · bug · high · Looping song with an early-ending last note crashes the build
- **Repro:** a 2-bar song, `loop: main`, one short note per bar (last note ends well before the extra loop bar(s)).
  `segan build` → `ValueError: loop (88200, 264600) outside 0..214194` in `wavio.wav_bytes`.
- **Cause (as seen by the game developer):** `songrender.render_variant` sizes the buffer from the last sounding
  note, so `total` can be shorter than `file_end` (song + loop-offset bars).
- **Fix:** `total = max(total, file_end)`; golden test with a sparse looping song.

### S13 · feature · low · Manifest has no dry length for SFX
- Durations include the room tail (S3), so a voice pool that counts a voice busy for `seconds` holds it through an
  inaudible tail. **Proposal:** `dry_seconds` (or `tail_seconds`) per file entry.

### S14 · friction · low · Minimal `.import` sidecars cause a one-time diff
- SEGAN writes `.import` without `uid`/`dest_files`; Godot fills them on the first import, so the first commit after a
  build is followed by a second diff. Doesn't recur. **Proposal:** document it, or run/emit the full sidecar.

### Resolution (SEGAN maintainers, 2026-10-19)

Fixed on `main`; they ship in the next tag (v0.2.0).

- **S12** fixed: a looping song's buffer always reaches the file end (song + loop-offset bars), so sparse loops
  build. Test: `test_sparse_looping_song_renders_to_the_loop_end`.
- **S4** fixed: unison voices start within a quarter turn of each other (was k/voices: two voices in antiphase).
  Changes the sound of every `unison > 1` instrument; goldens updated.
- **S6** fixed: SFX `pitch_hz` (and the sheet's pitch dots) only count frames whose period has energy of its own
  (no phantom difference tones); `centroid_hz` is now the power-weighted log-frequency centroid (a noise floor no
  longer drags it up); the loop header rounds the bar offset; harmonic/melodic/pentatonic minor and blues
  spell flats like their relative major (D harmonic minor: Bb). Not reproduced: `room_tail_s` 0.0 vs. "+0.21s"
  on the sheet; both come from the same number, and cannon's tail really is below -70 dB inside its 0.85 s
  duration. Probably a sheet from an earlier edit; reopen with a repro if it recurs.
- **S7** fixed: `--output` repeats (one render for all), stems carry `loop_offset` (header right), the roll and
  `pitch_check` show only the stem's tracks.
- **S1** done: song `stems: { groups, mixes, main_mix }`. One WAV per group; stems normalised over the loudest
  listed mix; `preview --output mix:<name>`; main analysis has `stem_mixes_lufs`; manifest has
  `stems.<group>.tracks`, `stem_mixes` and `stems_normalised_over`; the Godot `.tres` lists the groups. E016.
- **S2** done: `stems.main_mix: false` (no full-mix WAV) and `variations.include_main: false` (no `<id>.wav`);
  those manifest entries have no `file`.
- **S3** done: `[room]` per-category send (`ui = 0`), SFX `room:` field, `[mix] tail_trim_db` (default -70).
- Docs: the variation-gain / W001 interaction (S5) and "unlisted categories fall back to `sfx` for songs too"
  (S10) are in the reference.

## From LOOSE! (2026-10-20, music pool on 0.2.0)
- Loop pools / playlists: LOOSE! now ships 16 battle + 6 menu 8-bar loops shuffled by the game. Metadata (mood, key/tempo family, intensity 0..1, level trim) travels as `tags: ["mood=battle", "family=d", ...]` the game parses. Wanted: a first-class `pool:` (members, families, weights, transition rules: crossfade inside a family, fade across) in the manifest.
- Stem mix levels: a bed-only mix can sit 13 dB under bed+drive (drums-only loops). Wanted: a per-mix loudness target or max gap between mixes.
- Size: no OGG/Vorbis output and no per-song sample rate / mono; 22 loops = 136 MB WAV (Godot QOA ~23 MB).
- W001 for percussive orchestral songs: songs had to move to a custom quieter category; a hint in W001 for songs would help.
