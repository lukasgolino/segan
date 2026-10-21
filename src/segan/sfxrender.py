"""SFX rendering: layers -> dry mono sound -> the shared bus -> loudness (by category) -> PCM.

Outputs: the main sound, one per variation (`<name>.<n>`), one per phase (`<name>.<phase>`). Loops
(`loop: true`, looping phases) blend their end into their start (`crossfade`) and get the room wrapped
around, so they repeat without a seam.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import replace

import numpy as np

from segan.analysis import SILENCE_DB, frames_of, max_momentary_lufs, peak_db, to_db
from segan.dsp import Signal, db_to_gain, exp2, seed_of, sin_turns, uniform
from segan.kitshow import context_for
from segan.mix import bus, finish, room_tail, trim_tail
from segan.patch import Env, Filter, Instrument
from segan.project import Project
from segan.render import Output, Render, level_dict
from segan.sfx import Layer, Sfx, Variations
from segan.synth import Context, note_length, render_note
from segan.wavio import to_pcm16

LOG2_10_OVER_20 = math.log2(10.0) / 20.0


def sfx_cache_parts(sfx: Sfx, project: Project) -> tuple[object, ...]:
    return ("sfx", sfx.name, sfx.category, sfx.duration, sfx.layers, sfx.loop, sfx.crossfade, sfx.variations,
            sorted(sfx.phases.items()), sfx.normalize, project.config.mix_for(sfx.category, sfx.room), project.config.target(sfx.category))  # fmt: skip


def _keyframe_curve(frames: tuple[tuple[float, float], ...], slide: bool, offset: float = 0.0):  # type: ignore[no-untyped-def]
    times = np.array([f[0] for f in frames])
    values = np.array([f[1] for f in frames]) - offset

    def curve(t: Signal) -> Signal:
        if slide:
            return np.asarray(np.interp(t, times, values), dtype=np.float64)
        index = np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(values) - 1)
        return np.asarray(values[index], dtype=np.float64)

    return curve


def _jitter(inst: Instrument, amount: float, seed: int) -> Instrument:
    """A variation's timbre: duty, filter cutoff, envelope times and drum tuning nudged by up to `amount`."""
    if amount <= 0:
        return inst

    def u(i: int) -> float:
        return uniform(seed, i) * 2.0 - 1.0

    env = inst.env
    scale = [1.0 + 0.4 * amount * u(i) for i in range(3)]
    changes: dict[str, object] = {
        "duty": min(0.95, max(0.05, inst.duty * (1.0 + 0.3 * amount * u(3)))),
        "env": Env(env.attack * scale[0], env.decay * scale[1], env.sustain, env.release * scale[2], env.curve),
    }
    if inst.filter is not None:
        changes["filter"] = replace(inst.filter, cutoff=min(20000.0, inst.filter.cutoff * 2.0 ** (amount * u(4))))
    if inst.is_drum:
        drum = dict(inst.drum)
        drum["tune"] = inst.drum_param("tune") * 2.0 ** (0.25 * amount * u(5))
        drum["decay"] = inst.drum_param("decay") * (1.0 + 0.3 * amount * u(6))
        changes["drum"] = drum
    return replace(inst, **changes)  # type: ignore[arg-type]


def _effects(x: Signal, layer: Layer, rate: int, length: int, post_gain: Callable[[int], Signal | float] | None = None) -> Signal:
    """distort -> `post_gain` (a distorted layer's gain, so gain stays balance, not timbre) -> ring -> delay."""
    out = x
    if layer.distort > 0:
        drive = 1.0 + 15.0 * layer.distort
        y = np.clip(out * drive, -1.5, 1.5)
        out = (y - y**3 / 6.75) / max(1.0, drive**0.5)
    if post_gain is not None:
        out = out * post_gain(len(out))
    if layer.ring is not None:
        freq, mix = layer.ring
        t = np.arange(len(out)) / rate
        out = out * (1.0 - mix) + out * sin_turns(t * freq) * mix
    if layer.delay is not None:
        time, feedback, mix = layer.delay
        step = round(time * rate)
        echo = np.zeros(max(length, len(out)))
        echo[: len(out)] += out
        gain = mix
        k = 1
        while gain > 1e-3 and k * step < len(echo) and k <= 64:
            seg = out[: len(echo) - k * step]
            echo[k * step : k * step + len(seg)] += seg * gain
            gain *= feedback
            k += 1
        out = echo
    return out[:length]


