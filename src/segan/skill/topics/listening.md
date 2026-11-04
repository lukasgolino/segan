# Listening

You can't hear: the listen sheet and the numbers, in full.

## You can't hear. Read this first.

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
   recorded slightly sharp: its notes count as off only relative to that; `notes_skipped` and `skipped_because` say
   which notes couldn't be measured and why: very short notes, arpeggios, one-shots, chords),
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
