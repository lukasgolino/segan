# QUESTIONS.md — for the owner

Open questions and decisions made by default while building SEGAN unattended (2026-10-19). Answer inline; the
agent's recommendation is listed first. Everything below already works with the default.

## Needs your ears (agents can't hear)

Everything is `status: draft`. Listen with `cd examples/demo && segan preview <name>` (WAVs land in
`examples/demo/previews/<name>/`), then `segan mark <name> --status approved`. The listen sheets and numbers were
checked (pitch, loudness on target, no clicks, seamless loops); taste was not.

1. **Kits** — `segan kit show` -> `previews/kits/{nes,fm_soft,arcade_synth}.wav`. Are the instruments distinct
   and pleasant? (M1 done-criterion: pick/tweak.) Watch: `fm_soft` `w` warm_pad is quiet; `nes` `b` triangle bass is loud.
2. **The 11 preset SFX** (coin, jump, laser, explosion, hit, hurt, powerup, blip, select, door, step): approve >= 8?
   (M2 done-criterion.) Most at risk: `explosion` (crunch + thump balance), `door` (creak timbre), `hurt`.
3. **Songs** — `overworld` (+ `danger`, `calm`), `combat` (+ `boss`), `shop` (made by a fresh agent from the skill
   alone): listenable? (M3 done-criterion.) Also `door_creak` (fresh agent).
4. **Godot demo** — run `segan build` in `examples/demo`, open `examples/godot`, press Play: loops seamless in-engine,
   the step randomizer cycles, stem sliders work? (CI verifies loading, loop points and that everything plays.)

## Decided by default (say if you disagree)

5. **scipy** is a core dependency (filters, decimation, LUFS, room). (Recommended: keep.)
6. **Samples/SoundFonts** — decided 2026-10-19 (owner): WAV + SFZ + SF2 readers; orchestral sounds from VSCO 2 CE
    (CC0) fetched on demand (nothing bundled); an orchestral kit and example project. Done in v0.2.0. Open: the
    orchestral example's balance and the VSCO maps need the owner's ear (`examples/orchestra`, `segan kit show`).

7. **44.1 kHz** default sample rate (48 kHz is one setting away). (Recommended: keep.)
8. **Golden tolerance**: ±1 LSB across machines, byte-identical on one machine. (Recommended: keep; CI agrees so far.)
9. **Demo WAVs aren't committed** (~40 MB per rebuild); manifest/.tres/.import are, and CI fails if a rebuild changes
   them. PLAN said "rebuild, fail on diff" (PAGAN commits its PNGs). (Recommended: keep; or commit WAVs via Git LFS.)
10. **Loop files are one bar longer than the song**: the loop points sit whole bars after the loop section's start so
    the loop's own tail rings into its start (no click, no double render). Manifest gives `loop.offset`.
    (Recommended: keep. Alternative: loop exactly at the section boundary with the tail wrapped around, which plays a
    "ghost" tail on the very first pass.)
11. **SFX loudness = loudest 400 ms (max momentary LUFS)**, songs = integrated. Added a `foley` category (-22 LUFS)
    because short footsteps can't reach -14 without crushing them. (Recommended: keep.)
12. **W001 redefined**: normalisation never limits more than 3 dB; W001 = "target out of reach" (the plan's "source
    too hot" is meaningless once everything is normalised). (Recommended: keep.)
13. **`[mix] crush = {bits, rate}` flattened** to `crush_bits` / `crush_rate` (so `config set` can edit them).
14. **AudioStreamInteractive not generated** (needs one WAV per section); the manifest's section offsets are the
    contract. (Recommended: add per-section exports + Interactive `.tres` when a game needs adaptive transitions.)
15. **Default oversample 2** (plan): saw/pulse aliasing -50..-67 dB at 2x, W010 above -50 dB tells you to go to 4x.
    (Recommended: keep; 4x doubles synth time.)
16. **No dither** (plain rounding to 16-bit). (Recommended: keep; synth output, normalised loud.)
17. **Release v0.1.0 tagged and pushed** (not published to PyPI; the name `segan` is free there).
    Publish to PyPI? (Recommended: later, together with PAGAN.)

## Setup (from the initial session)

18. **Public repo?** `lukasgolino/segan` was created public, like `lukasgolino/pagan`. (Recommended: keep public.)
19. **Name vs. scope**: "Sound Effect Grammar And Notation" also covers music. (Recommended: keep the name.)