def render_layer(layer: Layer, ctx: Context, available: float, seed: int, pitch_offset: float, timbre: float) -> tuple[Signal, bool]:
    """One layer at the output rate, at most `available` seconds long; and whether it was still sounding
    when it got cut off (W011)."""
    inst = _jitter(layer.inst, timbre, seed_of(seed, "timbre"))
    if layer.length is not None and inst.sample is not None and inst.sample.one_shot is not False:
        inst = replace(inst, sample=replace(inst.sample, one_shot=False))  # an explicit length chokes a one-shot (then its release)
    gate = layer.length if layer.length is not None else max(0.001, available - layer.start - inst.tail())
    base = layer.base_midi()
    pitch_curve = None
    if (layer.pitch and len(layer.pitch) > 1) or pitch_offset:
        frames = layer.pitch or ((0.0, base),)
        keyed = _keyframe_curve(frames, layer.slide, base)
        pitch_curve = (lambda t: keyed(t) + pitch_offset) if pitch_offset else keyed
    gain_curve = None
    if layer.gain:
        db = _keyframe_curve(layer.gain, True)
        gain_curve = lambda t: exp2(db(t) * LOG2_10_OVER_20)  # noqa: E731
    post_gain = None
    if layer.distort > 0:  # the layer's gain comes after the distortion: changing it mustn't change the timbre
        level, curve = db_to_gain(inst.gain), gain_curve
        inst, gain_curve = replace(inst, gain=0.0), None
        post_gain = lambda n: level * (curve(np.arange(n) / ctx.rate) if curve is not None else 1.0)  # noqa: E731
    cutoff_curve = None
    if layer.cutoff:
        if inst.filter is None:
            inst = replace(inst, filter=Filter("lp", layer.cutoff[0][1]))
        assert inst.filter is not None
        reference = inst.filter.cutoff
        hz = _keyframe_curve(layer.cutoff, True)
        cutoff_curve = lambda t: hz(t) / reference  # noqa: E731
    full = note_length(inst, gate, ctx, base)
    room = available - layer.start
    if room <= 0:
        return np.zeros(0), False
    sounding = full > room + 1e-3
    length = min(full, room) if layer.delay is None else room
    signal = render_note(inst, ctx, base, gate, 1.0, seed, pitch_curve, gain_curve, cutoff_curve, length=min(full, room))
    signal = _effects(signal, layer, ctx.rate, round(length * ctx.rate), post_gain)
    if sounding and ctx.declick:
        fade = min(len(signal), round(0.003 * ctx.rate))
        if fade:
            signal = signal.copy()
            signal[-fade:] *= np.linspace(1.0, 0.0, fade, endpoint=False) ** 2
    return signal, sounding


def dry_mix(layers: tuple[Layer, ...], ctx: Context, duration: float, name: str, variation: int, pitch_offset: float,
            timbre: float, loop: bool, crossfade: float) -> tuple[Signal, list[str]]:  # fmt: skip
    """All layers summed (mono). Loops render `crossfade` extra seconds and blend them into the start."""
    available = duration + (crossfade if loop else 0.0)
    total = round(available * ctx.rate)
    out = np.zeros(total)
    sounding: list[str] = []
    for layer in layers:
        signal, still = render_layer(layer, ctx, available, seed_of(name, layer.index, variation), pitch_offset, timbre)
        start = round(layer.start * ctx.rate)
        piece = signal[: max(0, total - start)]
        out[start : start + len(piece)] += piece
        if still and not loop:
            sounding.append(layer.id or f"layers.{layer.index}")
    if loop:
        frames = round(duration * ctx.rate)
        fade = total - frames
        if fade > 0:
            phase = np.arange(fade) / fade / 4.0  # quarter turn: equal-power blend
            head = out[:fade] * sin_turns(phase) + out[frames:] * sin_turns(phase + 0.25)
            out = out[:frames].copy()
            out[:fade] = head
        else:
            out = out[:frames]
    return out, sounding


def _finish_output(dry: Signal, sfx: Sfx, project: Project, loop: bool, gain_offset: float = 0.0) -> tuple[Signal, dict[str, float | None]]:
    mix = project.config.mix_for(sfx.category, sfx.room)
    rate = mix.sample_rate
    channels = 2 if mix.sfx_channels == "stereo" else 1
    data = np.repeat(dry[:, None], channels, axis=1)
    frames = len(data)
    if loop and frames:
        twice = bus(np.concatenate([data, data, data]), mix)  # the room of the previous cycle rings into this one
        wet = twice[frames : 2 * frames]
    else:
        wet = trim_tail(bus(data, mix), frames, rate, mix.tail_trim_db) if mix.room > 0 else bus(data, mix)
    target = project.config.target(sfx.category) + gain_offset if sfx.normalize else None
    if target is None and gain_offset:
        wet = wet * 2.0 ** (gain_offset * LOG2_10_OVER_20)
    final, level, _ = finish(wet, rate, target, "momentary", mix.limiter, project.config.lint.max_limiting_db)
    return final, level_dict(level)


