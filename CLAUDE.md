# CLAUDE.md

SEGAN (Sound Effect Grammar And Notation) is PAGAN's sister library: a standalone Python CLI that translates
between AI and game audio. Agents write sound effects and music as palette-keyed YAML (instrument kits,
step grids, parametric SFX); SEGAN lints them, renders previews an agent can look at (listen sheets), and
builds engine assets (WAV, manifest.json, Godot). Read [PLAN.md](PLAN.md) for the brief, milestones and progress.
The reference implementation of every convention is PAGAN at `/home/lgolino/repos/PAGAN` (read-only).

## Conventions

- Same as PAGAN's CLAUDE.md unless noted here: Python 3.11+, typed (mypy strict), small modules, every feature
  with tests, deterministic output, `--json`, all findings collected with rule id/file/line/where/fix hint.
- Commits: plain `git commit` under the owner's identity, imperative subject. NEVER AI attribution (no
  Co-Authored-By trailers, no "Generated with" lines). Push to origin main is allowed (owner, 2026-10-19).
- Open questions for the owner go in QUESTIONS.md with a recommended default; never block on them.

## Decisions log

- 2026-10-19: Name SEGAN, sister library of PAGAN, own repo `lukasgolino/segan` (public, like PAGAN). Covers SFX and music.
