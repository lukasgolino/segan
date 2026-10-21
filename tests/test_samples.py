from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from segan import libraries
from segan.patch import Report, parse_patch
from segan.project import Project
from segan.render import render_asset
from segan.samples import SampleSpec, blob_sha1, load_set, parse_sfz, read_sf2, sfz_key, wav_info, zone_audio
from segan.synth import Context, render_note
from segan.wavio import wav_bytes

from conftest import load

RATE = 22050


def tone(freq: float, seconds: float, rate: int = RATE, amp: float = 0.5) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(int(seconds * rate)) / rate)


def write_wav16(path: Path, x: np.ndarray, rate: int = RATE, loop: tuple[int, int] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(np.round(x * 32767).astype(np.int16), rate, loop))
    return path


def write_wav24(path: Path, x: np.ndarray, rate: int = RATE, channels: int = 2) -> Path:
    v = np.round(np.repeat(x[:, None], channels, axis=1) * (2**23 - 1)).astype(np.int32).reshape(-1)
    raw = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=1).astype(np.uint8).tobytes()
    # WAVE_FORMAT_EXTENSIBLE with the PCM GUID, as many sample libraries write
    fmt = struct.pack("<HHIIHHHHI", 0xFFFE, channels, rate, rate * channels * 3, channels * 3, 24, 22, 24, 0) + struct.pack("<H", 1) + bytes(14)
    body = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(raw)) + raw
    path.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
    return path


def peak_hz(x: np.ndarray, rate: int) -> float:
    size = 1 << int(np.log2(len(x)))
    spectrum = np.abs(np.fft.rfft(x[:size] * np.hanning(size)))
    return float(np.argmax(spectrum) * rate / size)


def patch(fields: dict[str, Any], path: Path) -> Any:
    report = Report(path)
    inst = parse_patch(fields, report, "E005", "instruments.p", "p")
    assert inst is not None, report.findings
    return inst


def test_wav_readers_agree(tmp_path: Path) -> None:
    x = tone(440, 0.2)
    a = write_wav16(tmp_path / "a.wav", x)
    b = write_wav24(tmp_path / "b.wav", x)
    assert wav_info(b).bits == 24 and wav_info(b).channels == 2 and wav_info(b).frames == len(x)
    za, zb = load_set(SampleSpec("wav", str(a))).zones[0], load_set(SampleSpec("wav", str(b))).zones[0]
    assert np.max(np.abs(zone_audio(za) - x)) < 1e-4 and np.max(np.abs(zone_audio(zb) - x)) < 1e-6


def test_wav_sample_follows_the_note(project: Project) -> None:
    write_wav16(project.root / "samples" / "a4.wav", tone(440, 1.0))
    inst = patch({"sample": {"wav": "samples/a4.wav", "root": "A4"}, "env": [0.0, 0.0, 1.0, 0.05]}, project.root / "kits" / "x.kit.yaml")
    assert inst.is_sample and inst.describe() == "sample wav a4"
    ctx = Context(rate=RATE)
    up = render_note(inst, ctx, 81, 0.5)  # A5: the sample read at twice the speed
    assert abs(peak_hz(up[1000:], RATE) - 880) < 6
    assert abs(peak_hz(render_note(inst, ctx, 69, 0.5)[1000:], RATE) - 440) < 6
    np.testing.assert_array_equal(up, render_note(inst, ctx, 81, 0.5))


def test_wav_loop_sustains_past_the_sample(project: Project) -> None:
    period = RATE // 441  # 50 frames = 441 Hz exactly: a clean loop of whole cycles
    x = 0.5 * np.sin(2 * np.pi * np.arange(period * 20) / period)
    write_wav16(project.root / "loop.wav", x, loop=(period * 10, period * 20))
    inst = patch({"sample": {"wav": "loop.wav", "root": "A4"}, "env": [0.0, 0.0, 1.0, 0.01]}, project.root / "kits" / "x.kit.yaml")
    out = render_note(inst, Context(rate=RATE), 69, 1.0)
    assert np.max(np.abs(out[int(0.8 * RATE) : int(0.9 * RATE)])) > 0.4  # still sounding 0.8 s in (the file is 45 ms)
    plain = patch({"sample": {"wav": "loop.wav", "root": "A4", "loop": False}}, project.root / "kits" / "x.kit.yaml")
    assert np.max(np.abs(render_note(plain, Context(rate=RATE), 69, 1.0)[int(0.5 * RATE) :])) < 1e-3


