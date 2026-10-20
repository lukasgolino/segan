"""Soundtracks (`music/<name>.soundtrack.yaml`): which songs a game plays in which state, and how it moves between
states. The director (`segan_music.gd`) plays them; SEGAN checks them (E018, W016) and puts them in the manifest.

```yaml
name: main
start: explore
states:
  explore: { songs: { overworld: 2, village: 1 }, play: [120, 240], gap: [10, 40], fade_out: 3, crossfade: 4 }
  combat: { songs: [combat, overworld.danger] }
families:                          # songs that cross-fade into each other in a state (others fade out, gap, start)
  a_minor: [overworld, village]
transitions:                       # "from>to", "from>*", "*>to", "*" (most specific wins)
  "*": { at: bar, fade: 2 }
  explore>combat: { at: beat, fade: 0.5, stinger: hit, start: main }
```
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from segan.asset import load_source
from segan.findings import Finding, SeganError
from segan.kit import NAME_RE
from segan.notes import Key, transpose_key
from segan.patch import Report, is_number, line_of
from segan.yamlio import LineMap

SOUNDTRACK_SUFFIX = ".soundtrack.yaml"
FIELDS = ("name", "description", "start", "states", "transitions", "families")
STATE_FIELDS = ("songs", "play", "gap", "fade_out", "crossfade")
TRANSITION_FIELDS = ("at", "fade", "fade_in", "stinger", "start")
SYNC_POINTS = ("now", "beat", "bar", "section", "end")
DEFAULT_TRANSITION = {"at": "bar", "fade": 2.0, "fade_in": 0.0, "stinger": None, "start": None}
DEFAULT_PLAY = (120.0, 240.0)
STATE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class SongRef:
    song: str
    variant: str | None
    weight: float

    @property
    def label(self) -> str:
        return f"{self.song}.{self.variant}" if self.variant else self.song


@dataclass(frozen=True)
class State:
    name: str
    songs: tuple[SongRef, ...]
    play: tuple[float, float] | None  # seconds a song plays before it ends; None = until the state changes
    gap: tuple[float, float]  # seconds of silence between songs
    fade_out: float  # how a looping song ends when its play time is up
    crossfade: float = 0.0  # seconds the next song overlaps the last when both are in one family (no gap)
    line: int | None = None


@dataclass(frozen=True)
class Transition:
    at: str
    fade: float
    fade_in: float
    stinger: str | None
    start: str | None
    line: int | None = None


@dataclass
class Soundtrack:
    name: str
    path: Path | None
    description: str | None
    start: str
    states: dict[str, State]
    transitions: dict[str, Transition] = field(default_factory=dict)  # "from>to" with "*" wildcards, or "*"
    families: dict[str, tuple[str, ...]] = field(default_factory=dict)  # family -> song labels ("song" or "song.variant")
    families_line: int | None = None

    def family(self, ref: SongRef) -> str:
        """The family listing this song (`song`, or `song.variant` for a variant), else its own label."""
        return next((name for name, members in self.families.items() if ref.label in members), ref.label)

    def transition(self, src: str, dst: str) -> Transition:
        """The rule for src -> dst: "src>dst", then "src>*", "*>dst", "*", then the default."""
        for key in (f"{src}>{dst}", f"{src}>*", f"*>{dst}", "*"):
            if key in self.transitions:
                return self.transitions[key]
        return Transition(**DEFAULT_TRANSITION)  # type: ignore[arg-type]

    def manifest(self) -> dict[str, Any]:
        def range_or_none(r: tuple[float, float] | None) -> list[float] | None:
            return [r[0], r[1]] if r is not None else None

        return {
            "description": self.description,
            "start": self.start,
            "states": {s.name: {"songs": [{"song": r.song, "variant": r.variant, "weight": r.weight, "family": self.family(r)} for r in s.songs],
                                "play": range_or_none(s.play), "gap": [s.gap[0], s.gap[1]], "fade_out": s.fade_out, "crossfade": s.crossfade}
                       for s in self.states.values()},  # fmt: skip
            "families": {name: list(members) for name, members in self.families.items()},
            "transitions": {k: {"at": t.at, "fade": t.fade, "fade_in": t.fade_in, "stinger": t.stinger, "start": t.start} for k, t in self.transitions.items()},
            "default_transition": dict(DEFAULT_TRANSITION),
        }


def soundtrack_name(path: Path) -> str | None:
    return path.name[: -len(SOUNDTRACK_SUFFIX)] if path.name.endswith(SOUNDTRACK_SUFFIX) else None


def _range(value: Any, lo: float, hi: float) -> tuple[float, float] | None:
    """`30` or `[10, 40]` (seconds) -> (min, max)."""
    if is_number(value):
        value = [value, value]
    if isinstance(value, list) and len(value) == 2 and all(is_number(v) and lo <= v <= hi for v in value) and value[0] <= value[1]:
        return float(value[0]), float(value[1])
    return None


def parse_soundtrack(data: dict[str, Any], path: Path | None) -> tuple[Soundtrack | None, list[Finding]]:
    """E018: the file's own structure (references to songs and SFX are checked by `check_soundtrack`)."""
    report = Report(path)
    line = data.line if isinstance(data, LineMap) else None

    def bad(message: str, at: int | None, where: str) -> None:
        report.error("E018", message, at, where)

    for k in data:
        if k not in FIELDS:
            bad(f"unknown soundtrack field {k!r}; allowed: {', '.join(FIELDS)}", line_of(data, k, line), str(k))
    expected = soundtrack_name(path) if path is not None else None
    name = data.get("name", expected)
    if not isinstance(name, str) or not NAME_RE.match(name) or (expected is not None and name != expected):
        bad(f"name must be lowercase letters, digits, '_' or '-' and match the file name ({expected})", line_of(data, "name", line), "name")
        name = expected or "unnamed"
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        bad("description must be text", line_of(data, "description", line), "description")
        description = None
    states: dict[str, State] = {}
    raw_states = data.get("states")
    sline = line_of(data, "states", line)
    if not isinstance(raw_states, dict) or not raw_states:
        bad("states must map game states to songs, e.g. explore: { songs: [overworld, village] }", sline, "states")
        raw_states = {}
    for sname, raw in raw_states.items():
        where, at = f"states.{sname}", line_of(raw_states, sname, sline)
        if not isinstance(sname, str) or not STATE_RE.match(sname):
            bad(f"state name {sname!r} must be lowercase letters, digits or '_'", at, where)
            continue
        if isinstance(raw, list):
            raw = {"songs": raw}
        if not isinstance(raw, dict) or any(k not in STATE_FIELDS for k in raw):
            bad(f"state {sname!r} must be a list of songs or a mapping of {', '.join(STATE_FIELDS)}", at, where)
            continue
        songs = raw.get("songs")
        weights = {s: 1 for s in songs} if isinstance(songs, list) else songs
        if not isinstance(weights, dict) or not weights or not all(isinstance(s, str) and is_number(w) and w > 0 for s, w in weights.items()):
            bad(f"state {sname!r}: songs must list songs ([overworld, village]) or weight them ({{ overworld: 2, village: 1 }}); "
                "`song.variant` picks a variant", at, f"{where}.songs")  # fmt: skip
            continue
        if isinstance(songs, list) and len(set(songs)) != len(songs):
            bad(f"state {sname!r} lists a song twice (use weights to make one likelier)", at, f"{where}.songs")
            continue
        refs = tuple(SongRef(s.split(".", 1)[0], s.split(".", 1)[1] if "." in s else None, float(w)) for s, w in weights.items())
        gap = _range(raw.get("gap", 0), 0, 3600)
        if gap is None:
            bad(f"state {sname!r}: gap must be seconds of silence between songs, a number or [min, max] (0-3600)", at, f"{where}.gap")
            continue
        if "play" in raw:
            play = _range(raw["play"], 1, 7200)
            if play is None:
                bad(f"state {sname!r}: play must be how long a song plays before the next, in seconds: a number or [min, max] (1-7200)", at, f"{where}.play")
                continue
        else:
            play = None if len(refs) == 1 and gap == (0.0, 0.0) else DEFAULT_PLAY
        fade_out = raw.get("fade_out", 3.0)
        if not (is_number(fade_out) and 0 <= fade_out <= 60):
            bad(f"state {sname!r}: fade_out must be 0-60 seconds", at, f"{where}.fade_out")
            continue
        crossfade = raw.get("crossfade", 0.0)
        if not (is_number(crossfade) and 0 <= crossfade <= 60):
            bad(f"state {sname!r}: crossfade must be 0-60 seconds (how long the next song overlaps the last when both are in one family)", at, f"{where}.crossfade")
            continue
        states[sname] = State(sname, refs, play, gap, float(fade_out), float(crossfade), at)
    start = data.get("start", next(iter(raw_states), None))
    if not isinstance(start, str) or (raw_states and start not in raw_states):
        bad(f"start must be one of the states ({', '.join(map(str, raw_states))})", line_of(data, "start", line), "start")
        start = ""
    transitions: dict[str, Transition] = {}
    raw_transitions = data.get("transitions", {})
    tline = line_of(data, "transitions", line)
    if not isinstance(raw_transitions, dict):
        bad('transitions must map "from>to" (or "*" wildcards) to { at, fade, fade_in, stinger, start }', tline, "transitions")
        raw_transitions = {}
    for key, raw in raw_transitions.items():
        where, at = f"transitions.{key}", line_of(raw_transitions, key, tline)
        ends = str(key).split(">") if key != "*" else ["*", "*"]
        if len(ends) != 2 or not all(e == "*" or e in raw_states for e in ends):
            bad(f'transition {key!r} must be "from>to" with state names or "*" (states: {", ".join(map(str, raw_states))})', at, where)
            continue
        if not isinstance(raw, dict) or any(k not in TRANSITION_FIELDS for k in raw):
            bad(f"transition {key!r} must be a mapping of {', '.join(TRANSITION_FIELDS)}", at, where)
            continue
        sync = raw.get("at", DEFAULT_TRANSITION["at"])
        fade, fade_in = raw.get("fade", DEFAULT_TRANSITION["fade"]), raw.get("fade_in", 0.0)
        stinger, first = raw.get("stinger"), raw.get("start")
        if sync not in SYNC_POINTS:
            bad(f"transition {key!r}: at must be one of {', '.join(SYNC_POINTS)} (when the switch happens)", at, f"{where}.at")
        elif not (is_number(fade) and 0 <= fade <= 60 and is_number(fade_in) and 0 <= fade_in <= 60):
            bad(f"transition {key!r}: fade (the old song out) and fade_in (the new one in) must be 0-60 seconds", at, where)
        elif stinger is not None and not (isinstance(stinger, str) and NAME_RE.match(stinger)):
            bad(f"transition {key!r}: stinger must be the name of an SFX", at, f"{where}.stinger")
        elif first is not None and not (isinstance(first, str) and STATE_RE.match(first)):
            bad(f"transition {key!r}: start must be a section name", at, f"{where}.start")
        else:
            transitions["*" if ends == ["*", "*"] else str(key)] = Transition(str(sync), float(fade), float(fade_in), stinger, first, at)
    families: dict[str, tuple[str, ...]] = {}
    raw_families = data.get("families", {})
    fline = line_of(data, "families", line)
    owner: dict[str, str] = {}
    if not isinstance(raw_families, dict):
        bad("families must map family names to songs, e.g. d_minor: [dungeon, overworld.calm]", fline, "families")
        raw_families = {}
    for fname, members in raw_families.items():
        where, at = f"families.{fname}", line_of(raw_families, fname, fline)
        if not isinstance(fname, str) or not STATE_RE.match(fname):
            bad(f"family name {fname!r} must be lowercase letters, digits or '_'", at, where)
        elif not isinstance(members, list) or not members or not all(isinstance(m, str) for m in members) or len(set(members)) != len(members):
            bad(f"family {fname!r} must list songs once each (`song` or `song.variant`), e.g. [dungeon, overworld.calm]", at, where)
        elif twice := [m for m in members if m in owner]:
            bad(f"family {fname!r}: {', '.join(twice)} already in family {owner[twice[0]]!r} (a song is in one family)", at, where)
        else:
            owner.update(dict.fromkeys(members, fname))
            families[fname] = tuple(members)
    if report.failed:
        return None, report.findings
    return Soundtrack(name, path, description, start, states, transitions, families, fline), report.findings


