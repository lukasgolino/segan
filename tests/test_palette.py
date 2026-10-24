"""#76 palette: instrument models, FM operators, sync, sub, mutes, filter LFO, new drums and per-instrument effects."""

from typing import Any

import numpy as np
import pytest

from segan.analysis import yin
from segan.dsp import midi_to_hz_scalar
from segan.fx import apply_fx, note_value
from segan.kitshow import aliasing_of
from segan.patch import Instrument, Report, parse_patch
from segan.synth import Context, render_note
from segan.voices import NoteEvent, event_end, render_events

from conftest import load, rules

CTX = Context(rate=22050, oversample=2)


def patch(data: dict[str, Any]) -> Instrument:
    report = Report(None)
    inst = parse_patch(data, report, "E005", "x")
    assert inst is not None, [f.message for f in report.findings]
    return inst


def errors(data: dict[str, Any]) -> list[str]:
    report = Report(None)
    assert parse_patch(data, report, "E005", "x") is None
    return [f.message for f in report.findings]


def pitch(x: np.ndarray, rate: int = 22050) -> float:
    found = yin(x, rate)
    return float(np.median(found.hz[found.hz > 0]))


PITCHED = {
    "pluck": {"osc": "pluck"},
    "pluck_preset": {"osc": "pluck", "pluck": "nylon"},
    "bowed": {"osc": "bowed", "unison": 4, "detune": 5, "env": [0.1, 0, 1, 0.2]},
    "bowed_cello": {"osc": "bowed", "bowed": {"body": "cello", "bow": 0.5}},
    "wavetable": {"osc": "wavetable", "wavetable": {"table": "vocal", "lfo": [0.5, 1.0]}},
    "formant": {"osc": "formant", "formant": {"vowel": ["ah", "oh"], "voice": "tenor"}, "unison": 3, "detune": 6},
    "modal": {"osc": "modal", "modal": "marimba"},
    "supersaw": {"osc": "supersaw"},
    "fm_ops": {"osc": "fm", "fm": {"algorithm": "stack", "ops": [{"ratio": 1}, {"ratio": 2, "index": 1.5}, {"ratio": 7, "index": 0.4}]}},
    "sync": {"osc": "pulse", "sync": 2.6},
    "mute": {"osc": "saw", "mute": "cup"},
    "filter_lfo": {"osc": "saw", "filter": {"cutoff": 900, "slope": 24, "resonance": 0.4, "lfo": [2, 2]}},
}


@pytest.mark.parametrize("name", list(PITCHED))
def test_models_play_the_written_pitch(name: str) -> None:
    inst = patch(PITCHED[name])
    x = render_note(inst, CTX, 57.0, 1.0)
    assert np.isfinite(x).all() and 0.05 < np.abs(x).max() < 4.0
    assert abs(pitch(x) / 220.0 - 1.0) < 0.02


def test_renders_are_deterministic() -> None:
    for data in PITCHED.values():
        inst = patch(data)
        assert np.array_equal(render_note(inst, CTX, 60.0, 0.4, seed=3), render_note(inst, CTX, 60.0, 0.4, seed=3))


def test_sub_oscillator_adds_the_octave_below() -> None:
    inst = patch({"osc": "sine", "sub": {"octave": -1, "level": 0}})
    assert abs(pitch(render_note(inst, CTX, 57.0, 1.0)) - 110.0) < 2.0


def test_additive_drawbars_and_presets() -> None:
    organ = patch({"osc": "additive", "additive": {"drawbars": "008000000"}})  # the 8' bar alone: a sine at the note
    assert abs(pitch(render_note(organ, CTX, 69.0, 0.5)) - 440.0) < 3.0
    bell = patch({"osc": "additive", "additive": "bell"})
    x = render_note(bell, CTX, 72.0, 0.2, length=3.0)
    early, late = np.abs(x[:4000]).max(), np.abs(x[-4000:]).max()
    assert late < early * 0.5  # partials with a decay ring out


def test_pluck_decays_and_high_notes_die_faster() -> None:
    inst = patch({"osc": "pluck", "pluck": {"decay": 1.0}, "env": [0.001, 0, 1, 0.1]})
    low, high = (render_note(inst, CTX, m, 2.0, length=2.0) for m in (48.0, 84.0))
    for x in (low, high):
        assert np.abs(x[-2000:]).max() < np.abs(x[:2000]).max() * 0.1
    assert np.abs(high[11025:13000]).max() / np.abs(high[:2000]).max() < np.abs(low[11025:13000]).max() / np.abs(low[:2000]).max()


def test_model_defaults_hold_then_damp() -> None:
    assert patch({"osc": "pluck"}).env.sustain == 1.0 and patch({"osc": "modal"}).env.release == 1.0


def test_new_drums_render() -> None:
    for drum in ("rim", "shaker", "cowbell", "block", "conga", "brush", "metal"):
        x = render_note(patch({"drum": drum}), CTX, 60.0, 0.05)
        assert np.isfinite(x).all() and np.abs(x).max() > 0.05, drum


def test_model_errors_say_what_to_write() -> None:
    assert "need osc: modal" in errors({"osc": "saw", "modal": "glass"})[0]
    assert "marimba" in errors({"osc": "modal", "modal": "plastic"})[0]
    assert "preset" in errors({"osc": "pluck", "pluck": "banjo"})[0]
    assert "vowel" in errors({"osc": "formant", "formant": "x"})[0]
    assert "drawbars" in errors({"osc": "additive", "additive": {"drawbars": "999"}})[0]
    assert "mod must list operators after it" in errors({"osc": "fm", "fm": {"ops": [{"ratio": 1}, {"ratio": 2, "mod": [1]}]}})[0]
    assert "saw or pulse" in errors({"osc": "sine", "sync": 2})[0]
    assert "harmon" in errors({"osc": "saw", "mute": "wah"})[0]
    assert "slope" in errors({"osc": "saw", "filter": {"slope": 18}})[0]


