"""Fixes for agent reports #61-#75 that don't belong to one module's tests."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from segan import oggio
from segan.lint import lint_paths
from segan.project import Project
from segan.sfx import Variations
from segan.sfxrender import variation_layers

from conftest import load, rules, write


def test_trim_takes_a_one_item_list(project: Project) -> None:
    """#62: `trim: [start]` means the start alone, as the message says."""
    (project.root / "sounds").mkdir()
    from segan.wavio import wav_bytes

    (project.root / "sounds" / "hit.wav").write_bytes(wav_bytes(np.round(np.sin(np.arange(22050) / 10.0) * 8000).astype(np.int16), 22050))
    base = "name: r\nduration: 0.5\nlayers:\n  - { sample: sounds/hit.wav, licence: CC0, source: https://example.com/hit, trim: TRIM }\n"
    for trim in ("0.03", "[0.03]", "[0.03, 0.4]"):
        sfx, findings = load(project, "sfx", "r", base.replace("TRIM", trim))
        assert sfx is not None, (trim, findings)
        spec = sfx.layers[0].inst.sample
        assert spec is not None and spec.process is not None and spec.process.trim_start == 0.03
    sfx, findings = load(project, "sfx", "r", base.replace("TRIM", "[0.4, 0.1]"))
    assert sfx is None and "the start alone" in findings[0].message


def test_timing_jitter_keeps_the_first_layer_at_its_start(project: Project) -> None:
    """#64: `variations.timing` moves the other layers, never the earliest (no lead-in latency)."""
    text = "name: v\nduration: 0.6\nlayers:\n  - { osc: square, pitch: A4, length: 0.1 }\n  - { osc: noise, start: 0.05, length: 0.1 }\n  - { osc: sine, pitch: A3, start: 0.1, length: 0.1 }\n"
    sfx, findings = load(project, "sfx", "v", text.replace("square", "pulse"))
    assert sfx is not None, findings
    starts = [[layer.start for layer in variation_layers("v", sfx.layers, Variations(count=8, seed=3, timing=0.1), i)] for i in range(8)]
    assert all(s[0] == 0.0 for s in starts) and all(min(s) == 0.0 for s in starts)
    assert len({s[1] for s in starts}) > 1  # the others still move


def test_ogg_encodes_long_songs_in_blocks() -> None:
    """#68: one large Vorbis write crashed libsndfile; blocks don't, and the stream is complete."""
    if not oggio.available():
        pytest.skip("needs segan[ogg]")
    rate = 22050
    pcm = (np.random.default_rng(1).random((rate * 75, 2)) - 0.5) * 20000
    data = oggio.encode_ogg(pcm.astype(np.int16), rate, 0.4, "long")
    audio, got = oggio.decode_ogg(data)
    assert got == rate and abs(len(audio) - len(pcm)) < rate // 10
    assert data == oggio.encode_ogg(pcm.astype(np.int16), rate, 0.4, "long")  # still byte-identical


def test_w027_onset_inside_the_crossfade(project: Project) -> None:
    """#75: a hit in a loop's first crossfade seconds gets blended down: say so."""
    loop = "name: hum\nduration: 2.0\nloop: true\ncrossfade: 0.6\nlayers:\n  - { osc: sine, pitch: A2, env: [0.2, 0, 1, 0.2], length: 3 }\n"
    hit = "  - { osc: noise, start: START, length: 0.05, env: [0.001, 0.05, 0, 0.02], gain: 6 }\n"
    path = write(project, "sfx", "hum", loop + hit.replace("START", "0.2"))
    found = lint_paths(project, [path]).findings
    assert "W027" in rules(found) and "inside the 0.6s loop crossfade" in next(f.message for f in found if f.rule == "W027")
    path = write(project, "sfx", "hum", loop + hit.replace("START", "1.0"))
    assert "W027" not in rules(lint_paths(project, [path]).findings)


