"""`segan preview`: WAVs for the human, listen sheets for the agent, and the numbers to compare.

Writes `<preview_dir>/<asset>/<output>.wav` and `<output>.listen.png` for every output (main sound,
variations, phases, variants), a seam view for loops, and returns the analysis as JSON-ready dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from segan.analysis import (
    clipped_samples,
    dc_offset,
    integrated_lufs,
    leading_silence,
    max_momentary_lufs,
    onsets,
    peak_db,
    seam_click,
    spectral_centroid,
    true_peak_db,
    yin,
)
from segan.dsp import Signal, midi_to_hz_scalar
from segan.listen import BAD, DIM, GOOD, TEXT, TRACK_COLOURS, WARN, Block, RollNote, RollTrack, SheetSpec, listen_sheet, seam_sheet
from segan.project import Project
from segan.render import Output, Render
from segan.sfx import Layer, Sfx

JOIN_ERROR = 1e-3  # a walk may differ this much from a straight render of its path (16-bit rounding, limiter at clip edges)

Colour = tuple[int, int, int]


def analyze(output: Output, kind: str) -> dict[str, Any]:
    """The numbers an agent compares (they are also what lint checks)."""
    audio = output.audio
    rate = output.rate
    measure = "integrated" if kind == "song" else "momentary"
    result: dict[str, Any] = {
        "file": output.stem + ".wav",
        "seconds": round(output.seconds, 4),
        "frames": output.frames,
        "channels": output.channels,
        "sample_rate": rate,
        "peak_dbfs": round(peak_db(audio), 2),
        "true_peak_dbtp": round(true_peak_db(audio), 2),
        "lufs": round(integrated_lufs(audio, rate) if measure == "integrated" else max_momentary_lufs(audio, rate), 2),
        "loudness_measure": "integrated" if measure == "integrated" else "max momentary (400 ms)",
        "target_lufs": output.level.get("target"),
        "normalisation_gain_db": round(float(output.level.get("gain_db") or 0.0), 2),
        "limiter_reduction_db": round(float(output.level.get("limiting_db") or 0.0), 2),
        "clipped_samples": clipped_samples(output.pcm),
        "dc_offset": round(dc_offset(audio), 5),
        "centroid_hz": round(spectral_centroid(audio, rate), 1),
        "onsets_s": onsets(audio, rate),
    }
    if output.info.get("mixes"):
        result["stem_mixes_lufs"] = output.info["mixes"]  # each `stems.mixes` combination as the game plays it
        result["stem_mixes_trim_db"] = output.info["mix_trims"]  # what the game adds to the stems while playing each mix
    if output.info.get("normalised_over"):
        result["normalised_over_mix"] = output.info["normalised_over"]
    if kind == "sfx" and not output.info.get("loop"):
        result["room_tail_s"] = round(max(0.0, output.seconds - float(output.info.get("duration", output.seconds))), 3)
    if kind == "sfx":
        result["leading_silence_ms"] = round(leading_silence(audio, rate) * 1000.0, 2)
        result["sounding_at_end"] = output.info.get("sounding_at_end", [])
        track = yin(audio[: min(len(audio), rate * 4)], rate, require_fundamental=True)
        voiced = track.hz[track.hz > 0]
        if len(voiced):
            result["pitch_hz"] = {"start": round(float(voiced[0]), 1), "end": round(float(voiced[-1]), 1),
                                  "min": round(float(voiced.min()), 1), "max": round(float(voiced.max()), 1)}  # fmt: skip
    if output.loop is not None:
        result["loop"] = {"start": output.loop[0], "end": output.loop[1]}
        result["seam_click"] = round(seam_click(audio, output.loop[0], output.loop[1]), 5)
    return result


def level_stats(analysis: dict[str, Any], threshold_click: float | None = None) -> list[tuple[str, str, Colour]]:
    target = analysis.get("target_lufs")
    lufs = analysis["lufs"]
    off = abs(lufs - target) if target is not None else 0.0
    tail = analysis.get("room_tail_s")
    stats: list[tuple[str, str, Colour]] = [
        ("length", f"{analysis['seconds']:.3f}s" + (f" ({analysis['seconds'] - tail:.2f}s + {tail:.2f}s room tail)" if tail else ""), TEXT),
        ("peak", f"{analysis['peak_dbfs']:.1f} dBFS", TEXT),
        ("true peak", f"{analysis['true_peak_dbtp']:.1f} dBTP", TEXT),
        ("LUFS", f"{lufs:.1f}" + (f" (target {target:g})" if target is not None else " (not normalised)"), GOOD if off <= 1 else WARN),
        ("limiter", f"{analysis['limiter_reduction_db']:.1f} dB off", GOOD if analysis["limiter_reduction_db"] <= 3 else WARN),
    ]
    if "leading_silence_ms" in analysis:
        silence = analysis["leading_silence_ms"]
        stats.append(("lead-in", f"{silence:.1f} ms", GOOD if silence <= 5 else WARN))
    if "seam_click" in analysis:
        click = analysis["seam_click"]
        stats.append(("seam click", f"{click:.4f}", BAD if threshold_click is not None and click > threshold_click else GOOD))
    if analysis["clipped_samples"]:
        stats.append(("clipped", str(analysis["clipped_samples"]), BAD))
    stats.append(("centroid", f"{analysis['centroid_hz']:.0f} Hz", DIM))
    return stats


def _layer_targets(layer: Layer, start: float, end: float, tuning: float) -> list[tuple[float, float, float]]:
    """Intended pitch of a layer over time, as short segments (for the white lines on the spectrogram)."""
    if layer.inst.is_drum or layer.inst.wave in ("noise", "bitnoise"):
        return []
    frames = layer.pitch or ((0.0, float(layer.inst.note)),)
    out: list[tuple[float, float, float]] = []
    points = np.linspace(start, end, 60)
    times = np.array([f[0] for f in frames]) + start
    values = np.array([f[1] for f in frames])
    for a, b in zip(points[:-1], points[1:], strict=True):
        if layer.slide:
            midi = float(np.interp(a, times, values))
        else:
            midi = float(values[max(0, int(np.searchsorted(times, a, side="right")) - 1)])
        out.append((float(a), float(b), midi_to_hz_scalar(midi, tuning)))
    return out


def layer_end(layer: Layer, duration: float) -> float:
    """When a layer stops sounding (at most the SFX's duration)."""
    inst = layer.inst
    if inst.is_drum:
        return min(duration, layer.start + inst.tail())
    gate = layer.length if layer.length is not None else max(0.001, duration - layer.start - inst.tail())
    env = inst.env
    span = gate + env.release
    if env.sustain == 0:
        span = min(span, env.attack + env.decay + env.release)
    return min(duration, layer.start + span)


def sfx_sheet(sfx: Sfx, output: Output, analysis: dict[str, Any], project: Project, threshold_click: float) -> SheetSpec:
    phase = output.id.split(":", 1)[1] if output.id.startswith("phase:") else None
    layers = sfx.phases[phase].layers if phase else sfx.layers
    duration = float(output.info.get("duration", sfx.duration))
    rows: list[str] = []
    notes_: list[RollNote] = []
    colours: dict[str, Colour] = {}
    targets: list[tuple[float, float, float]] = []
    for i, layer in enumerate(layers):
        end = layer_end(layer, duration)
        label = f"{layer.id or f'layer {layer.index}'}: {layer.inst.describe()}"
        rows.append(str(i))
        notes_.append(RollNote(i, layer.start, max(end, layer.start + 0.005), label))
        colours[label] = TRACK_COLOURS[i % len(TRACK_COLOURS)]
        targets += _layer_targets(layer, layer.start, end, project.config.mix.tuning)
    lanes = RollTrack("layers", rows, notes_, drums=True, colours=colours)
    title = f"sfx {output.stem}  [{sfx.category}]" + (f"  - {sfx.meta.description}" if sfx.meta.description else "")
    notes = []
    if output.info.get("sounding_at_end"):
        notes.append(f"still sounding when cut at duration {duration:g}s: {', '.join(output.info['sounding_at_end'])} (W011)")
    if analysis.get("pitch_hz"):
        p = analysis["pitch_hz"]
        notes.append(f"detected pitch: start {p['start']} Hz, end {p['end']} Hz (range {p['min']}-{p['max']}); white lines = intended")
    pitch = yin(output.audio, output.rate, hop=0.004, require_fundamental=True)
    return SheetSpec(title[:150], level_stats(analysis, threshold_click), output.audio, output.rate, tracks=[lanes], pitch=pitch,
                     pitch_targets=targets, notes=notes, loop=(output.loop[0] / output.rate, output.loop[1] / output.rate) if output.loop else None)  # fmt: skip


@dataclass
class PreviewResult:
    asset: str
    folder: Path
    files: list[dict[str, Any]] = field(default_factory=list)  # per output: wav, sheet, seam, analysis


def write_preview(asset: Any, render: Render, project: Project, start: float | None = None, end: float | None = None,
                  only: list[str] | None = None, compressed: str | None = None) -> PreviewResult:  # fmt: skip
    """WAV + listen sheet (+ seam view for loops) per output into <preview_dir>/<asset>/."""
    folder = project.preview_dir / asset.name
    folder.mkdir(parents=True, exist_ok=True)
    result = PreviewResult(asset.name, folder)
    click = project.config.lint.max_seam_click
    outputs = list(render.outputs)
    walks = [o for o in (only or ["walk"]) if o == "walk" or o.startswith("walk:")]
    if render.kind == "song" and asset.flow is not None:
        outputs += [walk_output(asset, render, project, int(w.split(":", 1)[1]) if ":" in w else 1) for w in walks]
    if render.kind == "sfx" and only and "reel" in only:
        outputs.append(reel_output(asset, render))
    for output in outputs:
        if output.id.startswith("walk"):
            result.files.append(_write_walk(asset, output, folder, click))
            continue
        if output.id == "reel":
            result.files.append(_write_reel(asset, output, folder, click))
            continue
        if only and not {output.id or "main", output.stem} & set(only):
            continue
        if not only and output.id.startswith(("stem:", "mix:", "flow")):
            continue  # build outputs; preview them with --output stem:<name> / mix:<name> / flow:<clip>
        base = output.stem.replace("/", ".")
        wav = folder / f"{base}.wav"
        wav.write_bytes(output.wav())
        analysis = analyze(output, render.kind)
        if render.kind == "song" and (output.id == "" or output.id.startswith(("stem:", "mix:"))):
            from segan.songpreview import pitch_check

            check = pitch_check(asset, project)
            if output.id:  # a stem or mix: only its own tracks
                check = {t: c for t, c in check.items() if t in output.info.get("tracks", [])}
            analysis["pitch_check"] = check
            analysis["notes_per_pattern"] = {name: {t: sum(n.track == t for n in pat.notes) for t in sorted({n.track for n in pat.notes})}
                                             for name, pat in asset.patterns.items()}  # fmt: skip
        if render.kind == "sfx":
            from segan.sfxrender import layer_levels

            analysis["layers"] = layer_levels(asset, project, output.id)
            spec = sfx_sheet(asset, output, analysis, project, click)
        else:
            from segan.songpreview import song_sheet

            spec = song_sheet(asset, output, analysis, project, click)
        if start is not None or end is not None:
            spec.start = start or 0.0
            spec.end = end
        sheet = folder / f"{base}.listen.png"
        listen_sheet(spec, analysis.get("target_lufs")).save(sheet)
        entry: dict[str, Any] = {"output": output.id or "main", "wav": wav, "sheet": sheet, "analysis": analysis}
        if output.loop is not None:
            seam = folder / f"{base}.seam.png"
            seam_sheet(output.stem, output.audio, output.rate, output.loop[0], output.loop[1], analysis["seam_click"], click).save(seam)
            entry["seam"] = seam
        result.files.append(entry)
    if compressed is not None:  # a shareable copy of every preview WAV (the WAV stays: it's what lint measured)
        from segan import oggio
        from segan.wavio import read_wav

        for entry in result.files:
            wav = read_wav(entry["wav"].read_bytes())
            path = entry["wav"].with_suffix(f".{compressed}")
            data = oggio.encode_mp3(wav.samples, wav.rate) if compressed == "mp3" else oggio.encode_ogg(wav.samples, wav.rate, 0.6, path.name)
            path.write_bytes(data)
            entry[compressed] = path
    return result


REEL_GAP = 0.4  # seconds of silence between the takes of a reel


def reel_output(sfx: Sfx, render: Render) -> Output:
    """Every playable take of an SFX back to back (the main sound, then each variation), REEL_GAP apart, so a
    listener can judge the variety in one go. Each take keeps its own level, as the game plays it."""
    takes = [o for o in render.outputs if o.id == "" or o.id.startswith("variation:")] or list(render.outputs)
    first = takes[0]
    gap = np.zeros((round(REEL_GAP * first.rate), first.channels), dtype=np.int16)
    pcm = np.concatenate([part for o in takes for part in (o.pcm, gap)][:-1])
    starts, at = [], 0
    for o in takes:
        starts.append((o.id or "main", at / first.rate, o.seconds))
        at += o.frames + len(gap)
    return Output("reel", f"{sfx.name}.reel", pcm, first.rate, info={"takes": starts})


def _write_reel(sfx: Sfx, output: Output, folder: Path, threshold_click: float) -> dict[str, Any]:
    wav = folder / f"{output.stem}.wav"
    wav.write_bytes(output.wav())
    analysis = analyze(output, "sfx")
    analysis["takes"] = [{"output": name, "start_s": round(start, 4), "seconds": round(seconds, 4)} for name, start, seconds in output.info["takes"]]
    rows = [str(i) for i in range(len(output.info["takes"]))]
    notes_ = [RollNote(i, start, start + seconds, name) for i, (name, start, seconds) in enumerate(output.info["takes"])]
    colours = {name: TRACK_COLOURS[i % len(TRACK_COLOURS)] for i, (name, _, _) in enumerate(output.info["takes"])}
    spec = SheetSpec(f"sfx {sfx.name}: reel of {len(rows)} takes, {REEL_GAP:g}s apart"[:150], level_stats(analysis, threshold_click),
                     output.audio, output.rate, tracks=[RollTrack("takes", rows, notes_, drums=True, colours=colours)])  # fmt: skip
    sheet = folder / f"{output.stem}.listen.png"
    listen_sheet(spec, None).save(sheet)
    return {"output": "reel", "wav": wav, "sheet": sheet, "analysis": analysis}


def walk_output(song: Any, render: Render, project: Project, seed: int) -> Output:
    """A seeded walk through a flow song's sections, from its flow clips (what the director plays)."""
    from segan.flowrender import path_reference, walk, walk_audio
    from segan.wavio import to_pcm16

    path = walk(song, seed)
    audio, starts = walk_audio(render.outputs, None, path)
    gain = float(render.main.level.get("gain_db") or 0.0)
    error = float(np.abs(path_reference(song, project, None, path, len(audio), gain) - audio).max())
    level = {"target": render.main.level.get("target")}
    return Output(f"walk:{seed}", f"{song.name}.walk{seed}", to_pcm16(audio), render.main.rate, None, starts, level, {"path": path, "join_error": error})


def _write_walk(song: Any, output: Output, folder: Path, threshold_click: float) -> dict[str, Any]:
    path: list[str] = output.info["path"]
    wav = folder / f"{output.stem}.wav"
    wav.write_bytes(output.wav())
    analysis = analyze(output, "song")
    audio = output.audio
    analysis["walk"] = path
    analysis["join_error"] = round(float(output.info["join_error"]), 6)
    ends = [at for _, at in output.cues[1:]] + [output.frames]
    blocks = [Block(name, at / output.rate, end / output.rate) for (name, at), end in zip(output.cues, ends, strict=True)]
    notes = [f"a walk through the flow (seed {output.id.split(':')[1]}): {' > '.join(path)}",
             f"clip joins: max difference from a straight render of this path {analysis['join_error']:g} of full scale "
             f"(limit {JOIN_ERROR:g}; 16-bit rounding and the limiter at clip edges); the last section rings out"]  # fmt: skip
    title = f"song {song.name} walk" + (f"  - {song.meta.description}" if song.meta.description else "")
    spec = SheetSpec(title[:150], level_stats(analysis, threshold_click), audio, output.rate, blocks=blocks, notes=notes)
    sheet = folder / f"{output.stem}.listen.png"
    listen_sheet(spec, analysis.get("target_lufs")).save(sheet)
    return {"output": output.id, "wav": wav, "sheet": sheet, "analysis": analysis}