def load_soundtrack(path: Path) -> tuple[Soundtrack | None, list[Finding]]:
    try:
        data = load_source(path)
    except SeganError as exc:
        return None, exc.findings
    return parse_soundtrack(data, path)


def song_key(song: Any, variant: str | None) -> Key:
    """The key a song (or one of its variants) is in."""
    key: Key = song.key
    v = song.all_variants().get(variant) if variant else None
    if v is not None:
        key = v.key or key
        if v.semitones:
            key = transpose_key(key, v.semitones)
    return key


def keys_clash(a: Key, b: Key) -> bool:
    """Two keys clash in a cross-fade unless their notes nearly agree: the same key, relative keys, or a fifth
    apart (all but one note shared)."""
    pa = {(a.root + i) % 12 for i in a.intervals}
    pb = {(b.root + i) % 12 for i in b.intervals}
    return len(pa & pb) < min(len(pa), len(pb)) - 1


def check_soundtrack(st: Soundtrack, songs: dict[str, Any], sfx: set[str]) -> list[Finding]:
    """E018: songs, variants, stingers and start sections exist. W016: a cross-fade between clashing keys."""
    out: list[Finding] = []
    for state in st.states.values():
        for ref in state.songs:
            song = songs.get(ref.song)
            if song is None:
                out.append(Finding("E018", f"state {state.name!r}: no song {ref.song!r} (songs: {', '.join(sorted(songs)) or 'none'})", st.path, state.line, f"states.{state.name}.songs"))
            elif ref.variant and ref.variant not in song.all_variants():
                out.append(Finding("E018", f"state {state.name!r}: song {ref.song!r} has no variant {ref.variant!r} (variants: {', '.join(song.all_variants()) or 'none'})",
                                   st.path, state.line, f"states.{state.name}.songs"))  # fmt: skip
    for fname, members in st.families.items():
        for label in members:
            ref = SongRef(label.split(".", 1)[0], label.split(".", 1)[1] if "." in label else None, 1.0)
            song = songs.get(ref.song)
            if song is None or (ref.variant and ref.variant not in song.all_variants()):
                out.append(Finding("E018", f"family {fname!r}: no song {label!r} (songs: {', '.join(sorted(songs)) or 'none'}; `song.variant` for a variant)",
                                   st.path, st.families_line, f"families.{fname}"))  # fmt: skip
    if out:
        return out
    for key, t in st.transitions.items():
        where = f"transitions.{key}"
        if t.stinger is not None and t.stinger not in sfx:
            out.append(Finding("E018", f"transition {key!r}: stinger {t.stinger!r} isn't an SFX (SFX: {', '.join(sorted(sfx)) or 'none'})", st.path, t.line, f"{where}.stinger"))
        targets = [s for s in st.states.values() if key == "*" or key.split(">")[1] in ("*", s.name)]
        if t.start is not None:
            for state in targets:
                for ref in state.songs:
                    song = songs[ref.song]
                    if t.start not in song.played_sections():
                        out.append(Finding("E018", f"transition {key!r}: start section {t.start!r} isn't played by {ref.song!r} (state {state.name!r}; "
                                           f"sections: {', '.join(song.played_sections())})", st.path, t.line, f"{where}.start"))  # fmt: skip
    for src in st.states.values():
        for dst in st.states.values():
            t = st.transition(src.name, dst.name)
            if src.name == dst.name or t.fade <= 0 or t.at == "end":
                continue
            for a in src.songs:
                for b in dst.songs:
                    ka, kb = song_key(songs[a.song], a.variant), song_key(songs[b.song], b.variant)
                    if keys_clash(ka, kb):
                        out.append(Finding("W016", f"{src.name}>{dst.name} cross-fades {a.label} ({ka.describe()}) into {b.label} ({kb.describe()}) for "
                                           f"{t.fade:g}s: the keys clash while both sound. Shorten the fade (or fade: 0 with a stinger), switch at: end, "
                                           "or use a variant in a related key", st.path, t.line, f"transitions.{src.name}>{dst.name}"))  # fmt: skip
    for state in st.states.values():
        if state.crossfade <= 0:
            continue
        for i, a in enumerate(state.songs):
            for b in state.songs[i + 1 :]:
                ka, kb = song_key(songs[a.song], a.variant), song_key(songs[b.song], b.variant)
                if st.family(a) == st.family(b) and keys_clash(ka, kb):
                    out.append(Finding("W016", f"state {state.name!r} cross-fades {a.label} ({ka.describe()}) and {b.label} ({kb.describe()}) for {state.crossfade:g}s "
                                       f"(both in family {st.family(a)!r}): the keys clash while both sound. Put them in different families", st.path,
                                       st.families_line or state.line, f"states.{state.name}.crossfade"))  # fmt: skip
    return list(dict.fromkeys(out))
