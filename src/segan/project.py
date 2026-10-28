"""SEGAN projects: a directory with a segan.toml plus kits/, music/ and sfx/.

Adapted from PAGAN's project.py (discovery by walking up to the config file, open mode without one,
unknown keys are errors); the config sections are SEGAN's own.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from segan.findings import Finding, SeganError
from segan.kit import KIT_SUFFIX, NAME_RE, Kit, load_kit_file

CONFIG_NAME = "segan.toml"
MODES = ("strict", "open")
EXPORTERS = ("wav", "godot", "stems", "ogg", "web")
SAMPLE_RATES = (22050, 32000, 44100, 48000)
OVERSAMPLE = (1, 2, 4, 8)
MIN_TARGET_LUFS = -60.0  # quietest [loudness] target (a hover tick can sit at -45)
CHANNELS = ("mono", "stereo")
GODOT_COMPRESS = ("none", "ima", "qoa")
DEFAULT_LOUDNESS = {"music": -16.0, "sfx": -14.0, "ui": -20.0, "foley": -22.0}
SHORT_SFX = ("window", "duration")  # [loudness] short_sfx: how one-shots shorter than 400 ms are measured

Mode = Literal["strict", "open"]


@dataclass(frozen=True)
class MixConfig:
    sample_rate: int = 44100
    oversample: int = 2
    music_channels: str = "stereo"
    sfx_channels: str = "mono"
    tuning: float = 440.0
    room: float = 0.15
    room_decay: float = 0.6
    crush_bits: int = 0
    crush_rate: float = 0.0
    declick: bool = True
    limiter: float = -1.0
    brightness: float = 0.0
    warmth: float = 0.0
    tail_trim_db: float = -70.0  # the room tail is cut where it falls this far below the peak


@dataclass(frozen=True)
class LintConfig:
    disable: tuple[str, ...] = ()
    max_seam_click: float = 0.02  # W007
    max_leading_silence_ms: float = 5.0  # W005
    max_instruments: int = 8  # W003
    max_aliasing_db: float = -50.0  # W010
    max_limiting_db: float = 3.0  # W001
    max_dc_offset: float = 0.01  # W008
    loudness_tolerance: float = 1.0  # W013
    max_similarity: float = 0.85  # W024-W026: how alike two songs' first bars may be
    category_disable: dict[str, tuple[str, ...]] = field(default_factory=dict)  # [lint.<category>] disable: warnings off for that category

    def disabled_for(self, category: str | None) -> frozenset[str]:
        """Warnings off for an asset of `category` (its own `lint: disable` comes on top)."""
        return frozenset(self.category_disable.get(category or "", ()))


@dataclass(frozen=True)
class GodotConfig:
    compress: str = "qoa"


SFX_SOURCES = ("auto", "synth", "recorded")


@dataclass(frozen=True)
class SfxConfig:
    source: str = "auto"  # auto: synthesise stylised sounds, record real-world ones; synth: no recordings; recorded: prefer recordings


@dataclass(frozen=True)
class SoundsConfig:
    extra_licences: tuple[str, ...] = ()  # non-CC licences this project has cleared (royalty-free libraries)


@dataclass(frozen=True)
class SimilarityConfig:
    local_store: bool = False  # keep song fingerprints in the user cache and compare with other projects (W026)
    shipped: bool = True  # compare songs with SEGAN's own examples (W025); off only in those examples themselves


@dataclass(frozen=True)
class OggConfig:
    quality: float = 0.4  # Vorbis quality 0-1 (q0-q10 / 10); 0.4 is about 128 kbit/s stereo


BUS_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")


@dataclass(frozen=True)
class BusConfig:
    bus: str = "Master"  # the engine bus this category's assets play on
    volume_db: float = 0.0  # default playback volume for this category's assets (the bus itself stays at 0 dB)


@dataclass(frozen=True)
class Config:
    mode: Mode = "strict"
    default_kit: str | None = None
    output_dir: str = "build/audio"
    preview_dir: str = "previews"
    export: tuple[str, ...] = ("wav",)
    style_version: int = 1
    mix: MixConfig = field(default_factory=MixConfig)
    loudness: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LOUDNESS))
    short_sfx: str = "window"  # [loudness] short_sfx: "window" (400 ms, zero-padded) or "duration" (a short one-shot's own length)
    lint: LintConfig = field(default_factory=LintConfig)
    godot: GodotConfig = field(default_factory=GodotConfig)
    ogg: OggConfig = field(default_factory=OggConfig)
    sfx: SfxConfig = field(default_factory=SfxConfig)
    similarity: SimilarityConfig = field(default_factory=SimilarityConfig)
    sounds: SoundsConfig = field(default_factory=SoundsConfig)
    seed: int | None = None  # the project seed: suggestions and rolled kits branch from it
    room: dict[str, float] = field(default_factory=dict)  # category -> room send (0-1, x mix.room)
    bus: dict[str, BusConfig] = field(default_factory=dict)  # category -> mix bus + default dB ([bus.<category>])

    def target(self, category: str) -> float:
        """Loudness target (LUFS) for a category; categories not listed use `sfx`."""
        return self.loudness.get(category, self.loudness.get("sfx", DEFAULT_LOUDNESS["sfx"]))

    def mix_for(self, category: str, send: float | None = None) -> MixConfig:
        """The shared mix with this asset's room send applied (the asset's own `room:`, else its category's
        `[room]` entry, else 1): the same space, just less of it (0 = dry, no tail)."""
        amount = send if send is not None else self.room.get(category, 1.0)
        return self.mix if amount == 1.0 else replace(self.mix, room=round(self.mix.room * amount, 12))


@dataclass(frozen=True)
class Project:
    root: Path
    config: Config
    config_path: Path | None  # None when running without a segan.toml
    _kits: dict[str, Kit] = field(default_factory=dict, compare=False, repr=False)

    @property
    def kits_dir(self) -> Path:
        return self.root / "kits"

    @property
    def music_dir(self) -> Path:
        return self.root / "music"

    @property
    def sfx_dir(self) -> Path:
        return self.root / "sfx"

    @property
    def preview_dir(self) -> Path:
        return self.root / self.config.preview_dir

    @property
    def output_dir(self) -> Path:
        return self.root / self.config.output_dir

    @property
    def cache_dir(self) -> Path:
        return self.root / ".segan-cache"

    def kit_path(self, name: str) -> Path:
        return self.kits_dir / f"{name}{KIT_SUFFIX}"

    def kit_names(self) -> list[str]:
        if not self.kits_dir.is_dir():
            return []
        return sorted(p.name[: -len(KIT_SUFFIX)] for p in self.kits_dir.glob(f"*{KIT_SUFFIX}"))

    def load_kit(self, name: str) -> Kit:
        """Load a kit by name (cached per project). Raises SeganError."""
        if name in self._kits:
            return self._kits[name]
        path = self.kit_path(name)
        if not path.is_file():
            known = ", ".join(self.kit_names()) or "none"
            raise SeganError([Finding("E005", f"unknown kit {name!r}: {path} doesn't exist (kits: {known})", self.config_path)])
        kit = load_kit_file(path)
        self._kits[name] = kit
        return kit

    def kit_text(self, name: str) -> str:
        path = self.kit_path(name)
        return path.read_text(encoding="utf-8") if path.is_file() else ""


def find_project_root(start: Path) -> Path | None:
    """Find the nearest directory at or above `start` containing segan.toml."""
    start = start.resolve()
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory
    return None


def load_project(root: Path) -> Project:
    config_path = root / CONFIG_NAME
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SeganError([Finding("E001", f"cannot read config: {exc.strerror}", config_path)]) from None
    except UnicodeDecodeError:
        raise SeganError([Finding("E001", "config is not valid UTF-8 text", config_path)]) from None
    except tomllib.TOMLDecodeError as exc:
        raise SeganError([Finding("E001", f"invalid TOML: {exc}", config_path)]) from None
    return Project(root=root.resolve(), config=parse_config(data, config_path), config_path=config_path)


def discover_project(start: Path | None = None) -> Project:
    """The project containing `start` (default: cwd), or an open-mode project rooted there if none."""
    start = start or Path.cwd()
    root = find_project_root(start)
    if root is None:
        return Project(root=start.resolve(), config=Config(mode="open"), config_path=None)
    return load_project(root)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_config(data: dict[str, Any], path: Path) -> Config:
    findings: list[Finding] = []

    def error(message: str, where: str) -> None:
        findings.append(Finding("E001", message, path, None, where))

    defaults = Config()
    allowed = ("mode", "default_kit", "output_dir", "preview_dir", "export", "style_version", "seed", "mix", "loudness", "room", "lint", "godot", "ogg", "sfx",
               "similarity", "sounds", "bus")  # fmt: skip
    for key in data:
        if key not in allowed:
            error(f"unknown setting {key!r}; allowed: {', '.join(allowed)}", key)

    mode = data.get("mode", defaults.mode)
    if mode not in MODES:
        error(f"mode must be one of {', '.join(MODES)}", "mode")
        mode = defaults.mode

    default_kit = data.get("default_kit")
    if default_kit is not None and (not isinstance(default_kit, str) or not NAME_RE.match(default_kit)):
        error("default_kit must be a kit name (lowercase letters, digits, '_' or '-')", "default_kit")
        default_kit = None

    dirs: dict[str, str] = {}
    for key in ("output_dir", "preview_dir"):
        value = data.get(key, getattr(defaults, key))
        if not isinstance(value, str) or not value:
            error(f"{key} must be a non-empty path", key)
            value = getattr(defaults, key)
        dirs[key] = value

    export = data.get("export", list(defaults.export))
    if not isinstance(export, list) or not all(isinstance(e, str) and e in EXPORTERS for e in export):
        error(f"export must be a list drawn from {', '.join(EXPORTERS)}", "export")
        export = list(defaults.export)
    elif "godot" in export and "web" in export:
        error('export can\'t have both "godot" and "web": Godot writes res:// paths into manifest.json; build the web '
              'audio into its own output_dir', "export")  # fmt: skip
        export = list(defaults.export)

    style_version = data.get("style_version", defaults.style_version)
    if not _int(style_version) or style_version < 1:
        error("style_version must be a positive integer", "style_version")
        style_version = defaults.style_version

    seed = data.get("seed")
    if seed is not None and not (_int(seed) and 0 <= seed < 2**63):
        error("seed must be a whole number 0..2^63 (the project seed; `segan init` picks one)", "seed")
        seed = None
    mix = _parse_mix(data.get("mix", {}), error)
    loudness_table = data.get("loudness", {})
    short_sfx = defaults.short_sfx
    if isinstance(loudness_table, dict) and "short_sfx" in loudness_table:
        loudness_table = dict(loudness_table)
        short_sfx = loudness_table.pop("short_sfx")
        if short_sfx not in SHORT_SFX:
            error('loudness.short_sfx must be "window" (one-shots measured over 400 ms, the default) or "duration" (one-shots '
                  'shorter than 400 ms measured over their own length)', "loudness.short_sfx")  # fmt: skip
            short_sfx = defaults.short_sfx
    loudness = _parse_loudness(loudness_table, error)
    room = _parse_room(data.get("room", {}), error)
    bus = _parse_bus(data.get("bus", {}), error)
    lint = _parse_lint(data.get("lint", {}), error)
    godot = _parse_godot(data.get("godot", {}), error)
    ogg = _parse_ogg(data.get("ogg", {}), error)
    sfx = _parse_sfx(data.get("sfx", {}), error)
    similarity = _parse_similarity(data.get("similarity", {}), error)
    sounds = _parse_sounds(data.get("sounds", {}), error)
    if findings:
        raise SeganError(findings)
    return Config(
        mode=mode,
        default_kit=default_kit,
        output_dir=dirs["output_dir"],
        preview_dir=dirs["preview_dir"],
        export=tuple(export),
        style_version=style_version,
        mix=mix,
        loudness=loudness,
        short_sfx=short_sfx,
        lint=lint,
        godot=godot,
        ogg=ogg,
        sfx=sfx,
        similarity=similarity,
        sounds=sounds,
        seed=seed,
        room=room,
        bus=bus,
    )


Check = Callable[[Any], bool]


def _table(data: Any, name: str, defaults: Any, rules: dict[str, tuple[Check, str]], error: Callable[[str, str], None]) -> dict[str, Any]:
    """Validate a [table]: every key known and every value passing its check; bad values keep the default."""
    values = {key: getattr(defaults, key) for key in rules}
    if not isinstance(data, dict):
        error(f"[{name}] must be a table", name)
        return values
    for key in data:
        if key not in rules:
            error(f"unknown {name} setting {key!r}; allowed: {', '.join(rules)}", f"{name}.{key}")
    for key, (check, message) in rules.items():
        if key in data:
            if check(data[key]):
                values[key] = data[key]
            else:
                error(f"{name}.{key} {message}", f"{name}.{key}")
    return values


def _parse_mix(data: Any, error: Callable[[str, str], None]) -> MixConfig:
    rules: dict[str, tuple[Check, str]] = {
        "sample_rate": (lambda v: v in SAMPLE_RATES and _int(v), f"must be one of {', '.join(map(str, SAMPLE_RATES))}"),
        "oversample": (lambda v: v in OVERSAMPLE and _int(v), "must be 1, 2, 4 or 8 (synthesis rate multiplier against aliasing)"),
        "music_channels": (lambda v: v in CHANNELS, "must be mono or stereo"),
        "sfx_channels": (lambda v: v in CHANNELS, "must be mono or stereo"),
        "tuning": (lambda v: _number(v) and 400 <= v <= 480, "must be 400-480 Hz (A4)"),
        "room": (lambda v: _number(v) and 0 <= v <= 1, "must be 0-1 (0 = dry)"),
        "room_decay": (lambda v: _number(v) and 0.1 <= v <= 5, "must be 0.1-5 seconds"),
        "crush_bits": (lambda v: _int(v) and (v == 0 or 2 <= v <= 16), "must be 0 (off) or 2-16"),
        "crush_rate": (lambda v: _number(v) and (v == 0 or 1000 <= v <= 48000), "must be 0 (off) or 1000-48000 Hz"),
        "declick": (lambda v: isinstance(v, bool), "must be true or false"),
        "limiter": (lambda v: _number(v) and -12 <= v <= 0, "must be -12..0 dBFS (true-peak ceiling)"),
        "brightness": (lambda v: _number(v) and -12 <= v <= 12, "must be -12..12 dB (high/low tilt)"),
        "warmth": (lambda v: _number(v) and -12 <= v <= 12, "must be -12..12 dB (low-mid body)"),
        "tail_trim_db": (lambda v: _number(v) and -120 <= v <= -20, "must be -120..-20 dB (where the room tail is cut, below the peak)"),
    }
    v = _table(data, "mix", MixConfig(), rules, error)
    return MixConfig(
        sample_rate=int(v["sample_rate"]), oversample=int(v["oversample"]), music_channels=v["music_channels"],
        sfx_channels=v["sfx_channels"], tuning=float(v["tuning"]), room=float(v["room"]), room_decay=float(v["room_decay"]),
        crush_bits=int(v["crush_bits"]), crush_rate=float(v["crush_rate"]), declick=v["declick"], limiter=float(v["limiter"]),
        brightness=float(v["brightness"]), warmth=float(v["warmth"]), tail_trim_db=float(v["tail_trim_db"]),
    )  # fmt: skip


def _parse_loudness(data: Any, error: Callable[[str, str], None]) -> dict[str, float]:
    out = dict(DEFAULT_LOUDNESS)
    if not isinstance(data, dict):
        error("[loudness] must be a table of category = LUFS", "loudness")
        return out
    for key, value in data.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            error(f"loudness category {key!r} must be lowercase letters, digits or '_'", f"loudness.{key}")
        elif not (_number(value) and MIN_TARGET_LUFS <= value <= -5):
            error(f"loudness.{key} must be a target in LUFS, {MIN_TARGET_LUFS:g}..-5 (e.g. -16)", f"loudness.{key}")
        else:
            out[key] = float(value)
    return out


def _parse_room(data: Any, error: Callable[[str, str], None]) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(data, dict):
        error("[room] must be a table of category = room send (0-1)", "room")
        return out
    for key, value in data.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            error(f"room category {key!r} must be lowercase letters, digits or '_'", f"room.{key}")
        elif not (_number(value) and 0 <= value <= 1):
            error(f"room.{key} must be a send of 0-1 (x mix.room; 0 = dry, no tail)", f"room.{key}")
        else:
            out[key] = float(value)
    return out


def _parse_bus(data: Any, error: Callable[[str, str], None]) -> dict[str, BusConfig]:
    """`[bus.<category>]` tables (or `<category> = { bus = "SFX", volume_db = -3 }` under `[bus]`: the same TOML)."""
    out: dict[str, BusConfig] = {}
    if not isinstance(data, dict):
        error("[bus] must hold one table per category: [bus.<category>] with bus and volume_db", "bus")
        return out
    for key, table in data.items():
        where = f"bus.{key}"
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            error(f"bus category {key!r} must be lowercase letters, digits or '_'", where)
            continue
        if not isinstance(table, dict) or set(table) - {"bus", "volume_db"}:
            error(f'[bus.{key}] takes bus (an engine bus name, e.g. "SFX") and volume_db (the category\'s default dB)', where)
            continue
        name, volume = table.get("bus", "Master"), table.get("volume_db", 0.0)
        if not (isinstance(name, str) and BUS_NAME_RE.fullmatch(name)):
            error(f"{where}.bus must be a bus name: a letter, then letters, digits or '_' (up to 32), e.g. \"SFX\"", f"{where}.bus")
        elif not (_number(volume) and -60 <= volume <= 12):
            error(f"{where}.volume_db must be -60..12 dB (the category's default playback volume)", f"{where}.volume_db")
        else:
            out[key] = BusConfig(bus=name, volume_db=float(volume))
    return out


def _parse_lint(data: Any, error: Callable[[str, str], None]) -> LintConfig:
    rules: dict[str, tuple[Check, str]] = {
        "disable": (lambda v: isinstance(v, list) and all(isinstance(r, str) and re.fullmatch(r"W\d{3}", r) for r in v),
                    'must be a list of warning rule ids, e.g. ["W009"] (errors can\'t be disabled)'),  # fmt: skip
        "max_seam_click": (lambda v: _number(v) and 0 < v <= 1, "must be 0-1 (fraction of full scale)"),
        "max_leading_silence_ms": (lambda v: _number(v) and 0 <= v <= 1000, "must be 0-1000 ms"),
        "max_instruments": (lambda v: _int(v) and v >= 1, "must be a positive integer"),
        "max_aliasing_db": (lambda v: _number(v) and -120 <= v <= 0, "must be -120..0 dB"),
        "max_limiting_db": (lambda v: _number(v) and 0 <= v <= 40, "must be 0-40 dB"),
        "max_dc_offset": (lambda v: _number(v) and 0 < v <= 1, "must be 0-1"),
        "loudness_tolerance": (lambda v: _number(v) and 0 < v <= 20, "must be 0-20 LU"),
        "max_similarity": (lambda v: _number(v) and 0.5 <= v <= 1, "must be 0.5-1 (1 = only identical openings warn)"),
    }
    categories: dict[str, tuple[str, ...]] = {}
    if isinstance(data, dict):
        data = dict(data)
        for key in [k for k, value in data.items() if isinstance(value, dict)]:
            table = data.pop(key)
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or set(table) - {"disable"}:
                error(f"[lint.{key}] is a category's own lint settings: only `disable = [\"W017\"]`", f"lint.{key}")
            elif not rules["disable"][0](table.get("disable", [])):
                error(f"lint.{key}.disable {rules['disable'][1]}", f"lint.{key}.disable")
            else:
                categories[key] = tuple(table.get("disable", []))
    v = _table(data, "lint", LintConfig(), rules, error)
    return LintConfig(
        category_disable=categories,
        disable=tuple(v["disable"]), max_seam_click=float(v["max_seam_click"]),
        max_leading_silence_ms=float(v["max_leading_silence_ms"]), max_instruments=int(v["max_instruments"]),
        max_aliasing_db=float(v["max_aliasing_db"]), max_limiting_db=float(v["max_limiting_db"]),
        max_dc_offset=float(v["max_dc_offset"]), loudness_tolerance=float(v["loudness_tolerance"]), max_similarity=float(v["max_similarity"]),
    )  # fmt: skip


def _parse_godot(data: Any, error: Callable[[str, str], None]) -> GodotConfig:
    rules: dict[str, tuple[Check, str]] = {"compress": (lambda v: v in GODOT_COMPRESS, f"must be one of {', '.join(GODOT_COMPRESS)}")}
    v = _table(data, "godot", GodotConfig(), rules, error)
    return GodotConfig(compress=v["compress"])


def _parse_ogg(data: Any, error: Callable[[str, str], None]) -> OggConfig:
    rules: dict[str, tuple[Check, str]] = {"quality": (lambda v: _number(v) and 0 <= v <= 1, "must be 0-1 (Vorbis q0-q10 / 10)")}
    v = _table(data, "ogg", OggConfig(), rules, error)
    return OggConfig(quality=float(v["quality"]))


def _parse_sfx(data: Any, error: Callable[[str, str], None]) -> SfxConfig:
    rules: dict[str, tuple[Check, str]] = {"source": (lambda v: v in SFX_SOURCES, f"must be one of {', '.join(SFX_SOURCES)}")}
    v = _table(data, "sfx", SfxConfig(), rules, error)
    return SfxConfig(source=v["source"])


def _parse_similarity(data: Any, error: Callable[[str, str], None]) -> SimilarityConfig:
    rules: dict[str, tuple[Check, str]] = {"local_store": (lambda v: isinstance(v, bool), "must be true or false"),
                                           "shipped": (lambda v: isinstance(v, bool), "must be true or false")}  # fmt: skip
    v = _table(data, "similarity", SimilarityConfig(), rules, error)
    return SimilarityConfig(local_store=v["local_store"], shipped=v["shipped"])


def _parse_sounds(data: Any, error: Callable[[str, str], None]) -> SoundsConfig:
    def names(v: Any) -> bool:
        return isinstance(v, list) and all(isinstance(n, str) and n.strip() and not n.lower().startswith(("cc-by-nc", "cc by-nc", "cc-by-sa", "cc by-sa", "cc-by-nd")) for n in v)

    rules: dict[str, tuple[Check, str]] = {
        "extra_licences": (names, 'must be a list of licence names this project has cleared, e.g. ["Sonniss-GDC"] (never NC, SA or ND Creative Commons)'),
    }
    v = _table(data, "sounds", SoundsConfig(), rules, error)
    return SoundsConfig(extra_licences=tuple(v["extra_licences"]))