SFZ = """\
// comment
/* block
   comment */
#define $LOUD 64
<control> default_path=wavs/
<global> ampeg_release=0.4
<group> lovel=1 hivel=63
<region> lokey=0 hikey=64 pitch_keycenter=60 sample=c4 soft.wav
<region> lokey=65 hikey=127 pitch_keycenter=g4 sample=g4 soft.wav
<group> lovel=$LOUD hivel=127 seq_length=2
<region> key=60 lokey=0 hikey=127 seq_position=1 sample=c4 loud.wav
<region> key=60 lokey=0 hikey=127 seq_position=2 sample=c4 loud.wav volume=-6
<region> trigger=release key=60 sample=c4 soft.wav
"""


def test_sfz_parsing(tmp_path: Path) -> None:
    for name, f in (("c4 soft", 261.63), ("g4 soft", 392.0), ("c4 loud", 261.63)):
        write_wav16(tmp_path / "wavs" / f"{name}.wav", tone(f, 0.3))
    sset = parse_sfz(SFZ, tmp_path)
    assert len(sset.zones) == 4  # the release region is skipped
    soft, high, loud1, loud2 = sset.zones
    assert (soft.lokey, soft.hikey, soft.root, soft.lovel, soft.hivel) == (0, 64, 60.0, 1, 63) and high.root == 67.0
    assert loud1.lovel == 64 and loud1.seq_length == 2 and loud2.seq_position == 2 and abs(loud2.gain - 0.501) < 0.001
    assert sset.env.release == 0.4 and soft.loop is None
    assert [z.source.endswith("g4 soft.wav") for z in sset.pick(70, 30, 0)] == [True]
    assert sset.pick(60, 100, 0) == [loud1] and sset.pick(60, 100, 1) == [loud2]  # round robin by seed
    assert sfz_key("c#4") == 61 and sfz_key("db4") == 61 and sfz_key("60") == 60 and sfz_key("h4") is None


def test_sfz_instrument_in_a_song(project: Project) -> None:
    for name, f in (("c4 soft", 261.63), ("g4 soft", 392.0), ("c4 loud", 261.63)):
        write_wav16(project.root / "samples" / "wavs" / f"{name}.wav", tone(f, 1.5))
    (project.root / "samples" / "keys.sfz").write_text(SFZ)
    (project.root / "kits" / "t.kit.yaml").write_text("name: t\ninstruments:\n  p: { name: keys, sample: samples/keys.sfz, voices: 2 }\n")
    song, findings = load(project, "song", "s", "name: s\ntempo: 120\ntracks:\n  lead: { roll: [C4, G4] }\npatterns:\n  a:\n    length: 8\n"
                          "    lead: |\n      ....p...  G4\n      ........  F4\n      ........  E4\n      ........  D4\n      p-......  C4\n"
                          "sections:\n  main: [a]\n")  # fmt: skip
    assert song is not None, findings
    inst = song.kit.instruments["p"]
    assert inst.env.release == 0.4 and inst.range is None  # the map covers every key
    main = render_asset(song, project).main
    assert main.frames > 0 and float(main.level["lufs"] or -99) > -20


