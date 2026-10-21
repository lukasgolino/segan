"""A small YAML writer for generated sources (`segan bake sfx`, `segan.api` writers, MIDI import): block
style for structure, flow style (`[a, b]`, `{k: v}`) for short leaves, multi-line strings as `|` blocks,
so the output reads like hand-written SEGAN files."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

FLOW_WIDTH = 110
_PLAIN = re.compile(r"^[A-Za-z0-9_#][A-Za-z0-9_#.+\-]*$")


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(round(value, 9)).removesuffix(".0") if value == int(value) and abs(value) < 1e15 else repr(round(value, 9))
    text = str(value)
    if _PLAIN.match(text) and not text.startswith("#"):
        try:
            if yaml.safe_load(text) == text:
                return text
        except yaml.YAMLError:
            pass
    return json.dumps(text, ensure_ascii=False)


def _is_leaf(value: Any) -> bool:
    if isinstance(value, list):
        return all(_is_leaf(v) for v in value)
    if isinstance(value, dict):
        return all(not isinstance(v, dict) and _is_leaf(v) for v in value.values())
    return not (isinstance(value, str) and "\n" in value)


def flow(value: Any) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(flow(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{scalar(k)}: {flow(v)}" for k, v in value.items()) + " }" if value else "{}"
    return scalar(value)


def _block(key: str, value: Any, indent: str, path: str = "", comments: dict[str, str] | None = None) -> list[str]:
    """`comments` maps a dotted path (`patterns.chorus`, `tracks`) to text written as `#` lines above that key."""
    path = f"{path}.{key}" if path else key
    note = [f"{indent}# {line}".rstrip() for line in comments[path].split("\n")] if comments and path in comments else []
    return note + _block_lines(key, value, indent, path, comments)


def _block_lines(key: str, value: Any, indent: str, path: str, comments: dict[str, str] | None) -> list[str]:
    head = f"{indent}{scalar(key)}:"
    if isinstance(value, str) and "\n" in value:
        body = value.rstrip("\n").split("\n")
        return [f"{head} |", *(f"{indent}  {line}" if line else "" for line in body)]
    if _is_leaf(value):
        text = flow(value)
        if len(head) + 1 + len(text) <= FLOW_WIDTH or not isinstance(value, dict | list) or not value:
            return [f"{head} {text}"]
    if isinstance(value, dict):
        lines = [head]
        for k, v in value.items():
            lines += _block(str(k), v, indent + "  ", path, comments)
        return lines
    if isinstance(value, list):
        lines = [head]
        for item in value:
            if isinstance(item, dict) and item:
                inner = []
                for k, v in item.items():
                    inner += _block(str(k), v, indent + "    ")
                inner[0] = f"{indent}  - " + inner[0].lstrip()
                lines += inner
            else:
                lines.append(f"{indent}  - {flow(item)}")
        return lines
    return [f"{head} {scalar(value)}"]


def dump_mapping(data: dict[str, Any], order: list[str] | None = None, comments: dict[str, str] | None = None) -> str:
    """YAML text for a mapping; keys in `order` first, then the rest as given. `comments`: dotted path -> text
    written as comment lines above that key (top-level and nested mapping keys)."""
    keys = [k for k in (order or []) if k in data] + [k for k in data if k not in (order or [])]
    lines: list[str] = []
    for key in keys:
        lines += _block(key, data[key], "", "", comments)
    return "\n".join(lines) + "\n"