def render_sfx(sfx: Sfx, project: Project) -> Render:
    ctx = context_for(project.config.mix)
    outputs: list[Output] = []

    def emit(output_id: str, stem: str, layers: tuple[Layer, ...], duration: float, loop: bool, crossfade: float,
             variation: int = 0, pitch: float = 0.0, timbre: float = 0.0, gain: float = 0.0) -> None:  # fmt: skip
        dry, sounding = dry_mix(layers, ctx, duration, sfx.name, variation, pitch, timbre, loop, crossfade)
        final, level = _finish_output(dry, sfx, project, loop, gain)
        pcm = to_pcm16(frames_of(final))
        if loop and len(pcm):
            # Loops start one frame in: the file opens with the loop's last frame, so players that (like Godot)
            # wrap to the frame after loop_begin still hear every frame of the loop exactly once.
            pcm = np.concatenate([pcm[-1:], pcm])
        info = {"sounding_at_end": sounding, "duration": duration, "variation": variation, "pitch_offset": pitch,
                "loop": loop, "dry_frames": len(dry), "room_tail": room_tail(project.config.mix_for(sfx.category, sfx.room))}  # fmt: skip
        outputs.append(Output(output_id, stem, pcm, ctx.rate, (1, len(pcm)) if loop else None, [], level, info))

    if sfx.layers:
        emit("", sfx.name, sfx.layers, sfx.duration, sfx.loop, sfx.crossfade)
        if sfx.variations is not None:
            for i, (pitch, timbre, gain) in enumerate(variation_params(sfx.name, sfx.variations), start=1):
                layers = variation_layers(sfx.name, sfx.layers, sfx.variations, i)
                emit(f"variation:{i}", f"{sfx.name}.{i}", layers, sfx.duration, sfx.loop, sfx.crossfade, i, pitch, timbre, gain)
    for phase in sfx.phases.values():
        emit(f"phase:{phase.name}", f"{sfx.name}.{phase.name}", phase.layers, phase.duration, phase.loop, phase.crossfade)
    return Render(sfx.name, "sfx", outputs)


def layer_levels(sfx: Sfx, project: Project, output_id: str) -> list[dict[str, object]]:
    """Each layer of one output on its own, dry (before the room, normalisation and the limiter), at its place in
    the sound: peak, loudness (loudest 400 ms) and crest factor (peak over RMS while it sounds), plus the dry sum.
    Which layer makes a sound peaky shows as the highest peak for its loudness (W001)."""
    ctx = context_for(project.config.mix)
    variation, pitch, timbre = 0, 0.0, 0.0
    layers, duration, loop, crossfade = sfx.layers, sfx.duration, sfx.loop, sfx.crossfade
    if output_id.startswith("phase:"):
        phase = sfx.phases[output_id.split(":", 1)[1]]
        layers, duration, loop, crossfade = phase.layers, phase.duration, phase.loop, phase.crossfade
    elif output_id.startswith("variation:") and sfx.variations is not None:
        variation = int(output_id.split(":", 1)[1])
        pitch, timbre, _ = variation_params(sfx.name, sfx.variations)[variation - 1]
        layers = variation_layers(sfx.name, layers, sfx.variations, variation)
    available = duration + (crossfade if loop else 0.0)
    total = round(available * ctx.rate)

    def levels(x: Signal) -> dict[str, float]:
        sounding = x[np.abs(x) > 0]
        rms = float(np.sqrt(np.mean(sounding**2))) if len(sounding) else 0.0
        peak = peak_db(x)
        return {"peak_db": round(peak, 2), "lufs": round(max_momentary_lufs(x, ctx.rate), 2),
                "crest_db": round(peak - to_db(rms), 2) if rms > 0 else 0.0}  # fmt: skip

    out: list[dict[str, object]] = []
    dry = np.zeros(total)
    for layer in layers:
        signal, _ = render_layer(layer, ctx, available, seed_of(sfx.name, layer.index, variation), pitch, timbre)
        start = round(layer.start * ctx.rate)
        placed = np.zeros(total)
        piece = signal[: max(0, total - start)]
        placed[start : start + len(piece)] = piece
        dry += placed
        out.append({"layer": layer.id or f"layers.{layer.index}", "start_s": layer.start, **levels(placed)})
    out.append({"layer": "(dry mix)", "start_s": 0.0, **(levels(dry) if total else {"peak_db": SILENCE_DB, "lufs": SILENCE_DB, "crest_db": 0.0})})
    return out


def variation_layers(name: str, layers: tuple[Layer, ...], v: Variations, variation: int) -> tuple[Layer, ...]:
    """The layers of one variation: with `timing`, each layer's start moves by up to +/- timing seconds (seeded per
    layer, never before 0), so bursts and bubbles don't land at the same moments in every variation."""
    if not v.timing:
        return layers
    out = []
    for layer in layers:
        jitter = (uniform(seed_of(name, "variation", v.seed, variation, "timing", layer.index), 0) * 2 - 1) * v.timing
        out.append(replace(layer, start=round(max(0.0, layer.start + jitter), 6)))
    return tuple(out)


def variation_params(name: str, v: Variations) -> list[tuple[float, float, float]]:
    """(pitch offset in semitones, timbre amount, gain offset in dB) per variation, from the seed."""
    out = []
    for i in range(1, v.count + 1):
        seed = seed_of(name, "variation", v.seed, i)
        out.append(((uniform(seed, 0) * 2 - 1) * v.pitch, v.timbre, (uniform(seed, 1) * 2 - 1) * v.gain))
    return out
