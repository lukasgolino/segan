"""`segan lint`: format errors (from parsing) plus warnings from the source and from the rendered audio.

Audio warnings (W001 loudness shortfall, W004 silence, W005 lead-in, W007 loop seam, W008 DC offset,
W010 aliasing, W011 cut-off tail, W013 un-normalised level, W017 stem mix level) render the asset (cached), so lint, preview and
build always judge the same samples. `render=False` skips them for a fast format-only check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from segan.analysis import dc_offset, leading_silence, seam_click
from segan.asset import ASSET_SUFFIXES, SFX_SUFFIX, SONG_SUFFIX, load_asset
from segan.findings import Finding, SeganError
from segan.kit import KIT_SUFFIX, Kit, load_kit_file
from segan.kitshow import aliasing_of, context_for
from segan.patch import Instrument
from segan.project import Project
from segan.soundtrack import SOUNDTRACK_SUFFIX, Soundtrack, check_soundtrack, load_soundtrack
from segan.synth import Context

WARNING_RULES = {
    "W001": "loudness target out of reach without heavy limiting",
    "W002": "unused pattern or section",
    "W003": "too many instruments in one song",
    "W004": "silent pattern or sound",
    "W005": "leading silence in an SFX",
    "W006": "made under an older style version",
    "W007": "click at the loop point",
    "W008": "DC offset",
    "W009": "clash between tracks on a strong beat",
    "W010": "aliasing",
    "W011": "SFX still sounding at its duration",
    "W012": "note held past the end of its pattern",
    "W013": "loudness off target (normalisation off)",
    "W014": "note held longer than its (unlooped) sample",
    "W015": "flow section shorter than the ring-out before it",
    "W016": "soundtrack cross-fade between clashing keys",
    "W017": "stem mix can't reach its target",
    "W018": "a filter removes most of an SFX noise layer's level",
    "W019": "a looping song's file is over 2 bars longer than the song (long ring-out)",
}


@dataclass
class LintResult:
    files: list[Path]
    findings: list[Finding]
    assets: list[Any]
    kits: list[Kit]
    soundtracks: list[Soundtrack] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


def source_files(project: Project, paths: list[Path] | None = None) -> list[Path]:
    """Kit, song, SFX and soundtrack files under `paths` (default: the project's kits/, music/ and sfx/)."""
    roots = paths or [project.kits_dir, project.music_dir, project.sfx_dir]
    suffixes = (KIT_SUFFIX, SOUNDTRACK_SUFFIX, *ASSET_SUFFIXES)
    found: set[Path] = set()
    for root in roots:
        if root.is_file():
            found.add(root)
        elif root.is_dir():
            found.update(p for p in root.rglob("*.yaml") if p.name.endswith(suffixes))
    return sorted(found)


_ALIASING: dict[tuple[str, int, Context], float | None] = {}


def aliasing(inst: Instrument, midi: int, ctx: Context) -> float | None:
    """Aliasing of an instrument's steady tone at `midi` (memoised for the process)."""
    key = (repr(inst), midi, ctx)
    if key not in _ALIASING:
        _ALIASING[key] = aliasing_of(inst, midi, ctx)
    return _ALIASING[key]


def lint_paths(project: Project, paths: list[Path] | None = None, render: bool = True) -> LintResult:
    files = source_files(project, paths)
    findings: list[Finding] = []
    assets: list[Any] = []
    kits: list[Kit] = []
    ctx = context_for(project.config.mix)
    threshold = project.config.lint.max_aliasing_db
    soundtracks: list[Soundtrack] = []
    for path in files:
        if path.name.endswith(SOUNDTRACK_SUFFIX):
            soundtrack, st_findings = load_soundtrack(path)
            findings.extend(st_findings)
            if soundtrack is not None:
                soundtracks.append(soundtrack)
            continue
        if path.name.endswith(KIT_SUFFIX):
            try:
                kit = load_kit_file(path)
            except SeganError as exc:
                findings.extend(exc.findings)
                continue
            kits.append(kit)
            if render:
                findings.extend(_kit_aliasing(kit, ctx, threshold))
            continue
        asset, asset_findings = load_asset(path, project)
        if asset is not None:
            off = asset.meta.lint_disable | project.config.lint.disabled_for(getattr(asset, "category", None))
            asset_findings = [f for f in asset_findings if not (f.severity == "warning" and f.rule in off)]
        findings.extend(asset_findings)
        if asset is None:
            continue
        assets.append(asset)
        findings.extend(lint_asset(asset, project, render))
    by_name: dict[str, list[Any]] = {}
    for asset in assets:
        by_name.setdefault(asset.name, []).append(asset)
    for name, group in by_name.items():
        if len(group) > 1:
            for asset in group:
                others = ", ".join(o.path.name for o in group if o is not asset and o.path)
                findings.append(Finding("E012", f"asset name {name!r} is also used by {others}; names must be unique across songs and SFX (outputs would overwrite each other)", asset.path, None, "name"))
    if soundtracks:
        songs = _project_assets(project, assets, "song")
        sfx = set(_project_assets(project, assets, "sfx"))
        for soundtrack in soundtracks:
            findings.extend(check_soundtrack(soundtrack, songs, sfx))
    disabled = set(project.config.lint.disable)
    findings = [f for f in dict.fromkeys(findings) if f.rule not in disabled]
    return LintResult(files, findings, assets, kits, soundtracks)


def _project_assets(project: Project, loaded: list[Any], kind: str) -> dict[str, Any]:
    """Every song (or SFX) of the project by name: the ones this lint loaded, plus the rest parsed quietly (a
    soundtrack linted on its own still needs the songs it names)."""
    found = {a.name: a for a in loaded if a.kind == kind}
    folder, suffix = (project.music_dir, SONG_SUFFIX) if kind == "song" else (project.sfx_dir, SFX_SUFFIX)
    if folder.is_dir():
        for path in sorted(folder.rglob(f"*{suffix}")):
            name = path.name[: -len(suffix)]
            if name not in found:
                asset, _ = load_asset(path, project)
                if asset is not None:
                    found[asset.name] = asset
    return found


def _kit_aliasing(kit: Kit, ctx: Context, threshold: float) -> list[Finding]:
    out = []
    for key, inst in kit.instruments.items():
        if inst.range is None:
            continue
        value = aliasing(inst, inst.range[1], ctx)
        if value is not None and value > threshold:
            out.append(Finding("W010", f"{inst.name or key} aliases at {value:.0f} dB at the top of its range ({value - threshold:.0f} dB over "
                               f"lint.max_aliasing_db): raise [mix] oversample, or lower its range / use a softer wave", kit.path, inst.line, f"instruments.{key}"))  # fmt: skip
    return out


def lint_asset(asset: Any, project: Project, render: bool = True) -> list[Finding]:
    found: list[Finding] = []
    meta = asset.meta
    current = project.config.style_version
    if meta.style_version < current:
        found.append(Finding("W006", f"made under style v{meta.style_version}; the project is at v{current}: check it against SOUND.md's changelog, "
                             "update it, then `segan mark --current`", asset.path, None, "style_version"))  # fmt: skip
    if asset.kind == "song":
        from segan.songlint import lint_song_source

        found += lint_song_source(asset, project)
    if render and not meta.template:
        found += lint_audio(asset, project)
    off = set(meta.lint_disable) | project.config.lint.disabled_for(getattr(asset, "category", None))
    return [f for f in found if f.rule not in off]


def lint_audio(asset: Any, project: Project) -> list[Finding]:
    from segan.render import render_asset

    from segan.song import Song
    from segan.songrender import song_mix

    cfg = project.config.lint
    ctx = context_for(song_mix(asset, project) if isinstance(asset, Song) else project.config.mix)  # a song at its own rate aliases more
    found: list[Finding] = []
    path = asset.path
    render = render_asset(asset, project)
    short: set[tuple[str, str]] = set()
    for output in render.outputs:
        if asset.kind == "song" and output.loop is not None and output.info.get("loop_offset"):
            variant = asset.all_variants().get(output.info.get("variant") or "")
            tempo = variant.tempo if variant is not None and variant.tempo else asset.tempo
            bars = output.info["loop_offset"] / output.rate / (asset.meter[0] * 60.0 / tempo)
            if bars > MAX_LOOP_OFFSET_BARS + 1e-6:
                found.append(Finding("W019", f"{output.stem}: the loop file runs {bars:.0f} bars past the song because its last notes ring that long "
                                     "(a one-shot sample, a long release or room): the file is that much bigger. Give the long-ringing "
                                     "instruments `max_ring: <seconds>` in the kit (a short fade after the note), or shorten their release", asset.path, None, "loop"))  # fmt: skip
        if output.id.startswith("mix:") and output.level.get("target") is not None:
            aim, reach = float(output.level["target"] or 0.0), float(output.level["lufs"] or 0.0) + float(output.info["trim_db"])
            if reach < aim - cfg.loudness_tolerance:
                found.append(Finding("W017", f"stem mix {output.info['mix']!r} reaches only {reach:.1f} LUFS of its {aim:g} target, even with its "
                                     f"{output.info['trim_db']:g} dB trim: its peaks are too close to the ceiling, so it plays {aim - reach:.1f} LU quieter "
                                     "than the loudest mix. Give its stems more body (sustained parts), or let the loudest mix be quieter", path, None, f"stems.mixes.{output.info['mix']}"))  # fmt: skip
        if output.id.startswith(("stem:", "mix:", "flow")):
            if output.info.get("cut") and (output.id.split(":", 1)[0], output.info["section"]) not in short:
                short.add((output.id.split(":", 1)[0], output.info["section"]))
                found.append(Finding("W015", f"flow section {output.info['section']!r} is shorter than the ring-out of the section before it "
                                     f"({output.info['from']!r}): the rest of that ring-out is cut when the game plays it after "
                                     f"{output.info['from']!r}. Lengthen the section or shorten the releases / room", path, None, f"sections.{output.info['section']}"))  # fmt: skip
            continue
        label = output.stem
        level = output.level
        target, lufs, measured = level.get("target"), level.get("lufs"), level.get("measured")
        if measured is not None and measured < -70:
            found.append(Finding("W004", f"{label} is silent (nothing above -70 LUFS): check gains, envelopes and starts", path, None, label))
            continue
        if target is not None and lufs is not None and lufs < target - cfg.loudness_tolerance:
            fix = ("Stagger layer starts by a few ms (3-9 ms) so transients don't stack, tame the peakiest layer (saturate or "
                   "compress noise layers with distort, lower its gain), give it more body (longer decay/sustain), or use a quieter "
                   "category. `segan preview --json` lists each layer's peak, loudness and crest" if render.kind != "song" else
                   "Percussive songs (drums, plucks, staccato orchestra) have high peaks for their integrated loudness: add sustained parts "
                   "(pads, held bass), or give it a quieter category of its own: `category: music_soft` in the song and "
                   f"`music_soft = {target - 3:g}` under [loudness] in segan.toml (an unlisted category falls back to `sfx`)")  # fmt: skip
            found.append(Finding("W001", f"{label} reaches only {lufs:.1f} LUFS of its {target:g} target: it's too peaky to get louder without more than "
                                 f"{cfg.max_limiting_db:g} dB of limiting. {fix}", path, None, label))  # fmt: skip
        if target is None and lufs is not None:
            goal = project.config.target(getattr(asset, "category", "music"))
            if abs(lufs - goal) > cfg.loudness_tolerance:
                found.append(Finding("W013", f"{label} is at {lufs:.1f} LUFS, {lufs - goal:+.1f} LU off its category target {goal:g}, and normalize is false: "
                                     "fix its gains or let the build normalise it", path, None, label))  # fmt: skip
        audio = output.audio
        offset = dc_offset(audio)
        if offset > cfg.max_dc_offset:
            found.append(Finding("W008", f"{label} has a DC offset of {offset:.3f}: a layer is lopsided (pulse with uneven duty and no filter, distortion); "
                                 "add a high-pass filter", path, None, label))  # fmt: skip
        if output.loop is not None:
            click = seam_click(audio, output.loop[0], output.loop[1])
            if click > cfg.max_seam_click:
                hint = ("give the loop a longer crossfade, or make held sounds steady across the end" if asset.kind == "sfx"
                        else "a note or sweep is cut at the loop point; end the loop on a release")  # fmt: skip
                found.append(Finding("W007", f"{label} clicks at its loop point ({click:.3f} of full scale > {cfg.max_seam_click:g}): {hint}. "
                                     "Look at the seam view (`segan preview --seam`)", path, None, "loop"))  # fmt: skip
        if asset.kind == "sfx":
            silence = leading_silence(audio, output.rate) * 1000.0
            if silence > cfg.max_leading_silence_ms and not output.info.get("loop"):
                found.append(Finding("W005", f"{label} starts after {silence:.0f} ms of near-silence (> {cfg.max_leading_silence_ms:g} ms): it will feel "
                                     "late in game. Start the main layer at 0 and use a fast attack", path, None, label))  # fmt: skip
            for layer in output.info.get("sounding_at_end", []):
                found.append(Finding("W011", f"{label}: layer {layer} is still sounding at duration {output.info.get('duration'):g}s and gets cut "
                                     "(a click or a truncated tail): lengthen duration, or shorten the layer's length/release", path, None, f"duration ({layer})"))  # fmt: skip
    found += _asset_aliasing(asset, ctx, cfg.max_aliasing_db)
    if asset.kind == "sfx":
        found += _filter_loss(asset, ctx)
    return list(dict.fromkeys(found))


FILTER_LOSS_DB = 12.0  # W018
MAX_LOOP_OFFSET_BARS = 2  # W019


def _filter_loss(asset: Any, ctx: Context) -> list[Finding]:
    """W018: a noise layer whose filter takes away more than 12 dB of its level (a narrow band-pass): it ends up far
    quieter than its gain suggests. Measured dry, the layer with and without its filter (and cutoff keyframes)."""
    from dataclasses import replace

    import numpy as np

    from segan.dsp import seed_of
    from segan.sfxrender import render_layer

    out = []
    layers = [*asset.layers, *(layer for phase in asset.phases.values() for layer in phase.layers)]
    for layer in layers:
        inst = layer.inst
        if inst.is_drum or inst.is_sample or inst.wave not in ("noise", "bitnoise") or (inst.filter is None and not layer.cutoff):
            continue  # pitched waves lose level through a band-pass by design (formants); noise is where it surprises
        seed = seed_of(asset.name, layer.index, 0)
        available = layer.start + layer.inst.tail() + (layer.length or asset.duration)
        filtered, _ = render_layer(layer, ctx, available, seed, 0.0, 0.0)
        plain, _ = render_layer(replace(layer, inst=replace(layer.inst, filter=None), cutoff=None), ctx, available, seed, 0.0, 0.0)
        power, reference = float(np.mean(filtered**2)), float(np.mean(plain**2))
        if reference <= 0:
            continue
        loss = 10.0 * np.log10(reference / max(power, 1e-30))
        if loss > FILTER_LOSS_DB:
            name = layer.id or f"layers.{layer.index}"
            out.append(Finding("W018", f"layer {name}: its filter removes {loss:.0f} dB of the noise's level (a narrow band-pass or a low cutoff), so it plays far "
                               "quieter than its gain says: raise its gain to put it back in balance, or widen the filter", asset.path, layer.line, name))  # fmt: skip
    return out


def _asset_aliasing(asset: Any, ctx: Context, threshold: float) -> list[Finding]:
    """W010: each pitched instrument at the highest note this asset plays."""
    tops: dict[str, tuple[Instrument, int, int | None, str]] = {}
    if asset.kind == "sfx":
        layers = [*asset.layers, *(layer for phase in asset.phases.values() for layer in phase.layers)]
        for layer in layers:
            name = layer.id or f"layers.{layer.index}"
            tops[name] = (layer.inst, min(127, round(layer.top_midi())), layer.line, name)
    else:
        from segan.sequence import build_timeline, placed_notes

        for variant in [None, *asset.all_variants().values()]:
            kit = variant.kit if variant is not None and variant.kit is not None else asset.kit
            for p in placed_notes(asset, build_timeline(asset, variant, asset.played_sections()), variant):
                inst = kit.instruments.get(p.key)
                if inst is None or asset.tracks[p.note.track].drums:
                    continue
                current = tops.get(p.key)
                if current is None or p.midi > current[1]:
                    tops[p.key] = (inst, int(p.midi), None, inst.name or p.key)
    out = []
    for inst, midi, line, name in tops.values():
        value = aliasing(inst, midi, ctx)
        if value is not None and value > threshold:
            out.append(Finding("W010", f"{name} aliases at {value:.0f} dB on its highest note here (limit {threshold:g} dB): raise [mix] oversample "
                               "(segan config set mix.oversample 4), or play it lower / use a softer wave", asset.path, line, name))  # fmt: skip
    return out
