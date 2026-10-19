"""Song warnings that come from the source alone: unused patterns/sections (W002), too many instruments
(W003), empty patterns (W004) and clashes between tracks on strong beats (W009)."""

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
    return found


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
