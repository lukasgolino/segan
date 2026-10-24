"""Project settings: one registry of every `segan.toml` setting (default, meaning, what it refreshes),
plus safe editing for `segan config set`.

Copied from PAGAN's settings.py (registry + comment-preserving TOML text edits); the settings are SEGAN's.
Settings are the project's saved, shared choices (room, loudness targets, sample rate...). Changing one
and rebuilding refreshes every asset it affects: [mix] changes re-render every song and SFX.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import Any, Literal

from segan.findings import Finding, SeganError
from segan.project import Config, Project, parse_config

Refresh = Literal["all", "build", "lint", "none"]


@dataclass(frozen=True)
class Setting:
    key: str  # dotted: "mix.room"
    default: Any
    meaning: str
    refresh: Refresh  # what changes when this setting changes

    @property
    def table(self) -> str | None:
        return self.key.split(".")[0] if "." in self.key else None

    @property
    def name(self) -> str:
        return self.key.split(".")[-1]


SETTINGS: tuple[Setting, ...] = (
    Setting("mode", "strict", '"strict": songs and SFX use kit files only; "open": inline instruments allowed', "lint"),
    Setting("default_kit", None, "kit for songs and SFX that don't name one; switching it re-voices all of them", "all"),
    Setting("output_dir", "build/audio", "where `segan build` writes final assets (e.g. a game engine's audio folder; keep it apart from PAGAN's)", "build"),
    Setting("preview_dir", "previews", "scratch folder for previews and listen sheets", "none"),
    Setting("export", ["wav"], 'build outputs: "wav" (WAVs + manifest.json, always), "godot" (.import loop/compression edits + AudioStreamRandomizer/Synchronized .tres), "stems" (one WAV per song track), "ogg" (music as Ogg Vorbis instead of WAV; SFX stay WAV; needs segan[ogg])', "build"),
    Setting("seed", None, "the project seed (`segan init` picks one at random): `segan suggest` and `segan kit roll` branch from it, so two projects with the same brief start from different places", "none"),
    Setting("style_version", 1, "current sound style version; assets made under older ones get W006 (use `segan style bump`)", "lint"),
    Setting("mix.sample_rate", 44100, "output sample rate (Hz): 44100 (Godot's default mix rate) or 48000", "all"),
    Setting("mix.oversample", 2, "synthesis runs at N x the sample rate and is filtered down (anti-aliasing): 1, 2, 4 or 8", "all"),
    Setting("mix.music_channels", "stereo", "songs: stereo (tracks can pan) or mono", "all"),
    Setting("mix.sfx_channels", "mono", "SFX: mono (engines pan them in 2D/3D) or stereo", "all"),
    Setting("mix.tuning", 440.0, "pitch of A4 in Hz", "all"),
    Setting("mix.room", 0.15, "shared reverb amount, 0 = dry; the same space for every asset", "all"),
    Setting("mix.room_decay", 0.6, "how long the room rings (seconds to fall 60 dB)", "all"),
    Setting("mix.crush_bits", 0, "project-wide bit crush (0 = off; e.g. 8 for a lo-fi era sound)", "all"),
    Setting("mix.crush_rate", 0.0, "project-wide sample-rate crush in Hz (0 = off; e.g. 11025)", "all"),
    Setting("mix.declick", True, "micro-fades at note edges (true) or raw, clicky chip edges (false)", "all"),
    Setting("mix.limiter", -1.0, "true-peak ceiling in dBFS for every output", "all"),
    Setting("mix.brightness", 0.0, "tilt EQ in dB: + brighter, - darker (every asset)", "all"),
    Setting("mix.warmth", 0.0, "low-mid body in dB: + warmer (and a softer top), - thinner", "all"),
    Setting("mix.tail_trim_db", -70.0, "where an SFX's (or one-shot song's) room tail is cut, in dB below its peak (-40 = shorter files)", "all"),
    Setting("loudness.music", -16.0, "loudness target for songs (integrated LUFS)", "all"),
    Setting("loudness.sfx", -14.0, "loudness target for SFX (loudest 400 ms, LUFS); any category not listed uses this", "all"),
    Setting("loudness.ui", -20.0, "loudness target for SFX with category ui", "all"),
    Setting("loudness.foley", -22.0, "loudness target for SFX with category foley (footsteps, handling: frequent, so quieter)", "all"),
    Setting("lint.disable", [], "warning ids to turn off", "lint"),
    Setting("lint.max_seam_click", 0.02, "W007: largest click allowed at a loop point (fraction of full scale)", "lint"),
    Setting("lint.max_leading_silence_ms", 5.0, "W005: most silence before an SFX starts (it adds input latency)", "lint"),
    Setting("lint.max_instruments", 8, "W003: most kit instruments one song may use", "lint"),
    Setting("lint.max_aliasing_db", -50.0, "W010: most aliasing energy (dB below the tone) an instrument may make", "lint"),
    Setting("lint.max_limiting_db", 3.0, "W001: most gain reduction the limiter may apply before the source counts as too hot", "lint"),
    Setting("lint.max_dc_offset", 0.01, "W008: largest DC offset (fraction of full scale)", "lint"),
    Setting("lint.loudness_tolerance", 1.0, "W013: how far (LU) an un-normalised asset may be from its target", "lint"),
    Setting("lint.max_similarity", 0.85, "W024-W026: how alike (0-1) two songs' first bars may be before lint says so", "lint"),
    Setting("similarity.local_store", False, "keep this project's song fingerprints in the user cache (~/.cache/segan/fingerprints) and warn (W026) when a song is close to one from another project on this machine", "lint"),
    Setting("similarity.shipped", True, "warn (W025) when a song is close to one of SEGAN's own examples (off only in those examples)", "lint"),
    Setting("godot.compress", "qoa", 'how Godot compresses imported WAVs: "qoa" (default, good), "ima" (IMA-ADPCM), "none"', "build"),
    Setting("sfx.source", "auto", 'where SFX sounds come from: "auto" (synthesise stylised sounds, record real-world ones; see the skill), "synth" (no recordings: W020 on recorded layers), "recorded" (prefer recordings)', "lint"),
    Setting("ogg.quality", 0.4, 'Vorbis quality 0-1 for export "ogg" (0.4 is about 128 kbit/s stereo, 10x smaller than WAV)', "build"),
)
BY_KEY = {s.key: s for s in SETTINGS}


def lookup(key: str) -> Setting | None:
    """A registered setting, or an extra loudness category (`loudness.<category>`)."""
    if key in BY_KEY:
        return BY_KEY[key]
    if re.fullmatch(r"loudness\.[a-z][a-z0-9_]*", key):
        return Setting(key, None, f"loudness target for SFX with category {key.split('.')[1]}", "all")
    if re.fullmatch(r"room\.[a-z][a-z0-9_]*", key):
        return Setting(key, None, f"room send (0-1, x mix.room; 0 = dry, no tail) for assets with category {key.split('.')[1]}", "all")
    return None


def current_value(config: Config, key: str) -> Any:
    table, _, name = key.rpartition(".")
    if table == "loudness":
        return config.loudness.get(name)
    if table == "room":
        return config.room.get(name)
    source: Any = getattr(config, table) if table else config
    value = getattr(source, name)
    if isinstance(value, tuple):
        return list(value)
    return value


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise ValueError(f"can't write {value!r} to TOML")


def parse_value(text: str) -> Any:
    """Parse a command-line value as TOML (`42`, `true`, `[1, 2]`, `"x"`); bare words become strings."""
    try:
        value = tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text
    # Dates, times and inline tables aren't setting values: treat the text as a plain string.
    return value if isinstance(value, bool | int | float | str | list) else text


def _split_comment(line: str) -> tuple[str, str]:
    """Split a TOML line into code and trailing comment (ignoring # inside strings)."""
    quote: str | None = None
    for i, char in enumerate(line):
        if quote:
            if char == "\\" and quote == '"':
                continue
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return line[:i], line[i:]
    return line, ""


def _bracket_depth(code: str) -> int:
    depth, quote = 0, None
    for char in code:
        if quote:
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(table name, first line, end line) for the root ("") and every [table]."""
    found: list[tuple[str, int, int]] = []
    name, start = "", 0
    for i, line in enumerate(lines):
        header = re.match(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$", line)
        if header:
            found.append((name, start, i))
            name, start = header.group(1).strip(), i + 1
    found.append((name, start, len(lines)))
    return found


def set_in_toml(text: str, key: str, value: Any) -> str:
    """Set a (possibly dotted) key in TOML text, keeping layout and comments.

    Replaces an existing value (also one spread over several lines), else a commented-out
    `# key = ...` template line, else adds the key at the end of its table (creating the table).
    """
    return _edit_toml(text, key, f"{key.rpartition('.')[2]} = {toml_value(value)}")


def remove_from_toml(text: str, key: str) -> str:
    """Comment out a key so its default applies again (the line stays as a template)."""
    return _edit_toml(text, key, None)


def _edit_toml(text: str, key: str, entry: str | None) -> str:
    table, _, name = key.rpartition(".")
    lines = text.split("\n")
    section = next((sec for sec in _sections(lines) if sec[0] == table), None)
    if section is not None:
        _, first, end = section
        for i in range(first, end):
            code, comment = _split_comment(lines[i])
            match = re.match(rf"^(\s*){re.escape(name)}\s*=", code)
            if not match:
                continue
            last = i
            while _bracket_depth("".join(_split_comment(l)[0] for l in lines[i : last + 1])) > 0 and last + 1 < end:
                last += 1  # a value spread over several lines
            if entry is None:
                replacement = [f"{match.group(1)}# {name} = {code.split('=', 1)[1].strip()}"] if last == i else []
                lines[i : last + 1] = replacement
            else:
                gap = code[len(code.rstrip()) :] if last == i else ""
                lines[i : last + 1] = [f"{match.group(1)}{entry}{gap}{comment if last == i else ''}"]
            return "\n".join(lines)
        if entry is None:
            return text
        for i in range(first, end):  # a commented-out template line: `# default_kit = "my_kit"`
            template = re.match(rf"^(\s*)#\s*{re.escape(name)}\s*=", lines[i])
            if template:
                lines[i] = f"{template.group(1)}{entry}"
                return "\n".join(lines)
        insert = end
        while insert > first and (not lines[insert - 1].strip() or lines[insert - 1].lstrip().startswith("#")):
            insert -= 1  # after the table's last setting, before trailing blanks/comments of the next table
        lines.insert(insert, entry)
        return "\n".join(lines)
    if entry is None:
        return text
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}\n[{table}]\n{entry}\n"


@dataclass
class Change:
    key: str
    old: Any
    new: Any
    refresh: Refresh


def set_setting(project: Project, key: str, raw_value: str) -> Change:
    """Validate and save a setting; raises SeganError (and changes nothing) if the result is invalid."""
    if project.config_path is None:
        raise SeganError([Finding("E000", "no segan.toml found; run `segan init` first")])
    setting = lookup(key)
    if setting is None:
        raise SeganError([Finding("E000", f"unknown setting {key!r}; see `segan config show`")])
    value = parse_value(raw_value)
    if isinstance(setting.default, list) and isinstance(value, str):
        # Lists can also be written comma-separated: png,godot  ->  ["png", "godot"]
        value = [parse_value(part.strip()) for part in value.split(",") if part.strip()]
    text = project.config_path.read_text(encoding="utf-8")
    updated = set_in_toml(text, key, value)
    try:
        data = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise SeganError([Finding("E001", f"that value doesn't make valid TOML: {exc}", project.config_path)]) from None
    try:
        new_config = parse_config(data, project.config_path)  # raises with a precise message if invalid
    except SeganError as exc:
        example = toml_value(setting.default if setting.default is not None else "name")
        hint = f" (value syntax is TOML, e.g. segan config set {key} '{example}')"
        raise SeganError([Finding(f.rule, f.message + hint, f.path, f.line, f.where) for f in exc.findings]) from None
    if key == "default_kit" and value is not None and not project.kit_path(str(value)).is_file():
        known = ", ".join(project.kit_names()) or "none"
        raise SeganError([Finding("E005", f"no kit {value!r} (kits: {known})", project.config_path)])
    old = current_value(project.config, key)
    project.config_path.write_text(updated, encoding="utf-8")
    return Change(key, old, current_value(new_config, key), setting.refresh)


def unset_setting(project: Project, key: str) -> Change:
    """Return a setting to its default by commenting it out of segan.toml."""
    if project.config_path is None:
        raise SeganError([Finding("E000", "no segan.toml found; run `segan init` first")])
    setting = lookup(key)
    if setting is None:
        raise SeganError([Finding("E000", f"unknown setting {key!r}; see `segan config show`")])
    updated = remove_from_toml(project.config_path.read_text(encoding="utf-8"), key)
    new_config = parse_config(tomllib.loads(updated), project.config_path)
    old = current_value(project.config, key)
    project.config_path.write_text(updated, encoding="utf-8")
    return Change(key, old, current_value(new_config, key), setting.refresh)


def describe(config: Config) -> list[dict[str, Any]]:
    extra = [lookup(f"loudness.{c}") for c in sorted(config.loudness) if f"loudness.{c}" not in BY_KEY]
    extra += [lookup(f"room.{c}") for c in sorted(config.room)]
    return [
        {
            "key": s.key,
            "value": current_value(config, s.key),
            "default": s.default,
            "is_default": current_value(config, s.key) == s.default,
            "meaning": s.meaning,
            "refreshes": s.refresh,
        }
        for s in (*SETTINGS, *(e for e in extra if e is not None))
    ]