def test_aliasing_check_skips_inharmonic_models_and_measures_the_rest() -> None:
    assert aliasing_of(patch({"osc": "modal"}), 84, CTX) is None
    assert aliasing_of(patch({"osc": "pluck"}), 84, CTX) is None
    value = aliasing_of(patch({"osc": "wavetable", "wavetable": "analog"}), 84, Context(oversample=2))
    assert value is not None and value < -50


# --- effects ---------------------------------------------------------------------------------


def test_note_values() -> None:
    assert note_value("1/4") == 1.0 and note_value("1/8.") == 0.75 and abs(note_value("1/8t") - 1 / 3) < 1e-12  # type: ignore[operator]
    assert note_value("2") == 8.0 and note_value("1/3") is None and note_value("x") is None


def test_fx_errors() -> None:
    assert "one of chorus" in errors({"osc": "saw", "fx": [{"wobble": {}}]})[0]
    assert "delay.time must be" in errors({"osc": "saw", "fx": [{"delay": {"time": "1/7"}}]})[0]
    assert "settings must be a mapping" in errors({"osc": "saw", "fx": [{"chorus": {"speed": 1}}]})[0]


def test_every_effect_runs_and_stereo_ones_widen() -> None:
    x = render_note(patch({"osc": "saw"}), CTX, 57.0, 0.3)
    for kind in ("chorus", "ensemble", "flanger", "phaser", "delay", "reverb", "drive", "crush", "comb", "ring", "tremolo", "autopan", "filter"):
        inst = patch({"osc": "saw", "fx": [kind]})
        mono = apply_fx(x, inst.fx, 22050, 0.5, 1, 57.0)
        stereo = apply_fx(x, inst.fx, 22050, 0.5, 2, 57.0)
        assert mono.ndim == 1 and np.isfinite(mono).all() and np.isfinite(stereo).all(), kind
        if kind in ("chorus", "ensemble", "autopan", "reverb"):
            assert stereo.ndim == 2 and not np.allclose(stereo[:, 0], stereo[:, 1]), kind


def test_delay_follows_the_tempo_and_rings_past_the_note() -> None:
    inst = patch({"osc": "sine", "env": [0.001, 0.0, 1.0, 0.01], "fx": [{"delay": {"time": "1/4", "feedback": 0.0, "mix": 1.0}}]})
    slow = NoteEvent("t", "p", inst, 0, 0.05, 69.0, beat=0.5)
    fast = NoteEvent("t", "p", inst, 0, 0.05, 69.0, beat=0.25)
    assert event_end(slow, CTX) > event_end(fast, CTX) > round(0.25 * 22050)
    out = render_events([slow], CTX, 1)["t"][:, 0]
    echo = np.abs(out[round(0.5 * 22050) : round(0.6 * 22050)]).max()
    assert echo > 0.3 * np.abs(out[:2000]).max()  # the echo lands one quarter note (0.5 s) later


def test_songs_with_models_and_fx_lint_clean(project: Any) -> None:
    (project.kits_dir / "m.kit.yaml").write_text("""\
name: m
instruments:
  g: { name: guitar, osc: pluck, pluck: nylon, voices: 4, range: [E2, E5], fx: [{ chorus: { mix: 0.3 } }] }
  v: { name: strings, osc: bowed, unison: 4, detune: 5, voices: 4, env: [0.2, 0, 1, 0.4], range: [G2, E6], fx: [ensemble] }
  c: { name: choir, osc: formant, formant: { vowel: [ah, oh] }, unison: 3, voices: 3, env: [0.3, 0, 1, 0.5], range: [C3, C5] }
  b: { name: marimba, osc: modal, modal: marimba, voices: 4, range: [C3, C6], fx: [{ delay: { time: "1/8.", feedback: 0.3, mix: 0.25 } }] }
  k: { name: kick, drum: kick }
  r: { name: rim, drum: rim }
  s: { name: shaker, drum: shaker }
""")
    song, findings = load(project, "song", "cue", """\
name: cue
kit: m
tempo: 96
key: D dorian
tracks:
  mel: { roll: [D4, D5] }
  bed: { roll: [D3, D4] }
  perc: { drums: [k, r, s] }
patterns:
  a:
    length: 16
    mel: |
      ................  D5
      ................  C5
      ........b.......  B4
      ................  A4
      ....b...........  G4
      ................  F4
      ................  E4
      b.......g-------  D4
    bed: |
      ................  D4
      ................  C4
      ................  B3
      v---------------  A3
      ................  G3
      c---------------  F3
      ................  E3
      ................  D3
    perc: |
      x.......x.......  k
      ....x.......x...  r
      x.x.x.x.x.x.x.x.  s
sections: { main: [a, a] }
arrangement: [main]
loop: main
""")
    assert song is not None, findings
    from segan.lint import lint_paths

    result = lint_paths(project, [project.music_dir / "cue.song.yaml"])
    assert not result.errors and "W007" not in rules(result.findings) and "W004" not in rules(result.findings), result.findings
    assert midi_to_hz_scalar(69.0) == 440.0
