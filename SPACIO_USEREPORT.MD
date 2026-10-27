# SEGAN use report: space-io (v0.13.0). Format: `YYYY-MM-DD · kind · what happened`.

- 2026-10-27 · request · pinned v0.13.0 into space-io `.venv`; `segan init audio --style synth --godot .` detected PAGAN's `assets/generated` and chose `../assets/audio` with a clear message. Smooth.
- 2026-10-27 · friction · `init --godot` leaves `[sfx] source = "auto"`, which may pick recordings for "weapons/impacts"; a retro synth game has to know to set `source = "synth"`. `--style synth` could imply it.
- 2026-10-27 · friction · SFX loudness = loudest 400 ms, so a 60 ms ui_click at the `ui` default (-20) peaked at -2.3 dBFS, as hot as the -14 LUFS explosion; 0.12 s lasers likewise. Had to drop ui to -28, laser -28, hover -33 by hand. Short sounds want a duration-aware measure or a peak/short-term readout in the gallery.
- 2026-10-27 · friction · band-pass noise with `resonance: 0.75` is still very wide on the sheet; a cutoff sweep on it barely shows. Hard to make a narrow "zip" whoosh; no Q/bandwidth in octaves.
- 2026-10-27 · bug · `pitch_hz` on a diving laser (E6→E5 square + triangle an octave below) reports start=end=min=max=355 Hz (only the last ~20 ms of the triangle body), so the JSON says "no pitch movement" while the sheet shows the dive.
- 2026-10-27 · doc · `preview --json` nests analysis several levels deep (outputs[].outputs[].analysis); fine, but a flat `--summary` table (asset, output, seconds, dry, LUFS, peak) would save a script every session.
- 2026-10-27 · friction · build writes `laser.wav` / `explosion.wav` (main) besides their variations although the game plays the randomizer: extra files in the repo (known from age-of-boom).
- 2026-10-27 · request · first Godot import rewrites every SEGAN `.import` (uid, dest_files); later `segan build` keeps them, so commit after one import. Rebuilds (also from a fresh clone, cache cleared) were byte-identical.
