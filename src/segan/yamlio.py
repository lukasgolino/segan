"""YAML loading that rejects duplicate keys and remembers source line numbers.

Copied from PAGAN (yamlio.py) without the hex-colour hint; keep the two close so fixes port easily.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

import yaml


class LineMap(dict[Any, Any]):
    """A dict that remembers the 1-based source line of the mapping and of each key."""

    def __init__(self) -> None:
        super().__init__()
        self.line: int | None = None
        self.key_lines: dict[Any, int] = {}
        # key -> (line, start column, end column) of a scalar value, 1-based line, 0-based columns
        self.value_spans: dict[Any, tuple[int, int, int]] = {}

    def line_of(self, key: Any) -> int | None:
        return self.key_lines.get(key, self.line)


class YamlError(Exception):
    def __init__(self, message: str, line: int | None) -> None:
        super().__init__(message)
        self.message = message
        self.line = line


class _Loader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _Loader, node: yaml.MappingNode) -> LineMap:
    loader.flatten_mapping(node)
    result = LineMap()
    result.line = node.start_mark.line + 1
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        line = key_node.start_mark.line + 1
        try:
            duplicate = key in result
        except TypeError:
            raise yaml.constructor.ConstructorError(
                None, None, "mapping keys must be plain values, not lists or mappings", key_node.start_mark
            ) from None
        if duplicate:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate key {key!r} (first defined on line {result.key_lines[key]})",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=True)
        result.key_lines[key] = line
        start, end = value_node.start_mark, value_node.end_mark
        if isinstance(value_node, yaml.ScalarNode) and start.line == end.line:
            result.value_spans[key] = (start.line + 1, start.column, end.column)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def parse_yaml(text: str) -> Any:
    """Parse YAML text. Mappings come back as LineMap. Raises YamlError.

    Text is NFC-normalized first, so "é" typed as e + combining accent is the same one-character key.
    """
    text = unicodedata.normalize("NFC", text)
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 - _Loader is a SafeLoader
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        message = exc.problem or str(exc)
        if exc.context:
            message = f"{exc.context}: {message}"
        raise YamlError(f"invalid YAML: {message}", line) from None
    except yaml.YAMLError as exc:
        raise YamlError(f"invalid YAML: {exc}", None) from None


def load_yaml(path: Path) -> Any:
    """Read and parse a YAML file. Raises YamlError (also for unreadable files)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise YamlError(f"cannot read file: {exc.strerror}", None) from None
    except UnicodeDecodeError:
        raise YamlError("file is not valid UTF-8 text", None) from None
    return parse_yaml(text)