def test_quiet_after_the_subcommand(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#75: `segan lint --quiet` works like `segan --quiet lint`."""
    from segan.cli import main

    monkeypatch.chdir(project.root)
    assert main(["lint", "--quiet", "--no-render"]) == 0


def test_w003_counts_per_stem_mix(project: Project) -> None:
    """#71: a stemmed song counts the instruments of each mix, not of every track together."""
    from segan.songlint import lint_song_source

    kit = (project.root / "kits" / "t.kit.yaml").read_text()
    (project.root / "segan.toml").write_text((project.root / "segan.toml").read_text() + "\n[lint]\nmax_instruments = 3\n")
    from segan.project import load_project

    project = load_project(project.root)
    song_text = """\
name: st
tempo: 120
key: A minor
tracks:
  a: { roll: [C4, C5] }
  b: { roll: [C4, C5] }
  d: { drums: [k, s, h] }
patterns:
  x:
    length: 4
    a: |
      ....  C5
      ....  B4
      ....  A4
      ....  G4
      ....  F4
      ....  E4
      ....  D4
      p.q.  C4
    b: |
      ....  C5
      ....  B4
      ....  A4
      ....  G4
      ....  F4
      ....  E4
      ....  D4
      q...  C4
    d: |
      x...  k
      ..x.  s
      x.x.  h
sections: { main: [x] }
arrangement: [main]
STEMS
"""
    assert kit
    plain, _ = load(project, "song", "st", song_text.replace("STEMS", ""))
    assert "W003" in rules(lint_song_source(plain, project))
    stemmed, findings = load(project, "song", "st", song_text.replace("STEMS", "stems: { groups: { lead: [a, b], beat: [d] }, mixes: { calm: [lead], drive: [beat] } }"))
    assert stemmed is not None, findings
    assert "W003" not in rules(lint_song_source(stemmed, project))


def test_song_fades(project: Project) -> None:
    """#72: fade_in / fade_out for songs that play once."""
    from segan.render import render_asset

    song = """\
name: end
tempo: 120
key: A minor
tracks:
  a: { roll: [A4, A5] }
patterns:
  x:
    length: 16
    a: |
      ................  A5
      ................  G5
      ................  F5
      ................  E5
      ................  D5
      ................  C5
      ................  B4
      q---------------  A4
sections: { main: [x, x, x] }
arrangement: [main]
"""
    plain, _ = load(project, "song", "end", song)
    faded, findings = load(project, "song", "end", song + "fade_in: 1\nfade_out: 2\n")
    assert faded is not None and faded.fades == (1.0, 2.0), findings
    a = render_asset(plain, project).outputs[0].audio
    b = render_asset(faded, project).outputs[0].audio
    rate = 22050
    assert np.abs(b[: rate // 20]).max() < 0.05 * np.abs(a[: rate // 20]).max() + 1e-3  # starts from silence
    end = round(6.0 * rate)  # three bars at 120 bpm
    assert np.abs(b[end - rate // 20 : end]).max() < 0.1 * np.abs(a[end - rate // 2 : end]).max()
    bad, findings = load(project, "song", "end", song + "loop: main\nfade_out: 2\n")
    assert bad is None and "E008" in rules(findings)


def test_recorded_layer_end_after_varispeed(project: Project) -> None:
    """#67: a recording pitched below C4 plays slower; its end shows in the layer levels and W011's hint."""
    from segan.sfxrender import layer_levels
    from segan.wavio import wav_bytes

    (project.root / "sounds").mkdir()
    (project.root / "sounds" / "tone.wav").write_bytes(wav_bytes(np.round(np.sin(np.arange(22050) / 8.0) * 8000).astype(np.int16), 22050))
    text = "name: slow\nduration: 1.2\nlayers:\n  - { id: rec, sample: sounds/tone.wav, licence: CC0, source: https://example.com/t, pitch: C3 }\n"
    sfx, findings = load(project, "sfx", "slow", text)
    assert sfx is not None, findings
    rec = next(entry for entry in layer_levels(sfx, project, "") if entry["layer"] == "rec")
    assert 1.9 < float(str(rec["ends_s"])) < 2.1  # one second recorded, an octave down = two seconds
    path = write(project, "sfx", "slow", text)
    w011 = [f for f in lint_paths(project, [path]).findings if f.rule == "W011"]
    assert w011 and "runs to 2" in w011[0].message


def test_pitch_check_says_what_it_skipped(project: Project) -> None:
    """#73: skipped notes are counted with the reason."""
    from segan.songpreview import pitch_check

    song = """\
name: cue
tempo: 200
key: A minor
tracks:
  a: { roll: [A4, A5] }
patterns:
  x:
    length: 8
    a: |
      ........  A5
      ........  G5
      ........  F5
      ........  E5
      ........  D5
      ..p.....  C5
      .p......  B4
      p...p---  A4
sections: { main: [x] }
arrangement: [main]
"""
    loaded, findings = load(project, "song", "cue", song)
    assert loaded is not None, findings
    check = pitch_check(loaded, project)["a"]
    assert check["notes_checked"] + check["notes_skipped"] == 4
    assert check["notes_skipped"] >= 1 and all("50 ms" in r or "pitch" in r for r in check["skipped_because"])


def test_render_outputs_and_cached_pitch_check(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#69: `segan render --output` writes cached WAVs without analysis; the pitch check is cached per render."""
    from conftest import run_json
    from test_song import GROUPED

    from segan import songpreview

    write(project, "song", "tune", GROUPED)
    monkeypatch.chdir(project.root)
    code, data = run_json(["render", "tune", "--output", "mix:calm"], capsys)
    assert code == 0 and [o["output"] for o in data["outputs"][0]["outputs"]] == ["mix:calm"]
    calls: list[int] = []
    real = songpreview.measure_pitch

    def counted(*args: Any) -> Any:
        calls.append(1)
        return real(*args)

    monkeypatch.setattr(songpreview, "measure_pitch", counted)
    song, _ = load(project, "song", "tune", GROUPED)
    first = songpreview.pitch_check(song, project)
    assert songpreview.pitch_check(song, project) == first and len(calls) == 1


def test_cleared_licences(project: Project) -> None:
    """#66: a licence the project cleared in segan.toml is accepted for recorded layers and listed in the credits."""
    from segan.sounds import credits_text
    from segan.wavio import wav_bytes

    (project.root / "sounds").mkdir()
    (project.root / "sounds" / "boom.wav").write_bytes(wav_bytes(np.round(np.sin(np.arange(11025) / 9.0) * 8000).astype(np.int16), 22050))
    text = "name: b\nduration: 0.5\nlayers:\n  - { sample: sounds/boom.wav, licence: Sonniss-GDC, source: https://sonniss.com/gameaudiogdc }\n"
    sfx, findings = load(project, "sfx", "b", text)
    assert sfx is None and "extra_licences" in next(f.message for f in findings if f.rule == "E020")
    (project.root / "segan.toml").write_text((project.root / "segan.toml").read_text() + '\n[sounds]\nextra_licences = ["Sonniss-GDC"]\n')
    from segan.project import load_project

    project = load_project(project.root)
    sfx, findings = load(project, "sfx", "b", text)
    assert sfx is not None, findings
    credits = credits_text({"sounds/boom.wav": {"name": "boom", "licence": "Sonniss-GDC", "source": "https://sonniss.com/gameaudiogdc"}}, {}, ("Sonniss-GDC",))
    assert "Other licences" in credits and "licensed under Sonniss-GDC." in credits
    bad = '\n[sounds]\nextra_licences = ["CC-BY-NC-4.0"]\n'
    from segan.findings import SeganError

    (project.root / "segan.toml").write_text((project.root / "segan.toml").read_text().replace('\n[sounds]\nextra_licences = ["Sonniss-GDC"]\n', bad))
    with pytest.raises(SeganError):
        load_project(project.root)


def test_sounds_remove_and_prune(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#63: drop sounds from sounds.lock; prune drops what no SFX plays; lint says so (W028)."""
    from conftest import run_json
    from segan.wavio import wav_bytes

    (project.root / "sounds").mkdir()
    for name in ("a", "b"):
        (project.root / "sounds" / f"{name}.wav").write_bytes(wav_bytes(np.round(np.sin(np.arange(11025) / 9.0) * 8000).astype(np.int16), 22050))
    monkeypatch.chdir(project.root)
    for name in ("a", "b"):
        code, data = run_json(["sounds", "add", f"sounds/{name}.wav", "--licence", "CC0", "--source", "own recording"], capsys)
        assert code == 0, data
    write(project, "sfx", "uses_a", "name: uses_a\nduration: 0.5\nlayers:\n  - { sample: sounds/a.wav }\n")
    found = lint_paths(project, None, render=False).findings
    assert "W028" in rules(found) and "sounds/b.wav" in next(f.message for f in found if f.rule == "W028")
    code, data = run_json(["sounds", "remove", "sounds/a.wav"], capsys)
    assert code == 1 and "uses_a" in data["findings"][0]["message"]
    code, data = run_json(["sounds", "prune", "--dry-run"], capsys)
    assert code == 0 and data["unused"] == ["sounds/b.wav"]
    code, data = run_json(["sounds", "prune"], capsys)
    assert code == 0 and "W028" not in rules(lint_paths(project, None, render=False).findings)
    code, data = run_json(["sounds", "remove", "sounds/a.wav", "--force"], capsys)
    assert code == 0 and data["left"] == 0


PAGE = """<html><head><meta property="og:title" content="Bell by someone" /><meta property="og:audio:artist" content="someone" />
<meta property="og:audio:title" content="Bell.wav" /><meta property="og:url" content="https://freesound.org/people/someone/sounds/123/" /></head>
<body><div data-ogg="https://cdn.freesound.org/previews/0/123_45-lq.ogg"></div>
<a href="https://creativecommons.org/publicdomain/zero/1.0/">Creative Commons 0</a></body></html>"""


def test_keyless_add_from_a_page(project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """#65: without an API key a Freesound page (or freesound:<id>) is read from the public page, same licence rule."""
    from segan import sounds

    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    monkeypatch.setenv("SEGAN_SOUNDS", str(tmp_path / "cache"))
    pages = {"https://freesound.org/s/123/": PAGE.encode(), "https://cdn.freesound.org/previews/0/123_45-hq.ogg": b"OggS fake"}
    monkeypatch.setattr(sounds, "_request", lambda url, key: pages[url])
    key, entry = sounds.add("https://freesound.org/people/someone/sounds/123/", project.root)
    assert key == "freesound:123" and entry["licence"] == "CC0-1.0" and entry["author"] == "someone" and entry["download"].endswith("-hq.ogg")
    assert "freesound:123" in sounds.read_lock(project.root)
    pages["https://freesound.org/s/123/"] = PAGE.replace("publicdomain/zero/1.0", "licenses/by-nc/4.0").encode()
    with pytest.raises(sounds.SoundsError, match="not allowed"):
        sounds.add("freesound:123", project.root)
