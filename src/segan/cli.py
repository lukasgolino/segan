"""Command-line interface for SEGAN."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from typing import Any

from segan.buildinfo import version_string
from segan.findings import Finding, SeganError


class Output:
    """Human-readable output by default; one JSON object on stdout with --json."""

    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def say(self, text: str) -> None:
        if not self.as_json:
            print(text)

    def result(self, data: dict[str, Any]) -> None:
        if self.as_json:
            print(json.dumps({"ok": True, **data}, indent=2))

    def failure(self, findings: list[Finding], data: dict[str, Any] | None = None) -> None:
        if self.as_json:
            print(json.dumps({"ok": False, **(data or {}), "findings": [f.to_dict() for f in findings]}, indent=2))
        else:
            for finding in findings:
                print(finding.format())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="segan", description="SEGAN: Sound Effect Grammar And Notation")
    parser.add_argument("--version", action="version", version=version_string())
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output (any command)")
    return parser


Handler = Callable[[argparse.Namespace, Output], int]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    out = Output(as_json=getattr(args, "json", False))
    try:
        return handler(args, out)
    except SeganError as exc:
        out.failure(exc.findings)
        return 1
