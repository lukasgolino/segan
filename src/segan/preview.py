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
from segan.dsp import midi_to_hz_scalar
from segan.listen import BAD, DIM, GOOD, TEXT, TRACK_COLOURS, WARN, RollNote, RollTrack, SheetSpec, listen_sheet, seam_sheet
from segan.project import Project
from segan.render import Output, Render
from segan.sfx import Layer, Sfx

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
                  only: list[str] | None = None) -> PreviewResult:  # fmt: skip
    """WAV + listen sheet (+ seam view for loops) per output into <preview_dir>/<asset>/."""
    folder = project.preview_dir / asset.name
    folder.mkdir(parents=True, exist_ok=True)
    result = PreviewResult(asset.name, folder)
    click = project.config.lint.max_seam_click
    for output in render.outputs:
        if only and not {output.id or "main", output.stem} & set(only):
            continue
        if not only and output.id.startswith(("stem:", "mix:")):
            continue  # stems are build outputs; preview them with --output stem:<name> / mix:<name>
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
    return result
