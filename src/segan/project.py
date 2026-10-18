"""SEGAN projects: a directory with a segan.toml plus kits/, music/ and sfx/.

Adapted from PAGAN's project.py (discovery by walking up to the config file, open mode without one,
unknown keys are errors); the config sections are SEGAN's own.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from segan.findings import Finding, SeganError
from segan.kit import KIT_SUFFIX, NAME_RE, Kit, load_kit_file

CONFIG_NAME = "segan.toml"
MODES = ("strict", "open")
EXPORTERS = ("wav", "godot", "stems")
SAMPLE_RATES = (22050, 32000, 44100, 48000)
OVERSAMPLE = (1, 2, 4, 8)
CHANNELS = ("mono", "stereo")
GODOT_COMPRESS = ("none", "ima", "qoa")
DEFAULT_LOUDNESS = {"music": -16.0, "sfx": -14.0, "ui": -20.0}

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


@dataclass(frozen=True)
class GodotConfig:
    compress: str = "qoa"


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
    lint: LintConfig = field(default_factory=LintConfig)
    godot: GodotConfig = field(default_factory=GodotConfig)

    def target(self, category: str) -> float:
        """Loudness target (LUFS) for a category; categories not listed use `sfx`."""
        return self.loudness.get(category, self.loudness.get("sfx", DEFAULT_LOUDNESS["sfx"]))


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
    allowed = ("mode", "default_kit", "output_dir", "preview_dir", "export", "style_version", "mix", "loudness", "lint", "godot")
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

    style_version = data.get("style_version", defaults.style_version)
    if not _int(style_version) or style_version < 1:
        error("style_version must be a positive integer", "style_version")
        style_version = defaults.style_version

    mix = _parse_mix(data.get("mix", {}), error)
    loudness = _parse_loudness(data.get("loudness", {}), error)
    lint = _parse_lint(data.get("lint", {}), error)
    godot = _parse_godot(data.get("godot", {}), error)
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
        lint=lint,
        godot=godot,
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
    }
    v = _table(data, "mix", MixConfig(), rules, error)
    return MixConfig(
        sample_rate=int(v["sample_rate"]), oversample=int(v["oversample"]), music_channels=v["music_channels"],
        sfx_channels=v["sfx_channels"], tuning=float(v["tuning"]), room=float(v["room"]), room_decay=float(v["room_decay"]),
        crush_bits=int(v["crush_bits"]), crush_rate=float(v["crush_rate"]), declick=v["declick"], limiter=float(v["limiter"]),
        brightness=float(v["brightness"]), warmth=float(v["warmth"]),
    )  # fmt: skip


def _parse_loudness(data: Any, error: Callable[[str, str], None]) -> dict[str, float]:
    out = dict(DEFAULT_LOUDNESS)
    if not isinstance(data, dict):
        error("[loudness] must be a table of category = LUFS", "loudness")
        return out
    for key, value in data.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            error(f"loudness category {key!r} must be lowercase letters, digits or '_'", f"loudness.{key}")
        elif not (_number(value) and -40 <= value <= -5):
            error(f"loudness.{key} must be a target in LUFS, -40..-5 (e.g. -16)", f"loudness.{key}")
        else:
            out[key] = float(value)
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
    }
    v = _table(data, "lint", LintConfig(), rules, error)
    return LintConfig(
        disable=tuple(v["disable"]), max_seam_click=float(v["max_seam_click"]),
        max_leading_silence_ms=float(v["max_leading_silence_ms"]), max_instruments=int(v["max_instruments"]),
        max_aliasing_db=float(v["max_aliasing_db"]), max_limiting_db=float(v["max_limiting_db"]),
        max_dc_offset=float(v["max_dc_offset"]), loudness_tolerance=float(v["loudness_tolerance"]),
    )  # fmt: skip


def _parse_godot(data: Any, error: Callable[[str, str], None]) -> GodotConfig:
    rules: dict[str, tuple[Check, str]] = {"compress": (lambda v: v in GODOT_COMPRESS, f"must be one of {', '.join(GODOT_COMPRESS)}")}
    v = _table(data, "godot", GodotConfig(), rules, error)
    return GodotConfig(compress=v["compress"])
