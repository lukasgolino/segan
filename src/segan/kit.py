"""Kits (`kits/<name>.kit.yaml`): the project's instruments, keyed by one character (SEGAN's palettes).

```yaml
name: nes
instruments:
  p: { name: pulse_lead, osc: pulse, duty: 0.25, env: [0.005, 0.08, 0.6, 0.12], gain: -6 }
  k: { name: kick, drum: kick }
groups:
  leads: [p, q]
```
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from segan.findings import Finding, SeganError
from segan.patch import RESERVED_KEYS, Instrument, Report, line_of, parse_patch
from segan.yamlio import LineMap, YamlError, load_yaml

KIT_SUFFIX = ".kit.yaml"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
KIT_FIELDS = ("name", "description", "instruments", "groups")
# Recommended key order for new instruments (ASCII first; any single Unicode letter/digit works).
KEY_ORDER = "pqrstuvwbcdefgahijklmnyzPQRSTUVWBCDEFGAHIJKLMNOYZ0123456789"


@dataclass(frozen=True)
class Kit:
    name: str | None
    instruments: dict[str, Instrument]
    groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    description: str | None = None
    path: Path | None = None

    def drums(self) -> list[str]:
        return [k for k, inst in self.instruments.items() if inst.is_drum]

    def melodic(self) -> list[str]:
        return [k for k, inst in self.instruments.items() if not inst.is_drum]


def valid_key(key: str) -> bool:
    """One Unicode letter or digit, not a reserved grid character."""
    if len(key) != 1 or key in RESERVED_KEYS:
        return False
    return unicodedata.category(key)[0] in ("L", "N")


def kit_name_from_path(path: Path) -> str | None:
    return path.name[: -len(KIT_SUFFIX)] if path.name.endswith(KIT_SUFFIX) else None


def parse_instruments(raw: Any, report: Report, rule: str, where: str, line: int | None) -> dict[str, Instrument]:
    """The `instruments:` mapping of a kit (or a song's inline instruments)."""
    out: dict[str, Instrument] = {}
    if not isinstance(raw, dict) or not raw:
        report.error(rule, "instruments must map one-character keys to instrument patches, e.g. p: { osc: pulse }", line, where)
        return out
    names: dict[str, str] = {}
    for raw_key, value in raw.items():
        key = str(raw_key)
        kline = line_of(raw, raw_key, line)
        if not valid_key(key):
            reserved = f" ({key!r} is reserved: . rest, - hold, | bar line)" if key in RESERVED_KEYS else ""
            report.error(rule, f"instrument key {key!r} must be ONE letter or digit{reserved}", kline, f"{where}.{key}")
            continue
        if not isinstance(value, dict):
            report.error(rule, f"instrument {key!r} must be a mapping, e.g. {{ osc: pulse, duty: 0.25 }}", kline, f"{where}.{key}")
            continue
        inst = parse_patch(value, report, rule, f"{where}.{key}", key)
        if inst is None:
            continue
        if inst.name:
            if inst.name in names:
                report.error(rule, f"instrument name {inst.name!r} is used by keys {names[inst.name]!r} and {key!r}; names must be unique", kline, f"{where}.{key}.name")
            names[inst.name] = key
        out[key] = inst
    return out


def parse_groups(raw: Any, instruments: dict[str, Instrument], report: Report, rule: str, where: str, line: int | None) -> dict[str, tuple[str, ...]]:
    groups: dict[str, tuple[str, ...]] = {}
    if raw is None:
        return groups
    if not isinstance(raw, dict):
        report.error(rule, "groups must map a group name to a list of instrument keys, e.g. leads: [p, q]", line, where)
        return groups
    for name, members in raw.items():
        gline = line_of(raw, name, line)
        if not isinstance(members, list) or not members:
            report.error(rule, f"group {name!r} must be a non-empty list of instrument keys", gline, f"{where}.{name}")
            continue
        keys = tuple(str(m) for m in members)
        missing = [k for k in keys if k not in instruments]
        if missing:
            report.error(rule, f"group {name!r} lists unknown instrument key(s) {', '.join(map(repr, missing))}; known: {' '.join(instruments)}", gline, f"{where}.{name}")
            continue
        groups[str(name)] = keys
    return groups


def parse_kit(data: Any, path: Path | None, expect_name: str | None = None) -> tuple[Kit | None, list[Finding]]:
    report = Report(path)
    if not isinstance(data, dict):
        report.error("E005", "a kit file must be a mapping with name, instruments and optional groups")
        return None, report.findings
    line = data.line if isinstance(data, LineMap) else None
    for key in data:
        if key not in KIT_FIELDS:
            report.error("E005", f"unknown kit field {key!r}; allowed: {', '.join(KIT_FIELDS)}", line_of(data, key, line), str(key))
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        report.error("E005", "name must be lowercase letters, digits, '_' or '-'", line_of(data, "name", line), "name")
        name = None
    elif expect_name is not None and name != expect_name:
        report.error("E005", f"name {name!r} must match the file name ({expect_name}{KIT_SUFFIX}); songs and SFX reference kits by name", line_of(data, "name", line), "name")
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        report.error("E005", "description must be text", line_of(data, "description", line), "description")
        description = None
    instruments = parse_instruments(data.get("instruments"), report, "E005", "instruments", line_of(data, "instruments", line))
    groups = parse_groups(data.get("groups"), instruments, report, "E005", "groups", line_of(data, "groups", line))
    if report.failed:
        return None, report.findings
    return Kit(name, instruments, groups, description, path), report.findings


def load_kit_file(path: Path) -> Kit:
    """Load and validate a kit file; raises SeganError with every finding."""
    try:
        data = load_yaml(path)
    except YamlError as exc:
        raise SeganError([Finding("E001", exc.message, path, exc.line)]) from None
    kit, findings = parse_kit(data, path, kit_name_from_path(path))
    if kit is None:
        raise SeganError(findings)
    return kit
