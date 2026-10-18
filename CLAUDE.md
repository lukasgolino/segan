# CLAUDE.md

SEGAN (Sound Effect Grammar And Notation) is PAGAN's sister library: a standalone Python CLI that translates
between AI and game audio. Agents write sound effects and music as palette-keyed YAML (instrument kits,
step grids, parametric SFX); SEGAN lints them, renders previews an agent can look at (listen sheets), and
builds engine assets (WAV, manifest.json, Godot). Read [PLAN.md](PLAN.md) for the brief, milestones and progress.
The reference implementation of every convention is PAGAN at `/home/lgolino/repos/PAGAN` (read-only).

## Setup and commands

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
segan --version          # or: python -m segan --version
mypy                     # strict type check (config in pyproject.toml)
pytest
```

CI (`.github/workflows/ci.yml`) runs install + mypy + pytest on Python 3.11-3.13 on every push/PR.

## Layout

- `src/segan/` — the package:
  - `cli.py` argparse commands; `findings.py` Finding/SeganError (rule ids, file:line output, JSON);
  - `yamlio.py` YAML loader (rejects duplicate keys, tracks line numbers via `LineMap`) — copied from PAGAN;
  - `buildinfo.py`, `progress.py` — copied from PAGAN; `settings.py` registry + TOML text edits — adapted from PAGAN;
  - `dsp.py` deterministic primitives (sin/exp2 tables, splitmix64 noise, PolyBLEP/BLAMP, biquads, decimator);
  - `notes.py` note names, keys, scales; `patch.py` instrument fields (shared by kits, inline instruments, SFX layers);
  - `kit.py` kit files; `synth.py` one note -> samples (oscillators, envelopes, filters, drum macros, oversampling);
  - `voices.py` note events -> track buffers (mono voice cuts, pan, note cache); `mix.py` shared bus (room, tone,
    crush, loudness normalisation, true-peak limiter); `analysis.py` LUFS/peaks/onsets/YIN/seam/aliasing;
  - `wavio.py` deterministic WAV with `smpl`/`cue ` chunks; `listen.py` listen sheets, seam view, gallery;
  - `kitshow.py` `segan kit show`; `project.py` segan.toml + discovery; `templates/` files `segan init` writes.
- `tests/fixtures/golden/` — golden project (22.05 kHz mono so files stay small); `expected/*.wav` are checked
  renders. After an intended rendering change, look at the output, then `SEGAN_UPDATE_GOLDEN=1 pytest tests/test_golden.py`.
- `examples/demo/` — the demo project (kits: nes, fm_soft, arcade_synth).

## Conventions

- Same as PAGAN's CLAUDE.md unless noted here: Python 3.11+, typed (mypy strict), small modules, every feature
  with tests, deterministic output, `--json`, all findings collected with rule id/file/line/where/fix hint.
- Modules copied from PAGAN say so in their docstring; port fixes between the two on purpose.
- Commits: plain `git commit` under the owner's identity, imperative subject. NEVER AI attribution (no
  Co-Authored-By trailers, no "Generated with" lines). Push to origin main is allowed (owner, 2026-10-19).
- Versioning as PAGAN: bump `version` in pyproject.toml, CHANGELOG.md entry (Keep a Changelog), tag `vX.Y.Z`
  for any change to the notation, segan.toml settings, manifest/exporter output or rendered samples.
- Open questions for the owner go in QUESTIONS.md with a recommended default; never block on them.
- Dependencies: numpy, scipy, Pillow, PyYAML; extra `mcp`; dev: pytest, mypy, types-PyYAML, mcp.

## Decisions log

- 2026-10-19: Name SEGAN, sister library of PAGAN, own repo `lukasgolino/segan` (public, like PAGAN). Covers SFX and music.
- 2026-10-19: scipy is a core dependency (approved by default per PLAN.md §14): IIR filters (`sosfilt`), polyphase
  decimation (`resample_poly`), FFT convolution for the room. PyPI name `segan` is free (checked 2026-10-19; not published).
- 2026-10-19: Determinism (PLAN.md §8): no `numpy.random` (noise = splitmix64 hash of the sample index); per-sample
  sin/exp2 from 4097-entry tables built with `math` and rounded to 12 decimals; envelopes are polynomials
  (attack linear, decay/release (1-x)^3); scalar coefficients rounded to 12 decimals. No dither (plain rounding to int16).
- 2026-10-19: Golden tests compare decoded samples within ±1 LSB (cross-machine ulp drift) plus a same-machine
  byte-identical rerun test, mirroring PAGAN's "pixels exact, bytes same-machine".
- 2026-10-19: Oscillators: PolyBLEP saw/pulse (pulse DC removed), PolyBLAMP triangle, table sine, 2-op FM (phase
  modulation), white noise and `bitnoise` (sample-and-hold at 16x the pitch: the NES/sfxr crunch). Decimation by a
  fixed Kaiser FIR (96 taps per factor, passband 0.9 x Nyquist) via `resample_poly`.
- 2026-10-19: Aliasing metric (W010): a steady tone of the instrument (modulation off) at its top note; energy away
  from the harmonics vs. on them (Blackman-Harris FFT; floor ~-88 dB). Measured at 2x: saw/pulse -50..-67 dB, 4x
  -67..-89. Default `oversample = 2` (plan), threshold `lint.max_aliasing_db = -50`. Noise and inharmonic FM skip it.
- 2026-10-19: Loudness: songs are measured integrated (BS.1770-4, exact K-weighting for any rate); SFX by their
  loudest 400 ms window (max momentary, zero-padded for short sounds), so a long tail doesn't push a one-shot up.
- 2026-10-19: `segan kit show` normalises the whole kit to the music target with ONE gain, so instrument levels
  stay as the kit's `gain` fields set them.
- 2026-10-19: WAV `smpl` loop end is inclusive (RIFF spec); manifest `loop.end` is exclusive (like Godot's loop_end).
- 2026-10-19: `[mix] crush = {bits, rate}` from the plan is flattened to `crush_bits` / `crush_rate` so
  `segan config set` can edit it (inline tables aren't settable values).

