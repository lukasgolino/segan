"""Recorded SFX: stretch/shift DSP, the licence rule, recorded layers, sounds.lock and Freesound (mocked: no network)."""

from __future__ import annotations

import io
import json
import urllib.parse
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from segan.analysis import yin
from segan.licences import classify
from segan.project import Project, load_project
from segan.samples import Processing
from segan.stretch import stretch
from segan.wavio import wav_bytes

from conftest import CONFIG, load, make_project, run_json, write

RATE = 22050


def tone(freq: float, seconds: float, rate: int = RATE) -> np.ndarray:
    t = np.arange(round(seconds * rate)) / rate
    return 0.5 * np.sin(2 * np.pi * freq * t) * np.minimum(1.0, t * 50)


def write_wav(path: Path, x: np.ndarray, rate: int = RATE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype(np.int16)
    path.write_bytes(wav_bytes(pcm[:, None], rate))
    return path


def sfx_of(project: Project, name: str, text: str) -> Any:
    sfx, findings = load(project, "sfx", name, text)
    assert sfx is not None, [f.format() for f in findings]
    return sfx


def median_hz(x: np.ndarray, rate: int = RATE) -> float:
    track = yin(x, rate, hop=0.01)
    return float(np.median(track.hz[track.hz > 0]))


# --- DSP ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("factor", "semitones"), [(1.0, 0.0), (2.0, 0.0), (0.5, 0.0), (1.0, -12.0), (1.0, 7.0), (1.5, -5.0), (3.0, -24.0)])
def test_stretch_changes_length_and_pitch_independently(factor: float, semitones: float) -> None:
    x = tone(440.0, 1.0)
    y = stretch(x, RATE, factor, semitones)
    assert len(y) == round(len(x) * factor)
    assert median_hz(y) == pytest.approx(440.0 * 2 ** (semitones / 12), rel=0.01)
    middle = y[len(y) // 4 : 3 * len(y) // 4]
    assert np.sqrt(np.mean(middle**2)) == pytest.approx(0.5 / np.sqrt(2), rel=0.1)  # level kept (no phasing holes)


def test_stretch_is_deterministic() -> None:
    x = tone(330.0, 0.5) + 0.1 * np.sin(np.arange(round(0.5 * RATE)) * 0.37)
    assert np.array_equal(stretch(x, RATE, 1.37, -3.5), stretch(x, RATE, 1.37, -3.5))


# --- licences ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "licence"),
    [
        ("CC0", "CC0-1.0"),
        ("cc0-1.0", "CC0-1.0"),
        ("Creative Commons 0", "CC0-1.0"),
        ("http://creativecommons.org/publicdomain/zero/1.0/", "CC0-1.0"),
        ("CC-BY-4.0", "CC-BY-4.0"),
        ("CC BY 3.0", "CC-BY-3.0"),
        ("cc-by-4", "CC-BY-4.0"),
        ("Attribution", "CC-BY"),
        ("https://creativecommons.org/licenses/by/4.0/", "CC-BY-4.0"),
        ("http://creativecommons.org/licenses/by/3.0/", "CC-BY-3.0"),
        ("https://creativecommons.org/licenses/by/4.0/legalcode", "CC-BY-4.0"),
        ("CC-BY-NC-4.0", None),
        ("Attribution NonCommercial", None),
        ("http://creativecommons.org/licenses/by-nc/3.0/", None),
        ("https://creativecommons.org/licenses/by-sa/4.0/", None),
        ("http://creativecommons.org/licenses/sampling+/1.0/", None),
        ("public domain", None),
        ("", None),
        (None, None),
    ],
)
def test_licence_rule(text: Any, licence: str | None) -> None:
    found = classify(text)
    assert (found.id if found else None) == licence


# --- recorded layers ---------------------------------------------------------------------------------

RECORDED = """\
name: roar
duration: 1.5
layers:
  - id: rec
    sample: sounds/roar.wav
    licence: CC0
    source: https://example.org/roar
    shift: -5
    stretch: 1.2
    fade: [0.01, 0.2]
  - id: sub
    osc: sine
    pitch: C2
    env: [0.01, 0.3, 0.0, 0.1]
"""


@pytest.fixture
def rec_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    write_wav(tmp_path / "sounds" / "roar.wav", tone(220.0, 1.0))
    write_wav(tmp_path / "sounds" / "other.wav", tone(330.0, 0.6))
    return project


def test_recorded_layer_renders_with_synth_layers(rec_project: Project) -> None:
    from segan.sfxrender import render_sfx

    sfx = sfx_of(rec_project, "roar", RECORDED)
    rec = sfx.layers[0]
    assert rec.choices and rec.choices[0].kind == "rec" and rec.inst.describe() == "recording roar.wav"
    assert rec.choices[0].process == Processing(0.0, None, False, 1.2, -5.0, 0.01, 0.2)
    assert rec.recorded[0].licence == "CC0-1.0" and rec.recorded[0].source == "https://example.org/roar"
    render = render_sfx(sfx, rec_project)
    pcm = render.outputs[0].pcm
    assert np.abs(pcm).max() > 1000
    assert np.array_equal(pcm, render_sfx(sfx, rec_project).outputs[0].pcm)


def test_recorded_layer_plays_shifted_not_slowed(rec_project: Project) -> None:
    from segan.sfxrender import dry_mix
    from segan.kitshow import context_for

    text = "name: r\nduration: 1.5\nroom: 0\nlayers:\n  - sample: sounds/roar.wav\n    licence: CC0\n    source: x\n    shift: -12\n"
    sfx = sfx_of(rec_project, "r", text)
    dry, _ = dry_mix(sfx.layers, context_for(rec_project.config.mix), 1.5, "r", 0, 0.0, 0.0, False, 0.0)
    rate = rec_project.config.mix.sample_rate
    loud = np.flatnonzero(np.abs(dry) > 0.01)
    assert (loud[-1] - loud[0]) / rate == pytest.approx(1.0, abs=0.05)  # same length as recorded
    assert median_hz(dry, rate) == pytest.approx(110.0, rel=0.02)  # an octave down


def test_processing_trim_reverse_fade(rec_project: Project) -> None:
    from segan.recorded import processed

    ramp = np.linspace(0.0, 0.9, RATE)
    path = str(write_wav(rec_project.root / "sounds" / "ramp.wav", ramp))
    plain = processed(path, Processing(trim_start=0.25, trim_end=0.75))
    assert abs(len(plain) - RATE // 2) <= 1 and plain[-1] == pytest.approx(1.0) and plain[0] < plain[-1]  # peak-normalised
    backwards = processed(path, Processing(trim_start=0.25, trim_end=0.75, reverse=True))
    assert backwards[0] == pytest.approx(1.0) and backwards[-1] < backwards[0]
    faded = processed(path, Processing(fade_in=0.1, fade_out=0.1))
    assert faded[0] == 0.0 and faded[-1] == 0.0 and faded[RATE // 2] > 0.4


def test_a_list_picks_one_file_per_variation(rec_project: Project) -> None:
    from segan.sfxrender import render_layer
    from segan.kitshow import context_for
    from segan.dsp import seed_of

    text = ("name: pick\nduration: 1.0\nlayers:\n  - sample: [sounds/roar.wav, sounds/other.wav]\n    licence: CC0\n    source: x\n"
            "variations: { count: 8 }\n")  # fmt: skip
    sfx = sfx_of(rec_project, "pick", text)
    layer = sfx.layers[0]
    assert len(layer.choices) == 2
    ctx = context_for(rec_project.config.mix)
    picked = []
    for variation in range(9):
        signal, _ = render_layer(layer, ctx, 1.0, seed_of("pick", 0, variation), 0.0, 0.0)
        picked.append(round(median_hz(signal, ctx.rate)))
        again, _ = render_layer(layer, ctx, 1.0, seed_of("pick", 0, variation), 0.0, 0.0)
        assert np.array_equal(signal, again)
    assert set(picked) == {220, 330}


@pytest.mark.parametrize(
    ("fields", "rule", "message"),
    [
        ("", "E020", "has no licence"),
        ("    licence: CC-BY-NC-4.0\n    source: x\n", "E020", "isn't allowed"),
        ("    licence: CC-BY-SA-4.0\n    source: x\n", "E020", "isn't allowed"),
        ("    licence: CC-BY-4.0\n    source: x\n", "E020", "add author"),
        ("    licence: CC0\n", "E020", "add source"),
        ("    licence: CC0\n    license: CC0\n    source: x\n", "E013", "not both"),
        ("    licence: CC0\n    source: x\n    stretch: 9\n", "E013", "stretch"),
        ("    licence: CC0\n    source: x\n    osc: saw\n", "E013", "drop osc"),
    ],
)
def test_recorded_layer_errors(rec_project: Project, fields: str, rule: str, message: str) -> None:
    from segan.sfx import load_sfx

    path = write(rec_project, "sfx", "bad", f"name: bad\nduration: 1\nlayers:\n  - sample: sounds/roar.wav\n{fields}")
    sfx, findings = load_sfx(path, rec_project)
    assert sfx is None
    assert any(f.rule == rule and message in f.message for f in findings), [f.format() for f in findings]


def test_recorded_fields_need_a_recording(rec_project: Project) -> None:
    from segan.sfx import load_sfx

    path = write(rec_project, "sfx", "bad", "name: bad\nduration: 1\nlayers:\n  - osc: saw\n    shift: 3\n")
    _, findings = load_sfx(path, rec_project)
    assert any(f.rule == "E013" and "only for recorded layers" in f.message for f in findings)
    path = write(rec_project, "sfx", "bad", "name: bad\nduration: 1\nlayers:\n  - sample: sounds/nope.wav\n    licence: CC0\n    source: x\n")
    _, findings = load_sfx(path, rec_project)
    assert any(f.rule == "E019" and "not found" in f.message for f in findings)


def test_w020_when_the_project_is_synth_only(tmp_path: Path) -> None:
    from segan.lint import lint_paths

    project = make_project(tmp_path, CONFIG + '\n[sfx]\nsource = "synth"\n')
    write_wav(tmp_path / "sounds" / "roar.wav", tone(220.0, 1.0))
    write(project, "sfx", "roar", RECORDED)
    result = lint_paths(load_project(tmp_path), render=False)
    assert [f.rule for f in result.findings] == ["W020"]


# --- sounds.lock, credits, vendor --------------------------------------------------------------------


def test_add_a_local_file_and_use_its_lock_entry(rec_project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from segan.sfx import load_sfx

    monkeypatch.chdir(rec_project.root)
    code, data = run_json(["sounds", "add", "sounds/roar.wav", "--licence", "CC-BY-4.0", "--source", "https://example.org/roar"], capsys)
    assert code == 1 and "--author is required" in data["findings"][0]["message"]
    code, data = run_json(["sounds", "add", "sounds/roar.wav", "--licence", "CC-BY-NC-4.0", "--source", "x", "--author", "a"], capsys)
    assert code == 1 and "isn't allowed" in data["findings"][0]["message"]
    code, data = run_json(["sounds", "add", "./sounds/roar.wav", "--licence", "CC-BY-4.0", "--source", "https://example.org/roar", "--author", "Ann"], capsys)
    assert code == 0 and data["ref"] == "sounds/roar.wav" and data["entry"]["licence"] == "CC-BY-4.0"
    path = write(rec_project, "sfx", "roar", "name: roar\nduration: 1\nlayers:\n  - sample: sounds/roar.wav\n")
    sfx, findings = load_sfx(path, rec_project)
    assert sfx is not None, [f.format() for f in findings]
    assert sfx.layers[0].recorded[0].author == "Ann"
    code, data = run_json(["sounds", "credits"], capsys)
    assert code == 0 and data["attribution_required"] == ["sounds/roar.wav"]
    credits = (rec_project.root / "SOUND_CREDITS.md").read_text()
    assert '"roar" by Ann (https://example.org/roar), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).' in credits
    assert "Used in: roar." in credits and "Modified" in credits
    write_wav(rec_project.root / "sounds" / "roar.wav", tone(225.0, 1.0))  # changed after it was locked
    _, findings = load_sfx(path, rec_project)
    assert any(f.rule == "E019" and "sha256" in f.message for f in findings)


# --- Freesound (mocked) ------------------------------------------------------------------------------


def ogg_bytes(x: np.ndarray, rate: int = RATE) -> bytes:
    import soundfile

    buffer = io.BytesIO()
    soundfile.write(buffer, x, rate, format="OGG", subtype="VORBIS")
    return buffer.getvalue()


def sound_record(sound_id: int, licence: str, name: str = "Lion roar") -> dict[str, Any]:
    """A sound as /apiv2/search/ and /apiv2/sounds/<id>/ return it with our `fields` (shapes from the API docs)."""
    base = f"https://cdn.freesound.org/previews/{sound_id // 1000}/{sound_id}_42"
    return {
        "id": sound_id,
        "name": name,
        "username": "roarer",
        "license": licence,
        "duration": 1.0,
        "avg_rating": 4.25,
        "num_ratings": 12,
        "tags": ["lion", "roar", "animal"],
        "url": f"https://freesound.org/people/roarer/sounds/{sound_id}/",
        "previews": {
            "preview-hq-ogg": f"{base}-hq.ogg",
            "preview-lq-ogg": f"{base}-lq.ogg",
            "preview-hq-mp3": f"{base}-hq.mp3",
            "preview-lq-mp3": f"{base}-lq.mp3",
        },
    }


class FakeFreesound:
    def __init__(self) -> None:
        self.sounds = {
            101: sound_record(101, "https://creativecommons.org/licenses/by/4.0/"),
            102: sound_record(102, "http://creativecommons.org/publicdomain/zero/1.0/", "Big cat growl"),
            103: sound_record(103, "http://creativecommons.org/licenses/by-nc/3.0/", "NC roar"),
        }
        self.audio = {101: ogg_bytes(tone(220.0, 1.0)), 102: ogg_bytes(tone(110.0, 1.0)), 103: ogg_bytes(tone(440.0, 1.0))}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, request: Any, timeout: float = 0) -> Any:
        url = request.full_url
        self.requests.append((url, dict(request.header_items())))
        parsed = urllib.parse.urlparse(url)
        if parsed.path == "/apiv2/search/":
            body: bytes = json.dumps({"count": 3, "next": None, "previous": None, "results": list(self.sounds.values())}).encode()
        elif parsed.path.startswith("/apiv2/sounds/"):
            body = json.dumps(self.sounds[int(parsed.path.split("/")[3])]).encode()
        else:
            body = self.audio[int(Path(parsed.path).name.split("_")[0])]
        return io.BytesIO(body)


@pytest.fixture
def freesound(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeFreesound:
    from segan import sounds

    fake = FakeFreesound()
    monkeypatch.setattr(sounds, "_urlopen", fake)
    monkeypatch.setenv("FREESOUND_API_KEY", "k3y")
    monkeypatch.setenv("SEGAN_SOUNDS", str(tmp_path / "cache"))
    return fake


def test_search_needs_a_key(rec_project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    code, data = run_json(["sounds", "search", "lion"], capsys)
    assert code == 1 and "FREESOUND_API_KEY isn't set" in data["findings"][0]["message"]


def test_search_lists_allowed_licences_only(freesound: FakeFreesound, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["sounds", "search", "lion roar", "--max-seconds", "3"], capsys)
    assert code == 0 and [r["ref"] for r in data["results"]] == ["freesound:101", "freesound:102"] and data["refused"] == 1
    first = data["results"][0]
    assert first["licence"] == "CC BY 4.0" and first["author"] == "roarer" and first["rating"] == 4.25 and first["tags"][0] == "lion"
    url, headers = freesound.requests[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith("https://freesound.org/apiv2/search/?")
    assert query["filter"] == ['license:("Creative Commons 0" OR "Attribution") duration:[0 TO 3]']
    assert query["fields"] == ["id,name,username,license,duration,avg_rating,num_ratings,tags,previews,url"]
    assert headers["Authorization"] == "Token k3y" and "k3y" not in url
    code, data = run_json(["sounds", "search", "lion", "--licence", "cc0"], capsys)
    assert [r["ref"] for r in data["results"]] == ["freesound:102"]


def test_add_fetch_and_build_from_freesound(rec_project: Project, freesound: FakeFreesound, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    from segan import sounds
    from segan.sfx import load_sfx

    monkeypatch.chdir(rec_project.root)
    code, data = run_json(["sounds", "add", "freesound:103"], capsys)
    assert code == 1 and "not allowed" in data["findings"][0]["message"]
    code, data = run_json(["sounds", "add", "freesound:101"], capsys)
    assert code == 0, data
    entry = data["entry"]
    assert entry["licence"] == "CC-BY-4.0" and entry["author"] == "roarer" and entry["file"] == "preview-hq-ogg"
    assert entry["url"] == "https://freesound.org/people/roarer/sounds/101/"
    cached = Path(sounds.cache_root()) / "freesound" / "101.ogg"
    assert cached.is_file() and entry["sha256"] == sounds.sha256_of(cached)
    lock = (rec_project.root / "sounds.lock").read_text()
    assert '[sounds."freesound:101"]' in lock and 'licence = "CC-BY-4.0"' in lock
    preview_headers = freesound.requests[-1][1]
    assert freesound.requests[-1][0].startswith("https://cdn.freesound.org/") and preview_headers["Authorization"] == "Token k3y"

    text = "name: lion\nduration: 1.2\nlayers:\n  - sample: freesound:101\n    shift: -3\n"
    path = write(rec_project, "sfx", "lion", text)
    sfx, findings = load_sfx(path, rec_project)
    assert sfx is not None, [f.format() for f in findings]
    assert sfx.layers[0].recorded[0].licence == "CC-BY-4.0"

    cached.unlink()  # a fresh machine: fetched on first use (no key needed for the preview)
    monkeypatch.delenv("FREESOUND_API_KEY")
    sfx, findings = load_sfx(path, rec_project)
    assert sfx is not None and cached.is_file()
    cached.write_bytes(freesound.audio[102])  # damaged / different file
    _, findings = load_sfx(path, rec_project)
    assert any(f.rule == "E019" and "sha256" in f.message for f in findings)
    cached.unlink()

    code, data = run_json(["sounds", "vendor"], capsys)
    assert code == 0 and data["copied"][0]["path"] == "sounds/freesound/101.ogg"
    sfx, findings = load_sfx(path, rec_project)
    assert sfx is not None and sfx.layers[0].recorded[0].path.endswith("sounds/freesound/101.ogg")

    code, data = run_json(["sounds", "credits"], capsys)
    assert code == 0 and data["attribution_required"] == ["freesound:101"]
    credits = (rec_project.root / "SOUND_CREDITS.md").read_text()
    assert '"Lion roar" by roarer (https://freesound.org/people/roarer/sounds/101/), licensed under CC BY 4.0' in credits


def test_unknown_freesound_ref(rec_project: Project) -> None:
    from segan.sfx import load_sfx

    path = write(rec_project, "sfx", "lion", "name: lion\nduration: 1\nlayers:\n  - sample: freesound:999\n")
    _, findings = load_sfx(path, rec_project)
    assert any(f.rule == "E019" and "segan sounds add freesound:999" in f.message for f in findings)


def test_inspect(rec_project: Project, freesound: FakeFreesound, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(rec_project.root)
    code, data = run_json(["sounds", "inspect", "sounds/roar.wav", "freesound:102"], capsys)
    assert code == 0, data
    local, remote = data["sounds"]
    assert local["seconds"] == 1.0 and local["pitch"]["note"] == "A3" and local["peak_dbfs"] == pytest.approx(-6.0, abs=0.1)
    assert remote["pitch"]["note"] == "A2" and remote["about"]["licence"] == "CC0 1.0"
    assert not (rec_project.root / "sounds.lock").exists()  # inspecting doesn't record anything


def test_sfx_source_setting(rec_project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(rec_project.root)
    code, data = run_json(["config", "set", "sfx.source", "recorded"], capsys)
    assert code == 0
    assert load_project(rec_project.root).config.sfx.source == "recorded"
    code, data = run_json(["config", "set", "sfx.source", "maybe"], capsys)
    assert code == 1