def write_sf2(path: Path, x: np.ndarray, rate: int, root: int, loop: tuple[int, int] | None) -> Path:
    """A minimal SoundFont: one sample, one instrument zone (+ a global zone), one preset with two zones."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return tag + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")

    def lst(kind: bytes, data: bytes) -> bytes:
        return chunk(b"LIST", kind + data)

    pcm = np.round(x * 32767).astype("<i2").tobytes() + bytes(92)
    ls, le = loop if loop else (0, 0)
    shdr = struct.pack("<20sIIIIIBbHH", b"tone", 0, len(x), ls, le, rate, root, 0, 0, 1) + struct.pack("<20sIIIIIBbHH", b"EOS", 0, 0, 0, 0, 0, 0, 0, 0, 0)
    def gen(op: int, amount: int) -> bytes:
        return struct.pack("<HH", op, amount & 0xFFFF)

    igen = gen(38, -2400) + gen(43, 0 | (127 << 8)) + gen(54, 1 if loop else 0) + gen(53, 0) + gen(0, 0)
    ibag = struct.pack("<HH", 0, 0) + struct.pack("<HH", 1, 0) + struct.pack("<HH", 4, 0)  # global zone (release), zone, terminal
    inst = struct.pack("<20sH", b"Tone", 0) + struct.pack("<20sH", b"EOI", 2)
    pgen = gen(48, 60) + gen(41, 0) + gen(0, 0)  # preset zone: 6 dB attenuation (x0.4), instrument 0
    pbag = struct.pack("<HH", 0, 0) + struct.pack("<HH", 2, 0)
    phdr = struct.pack("<20sHHHIII", b"Soft Tone", 5, 0, 0, 0, 0, 0) + struct.pack("<20sHHHIII", b"EOP", 0, 0, 1, 0, 0, 0)
    imod = pmod = bytes(10)
    pdta = (chunk(b"phdr", phdr) + chunk(b"pbag", pbag) + chunk(b"pmod", pmod) + chunk(b"pgen", pgen) + chunk(b"inst", inst)
            + chunk(b"ibag", ibag) + chunk(b"imod", imod) + chunk(b"igen", igen[:-4]) + chunk(b"shdr", shdr))  # fmt: skip
    body = b"sfbk" + lst(b"INFO", chunk(b"ifil", struct.pack("<HH", 2, 1))) + lst(b"sdta", chunk(b"smpl", pcm)) + lst(b"pdta", pdta)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def test_sf2_preset(project: Project) -> None:
    period = 50
    x = 0.5 * np.sin(2 * np.pi * np.arange(period * 40) / period)  # 441 Hz at 22050
    write_sf2(project.root / "bank.sf2", x, RATE, 69, (period * 20, period * 40))
    sset = read_sf2(project.root / "bank.sf2", 5)
    (zone,) = sset.zones
    assert zone.root == 69.0 and zone.loop == (1000, 2000) and abs(sset.env.release - 0.25) < 1e-9
    assert abs(20 * np.log10(zone.gain) + 2.4) < 1e-6  # 60 cB x 0.4
    assert read_sf2(project.root / "bank.sf2", "soft tone").zones == sset.zones
    with pytest.raises(ValueError, match="no preset 6"):
        read_sf2(project.root / "bank.sf2", 6)
    inst = patch({"sample": {"sf2": "bank.sf2", "preset": 5}}, project.root / "kits" / "x.kit.yaml")
    assert inst.env.release == 0.25
    out = render_note(inst, Context(rate=RATE), 81, 1.0)
    assert abs(peak_hz(out[int(0.5 * RATE) :], RATE) - 882) < 8  # looped and an octave up


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"wav": "nope.wav"}, "not found"),
        ("x.mp3", "must be a .wav"),
        ({"wav": "a.wav", "sfz": "b.sfz"}, "exactly one"),
        ({"wav": "a.wav", "preset": 3}, "preset/bank for sf2"),
        ({"wav": "a.wav", "root": "Q9"}, "root"),
        ({"library": "nope", "instrument": "x"}, "unknown sample library"),
        ("vsco2/no_such_thing", "no instrument"),
    ],
)
def test_sample_errors(project: Project, value: Any, message: str) -> None:
    write_wav16(project.root / "a.wav", tone(440, 0.1))
    report = Report(project.root / "kits" / "x.kit.yaml")
    assert parse_patch({"sample": value}, report, "E005", "instruments.p", "p") is None
    assert any(message in f.message for f in report.findings), report.findings


def test_library_needs_a_fetch_then_plays(project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGAN_SAMPLES", str(tmp_path / "cache"))
    lib = libraries.library("vsco2")
    name = "glockenspiel"
    report = Report(project.root / "kits" / "x.kit.yaml")
    assert parse_patch({"sample": f"vsco2/{name}"}, report, "E005", "instruments.p", "p") is None
    assert f"segan samples fetch vsco2 {name}" in report.findings[0].message
    served: dict[str, bytes] = {}
    for path in lib.instruments[name]["files"]:  # stand-in audio with the pinned ids
        data = wav_bytes(np.round(tone(1046.5, 0.5, 44100) * 32767).astype(np.int16), 44100)
        served[libraries.raw_url(lib, path)] = data
        lib.files[path] = (len(data), blob_sha1(data))

    class Response:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return self.data

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout: Response(served[url]))
    count, _ = libraries.fetch(lib, [name])
    assert count == len(lib.instruments[name]["files"]) and libraries.fetch(lib, [name])[0] == 0
    inst = patch({"sample": f"vsco2/{name}"}, project.root / "kits" / "x.kit.yaml")
    assert inst.sample is not None and inst.sample.kind == "library" and inst.range is not None
    assert np.max(np.abs(render_note(inst, Context(rate=RATE), inst.range[0] + 3, 0.2))) > 0.05
    libraries.library.cache_clear()


def test_fetch_rejects_a_changed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEGAN_SAMPLES", str(tmp_path / "cache"))
    lib = libraries.library("vsco2")

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self) -> bytes:
            return b"tampered"

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout: Response())
    with pytest.raises(libraries.LibraryError, match="doesn't match"):
        libraries.fetch(lib, ["triangle"])
    assert not any((tmp_path / "cache").rglob("*.wav"))


def test_w014_note_longer_than_its_sample(project: Project) -> None:
    from segan.songlint import lint_song_source

    write_wav16(project.root / "samples" / "blip.wav", tone(261.63, 0.3))
    (project.root / "kits" / "t.kit.yaml").write_text("name: t\ninstruments:\n  p: { sample: { wav: samples/blip.wav, root: C4 } }\n")
    text = "name: s\ntempo: 120\ntracks:\n  lead: { roll: [C4, D4] }\npatterns:\n  a:\n    length: 8\n    lead: |\n      ........  D4\n      p-......  C4\n  b:\n    length: 8\n    lead: |\n      ........  D4\n      p-------  C4\nsections:\n  main: [a, b]\n"
    song, findings = load(project, "song", "s", text)
    assert song is not None, findings
    warnings = [f for f in lint_song_source(song, project) if f.rule == "W014"]
    assert [f.where for f in warnings] == ["patterns.b"] and "lasts 0.3s" in warnings[0].message


def test_ranges_in_samples_list_and_kit_show(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#24: `segan samples list` gives each library instrument's key range (from the bundled map, no download);
    `segan kit show --json` gives each instrument's range."""
    from conftest import run_json

    lib = libraries.library("vsco2")
    assert lib.key_range("bass_drum") is None  # unpitched
    low, high = lib.key_range("violins_sus") or (0, 0)
    assert 40 <= low < 60 < high <= 108
    monkeypatch.chdir(project.root)
    code, data = run_json(["samples", "list"], capsys)
    rows = {r["instrument"]: r for r in data["libraries"][0]["instruments"]}
    assert code == 0 and rows["bass_drum"]["range"] is None and rows["violins_sus"]["range"][0].endswith(("2", "3"))
    code, data = run_json(["kit", "show", "t"], capsys)
    instruments = data["outputs"][0]["instruments"]
    assert code == 0 and instruments["p"]["range"] == ["C4", "C6"] and instruments["q"]["range"] is None
