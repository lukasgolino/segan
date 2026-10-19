"""Rendering assets to audio outputs, with a cache in `<project>/.segan-cache/renders/`.

An asset renders to one or more outputs (the main sound, variations, phases, variants, stems), each a
16-bit PCM buffer with its loop points, cue markers and level report. Everything downstream (WAVs, listen
sheets, lint) reads these, so previews, lint and builds always agree on the samples.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from segan import __version__, progress
from segan.dsp import Signal
from segan.mix import Level
from segan.project import Project
from segan.wavio import FULL_SCALE, wav_bytes

RENDERER_VERSION = 2  # bump when rendering changes, so cached renders are redone


@dataclass
class Output:
    id: str  # "" main, "variation:2", "phase:charge", "variant:danger", "stem:lead"
    stem: str  # file name without .wav: coin, coin.2, coin.charge, overworld.danger, overworld/lead
    pcm: NDArray[np.int16]  # (frames, channels)
    rate: int
    loop: tuple[int, int] | None = None
    cues: list[tuple[str, int]] = field(default_factory=list)
    level: dict[str, float | None] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)  # facts for lint (sounding layers, sections...)

    @property
    def audio(self) -> Signal:
        return np.asarray(self.pcm, dtype=np.float64) / FULL_SCALE

    @property
    def frames(self) -> int:
        return int(self.pcm.shape[0])

    @property
    def channels(self) -> int:
        return int(self.pcm.shape[1])

    @property
    def seconds(self) -> float:
        return self.frames / self.rate

    def wav(self) -> bytes:
        return wav_bytes(self.pcm, self.rate, self.loop, self.cues)


@dataclass
class Render:
    name: str
    kind: str
    outputs: list[Output]

    def output(self, output_id: str = "") -> Output:
        for out in self.outputs:
            if out.id == output_id:
                return out
        raise KeyError(output_id)

    @property
    def main(self) -> Output:
        return self.outputs[0]


def level_dict(level: Level) -> dict[str, float | None]:
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in asdict(level).items()}


def cache_key(*parts: object) -> str:
    text = "\x1e".join(repr(p) for p in (RENDERER_VERSION, __version__, *parts))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _save(render: Render) -> bytes:
    arrays: dict[str, Any] = {f"pcm{i}": out.pcm for i, out in enumerate(render.outputs)}
    meta = {
        "name": render.name,
        "kind": render.kind,
        "outputs": [{"id": o.id, "stem": o.stem, "rate": o.rate, "loop": o.loop, "cues": o.cues, "level": o.level, "info": o.info} for o in render.outputs],
    }
    buffer = io.BytesIO()
    arrays["meta"] = np.frombuffer(json.dumps(meta).encode("utf-8"), dtype=np.uint8)
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def _load(data: bytes) -> Render:
    with np.load(io.BytesIO(data)) as npz:
        meta = json.loads(bytes(npz["meta"]).decode("utf-8"))
        outputs = [
            Output(o["id"], o["stem"], np.asarray(npz[f"pcm{i}"], dtype=np.int16), o["rate"], tuple(o["loop"]) if o["loop"] else None,
                   [(str(n), int(p)) for n, p in o["cues"]], o["level"], o["info"])  # fmt: skip
            for i, o in enumerate(meta["outputs"])
        ]
    return Render(meta["name"], meta["kind"], outputs)


def render_asset(asset: Any, project: Project, use_cache: bool = True) -> Render:
    """Render a song or SFX (from the cache when nothing that affects it changed)."""
    from segan.sfxrender import render_sfx, sfx_cache_parts
    from segan.songrender import render_song, song_cache_parts

    parts: tuple[object, ...] = sfx_cache_parts(asset, project) if asset.kind == "sfx" else song_cache_parts(asset, project)

    def compute() -> Render:
        return render_sfx(asset, project) if asset.kind == "sfx" else render_song(asset, project)

    key = cache_key(*parts)
    path = project.cache_dir / "renders" / f"{key}.npz"
    if use_cache and path.is_file():
        try:
            return _load(path.read_bytes())
        except (OSError, ValueError, KeyError):
            pass
    progress.note(f"rendering {asset.kind} {asset.name}")
    render = compute()
    if use_cache:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_save(render))
        except OSError:
            pass
    return render
