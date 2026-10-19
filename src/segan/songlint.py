"""Song warnings that come from the source alone: unused patterns/sections (W002), too many instruments
(W003), empty patterns (W004), clashes between tracks on strong beats (W009) and notes held longer than their
sample (W014)."""

from __future__ import annotations

from segan.findings import Finding
from segan.project import Project
from segan.song import Song, note_midi

CLASHES = {1: "minor 2nd", 6: "tritone"}


def lint_song_source(song: Song, project: Project) -> list[Finding]:
    found: list[Finding] = []
    path = song.path
    used_sections = set(song.arrangement)
    for name in song.sections:
        if name not in used_sections:
            found.append(Finding("W002", f"section {name!r} isn't in the arrangement: add it or delete it", path, None, f"sections.{name}"))
    used_patterns = {p for s in used_sections for p in song.sections.get(s, [])}
    sources = set()
    frontier = list(used_patterns)
    while frontier:
        pattern = song.patterns.get(frontier.pop())
        if pattern is not None and pattern.source and pattern.source not in sources:
            sources.add(pattern.source)
            frontier.append(pattern.source)
    for name, pattern in song.patterns.items():
        if name not in used_patterns and name not in sources:
            found.append(Finding("W002", f"pattern {name!r} isn't played (no section in the arrangement uses it, and no played pattern derives from it)", path, pattern.line, f"patterns.{name}"))
        if not pattern.notes:
            found.append(Finding("W004", f"pattern {name!r} has no notes", path, pattern.line, f"patterns.{name}"))
    keys = sorted(song.used_keys())
    limit = project.config.lint.max_instruments
    if len(keys) > limit:
        found.append(Finding("W003", f"the song uses {len(keys)} instruments ({' '.join(keys)}), more than lint.max_instruments ({limit}): "
                             "a smaller set keeps the sound consistent", path, None, "patterns"))  # fmt: skip
    found += _clashes(song)
    found += _short_samples(song)
    return found


def _short_samples(song: Song) -> list[Finding]:
    """W014: a held note on a sampled instrument outlasts its sample (no loop): it goes silent mid-note."""
    from segan.samples import load_set
    from segan.synth import VELOCITY_SCALE, is_one_shot

    out = []
    step_seconds = 60.0 / song.tempo / song.steps_per_beat
    for pattern in song.patterns.values():
        short: list[str] = []
        for n in pattern.notes:
            inst = song.kit.instruments.get(n.key)
            midi = note_midi(song, n) if not song.tracks[n.track].drums else (inst.note if inst else None)
            if inst is None or inst.sample is None or midi is None or is_one_shot(inst):
                continue
            vel = inst.sample.velocity or max(1, min(127, round(n.velocity * VELOCITY_SCALE)))
            for zone in load_set(inst.sample).pick(midi, vel, 0):
                if zone.loop is not None:
                    continue
                lasts = zone.seconds / 2.0 ** ((midi - zone.root) * zone.scale_tuning / 12.0)
                if n.length * step_seconds > lasts + 0.05:
                    short.append(f"{n.track} {song.key.name(midi)} at step {n.step + 1} ({n.length * step_seconds:.1f}s; the sample lasts {lasts:.1f}s)")
                    break
        if short:
            more = f" and {len(short) - 3} more" if len(short) > 3 else ""
            out.append(Finding("W014", f"pattern {pattern.name!r}: notes held longer than their sample (silent before they end): {'; '.join(short[:3])}{more}. "
                               "Shorten them, re-strike (two shorter notes), or use a sample with a loop", song.path, pattern.line, f"patterns.{pattern.name}"))  # fmt: skip
    return out


def _clashes(song: Song) -> list[Finding]:
    """Two roll notes on different tracks a minor 2nd (or 9th...) or a tritone apart, sounding together on a beat."""
    out = []
    for pattern in song.patterns.values():
        hits: list[str] = []
        roll = [n for n in pattern.notes if not song.tracks[n.track].drums]
        for step in range(0, pattern.length, song.steps_per_beat):
            sounding = [(n, note_midi(song, n)) for n in roll if n.step <= step < n.step + n.length]
            for i, (a, ma) in enumerate(sounding):
                for b, mb in sounding[i + 1 :]:
                    if a.track == b.track or ma is None or mb is None:
                        continue
                    interval = abs(ma - mb) % 12
                    if interval in CLASHES:
                        hits.append(f"step {step + 1} {a.track}/{b.track} {CLASHES[interval]} ({song.key.name(ma)}-{song.key.name(mb)})")
        if hits:
            more = f" and {len(hits) - 3} more" if len(hits) > 3 else ""
            out.append(Finding("W009", f"pattern {pattern.name!r}: tracks clash on the beat: {'; '.join(hits[:3])}{more}. Notes held from earlier count; the beats are steps 1, 1+steps_per_beat, ... "
                               "Often intended (a V7 chord's tritone, tension): then `lint: { disable: [W009] }`; if not, move or shorten one note", song.path, pattern.line, f"patterns.{pattern.name}"))  # fmt: skip
    return out
