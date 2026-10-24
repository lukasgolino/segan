"""The MCP server (`segan mcp`), driven in-process by the SDK's client. Skipped without the "mcp" extra."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.types import AudioContent, CallToolResult, ImageContent, TextContent  # noqa: E402
from PIL import Image  # noqa: E402

from conftest import make_project, write  # noqa: E402
from segan.mcp_server import create_server  # noqa: E402
from test_midi import song_file  # noqa: E402
from test_song import SONG  # noqa: E402


def run(root: Path, body: Callable[[Client], Awaitable[Any]], allow_godot: bool = False) -> Any:
    async def go() -> Any:
        async with Client(create_server(root, allow_godot)) as client:
            return await body(client)

    return anyio.run(go)


def call(root: Path, tool: str, args: dict[str, Any] | None = None, allow_godot: bool = False) -> CallToolResult:
    async def body(client: Client) -> CallToolResult:
        return await client.call_tool(tool, args or {})

    result: CallToolResult = run(root, body, allow_godot)
    return result


def data(result: CallToolResult) -> dict[str, Any]:
    if isinstance(result.structured_content, dict) and "ok" in result.structured_content:
        return result.structured_content
    text = next(c for c in result.content if isinstance(c, TextContent)).text
    parsed: dict[str, Any] = json.loads(text)
    return parsed


def images(result: CallToolResult) -> list[Image.Image]:
    return [Image.open(io.BytesIO(base64.b64decode(c.data))) for c in result.content if isinstance(c, ImageContent)]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = make_project(tmp_path)
    (tmp_path / "BRIEF.md").write_text("# Sound brief\n\n## Decisions and feedback log\n")
    (tmp_path / "SOUND.md").write_text("# Sound bible\n")
    write(project, "song", "tune", SONG)
    return tmp_path


def test_tools_and_resources_are_listed(root: Path) -> None:
    async def body(client: Client) -> tuple[list[str], list[str]]:
        tools = await client.list_tools()
        resources = await client.list_resources()
        return [t.name for t in tools.tools], [str(r.uri) for r in resources.resources]

    tools, resources = run(root, body)
    for name in ("status", "read_docs", "write_doc", "log_feedback", "config_show", "config_set", "config_unset", "kit_list", "kit_show",
                 "kit_write", "mix_adjust", "scaffold", "read_asset", "write_asset", "lint", "preview", "gallery", "mark", "style_bump",
                 "import_midi", "build", "manifest", "sounds_search", "sounds_add", "sounds_inspect", "sounds_credits", "similarity", "suggest_song", "kit_roll"):  # fmt: skip
        assert name in tools, name
    assert {"segan://workflow", "segan://reference", "segan://brief", "segan://sound", "segan://manifest"} <= set(resources)


def test_status_docs_and_feedback(root: Path) -> None:
    assert [a["name"] for a in data(call(root, "status"))["assets"]] == ["tune"]
    assert data(call(root, "read_docs"))["SOUND.md"] == "# Sound bible\n"
    logged = data(call(root, "log_feedback", {"note": "drums too loud"}))
    assert logged["ok"] and "drums too loud" in (root / "BRIEF.md").read_text()


def test_write_asset_lints_and_returns_the_sheet(root: Path) -> None:
    result = call(root, "write_asset", {"kind": "sfx", "name": "pew", "text": "name: pew\npreset: laser\n"})
    payload = data(result)
    assert payload["ok"] and payload["errors"] == 0 and payload["analysis"]["lufs"] < 0
    assert images(result) and images(result)[0].width > 500
    bad = data(call(root, "write_asset", {"kind": "sfx", "name": "bad", "text": "name: bad\nlayers: []\n"}))
    assert not bad["ok"] and bad["findings"][0]["rule"] == "E013"
    clash = data(call(root, "write_asset", {"kind": "sfx", "name": "tune", "text": "name: tune\npreset: blip\n"}))
    assert not clash["ok"] and "unique" in clash["findings"][0]["message"]


def test_preview_returns_image_and_audio(root: Path) -> None:
    result = call(root, "preview", {"asset": "tune", "which": "seam", "audio": True})
    assert data(result)["ok"] and images(result)
    audio = [c for c in result.content if isinstance(c, AudioContent)]
    assert audio and base64.b64decode(audio[0].data)[:4] == b"RIFF"


def test_scaffold_kits_mix_and_config(root: Path) -> None:
    scaffolded = data(call(root, "scaffold", {"kind": "song", "name": "theme", "description": "a theme", "key": "D dorian"}))
    assert scaffolded["ok"] and "key: D dorian" in scaffolded["text"]
    kits = data(call(root, "kit_list"))
    assert set(kits["kits"]) == {"t", "u"} and kits["kits"]["t"]["instruments"]["p"]["name"] == "lead"
    shown = call(root, "kit_show", {"name": "t"})
    assert data(shown)["ok"] and images(shown)
    dry = data(call(root, "mix_adjust", {"room": 0.1}))
    assert dry["ok"] and dry["written"] is False
    assert data(call(root, "config_set", {"key": "mix.room", "value": "0.25"}))["new"] == 0.25
    written = data(call(root, "kit_write", {"name": "v", "text": "name: v\ninstruments:\n  p: { osc: wobble }\n"}))
    assert not written["ok"]


def test_import_build_and_manifest(root: Path) -> None:
    encoded = base64.b64encode(song_file()).decode()
    imported = data(call(root, "import_midi", {"midi_base64": encoded, "name": "fromfile"}))
    assert imported["ok"], imported
    assert data(call(root, "build", {"verify_godot": True}))["ok"] is False  # not allowed without --allow-godot
    built = data(call(root, "build"))
    assert built["ok"], built
    manifest = data(call(root, "manifest", {"asset": "tune"}))
    assert manifest["ok"] and manifest["entry"]["kind"] == "song"


def test_paths_are_confined(root: Path) -> None:
    result = data(call(root, "import_midi", {"path": "../../etc/passwd"}))
    assert not result["ok"] and "outside" in result["findings"][0]["message"]
