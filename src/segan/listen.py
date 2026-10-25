"""Listen sheets: how an agent "looks" at sound.

One PNG, every panel on one time axis, top to bottom: header (numbers), arrangement strip (songs), piano
roll per track (from the source, so exact), waveform (clipping in red), log-frequency spectrogram (octave
lines, beat grid, detected pitch for SFX) and a loudness curve (songs). Also: the loop-seam view, the kit
sheet (instrument segments) and the gallery (every asset side by side + loudness by category).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from segan.analysis import PitchTrack, frames_of, momentary_lufs, short_term_lufs

SHORT_CUE_SECONDS = 6.0  # under this the loudness curve is momentary (400 ms), not short-term (3 s)
from segan.dsp import Signal

WIDTH = 1200
LEFT = 74
RIGHT = 16
PLOT = WIDTH - LEFT - RIGHT
BG = (16, 20, 26)
PANEL = (22, 27, 34)
GRID = (44, 52, 62)
GRID_STRONG = (78, 90, 104)
TEXT = (216, 222, 233)
DIM = (140, 150, 165)
WAVE = (127, 211, 255)
CLIP = (255, 64, 64)
PITCH = (80, 255, 200)
LOOP = (255, 200, 60)
MARKER = (255, 110, 220)
GOOD = (120, 220, 140)
WARN = (255, 190, 80)
BAD = (255, 90, 90)
TRACK_COLOURS = [(255, 170, 70), (110, 200, 255), (190, 140, 255), (120, 230, 150), (255, 120, 150), (230, 230, 110), (120, 240, 240), (255, 150, 230)]
SPEC_LOW, SPEC_HIGH = 30.0, 16000.0
SPEC_FLOOR = -100.0


def font(size: int = 12) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _colormap() -> np.ndarray:
    stops = [(0.0, (8, 8, 16)), (0.25, (60, 15, 110)), (0.5, (170, 40, 110)), (0.7, (240, 90, 50)), (0.87, (252, 190, 40)), (1.0, (255, 255, 220))]
    xs = np.linspace(0, 1, 256)
    out = np.zeros((256, 3))
    for c in range(3):
        out[:, c] = np.interp(xs, [s[0] for s in stops], [s[1][c] for s in stops])
    return out.astype(np.uint8)


CMAP = _colormap()


@dataclass(frozen=True)
class RollNote:
    row: int  # index into the track's rows (0 = top)
    start: float  # seconds
    end: float
    key: str
    velocity: float = 1.0


@dataclass(frozen=True)
class RollTrack:
    name: str
    rows: list[str]  # row labels, top first (note names or drum keys)
    notes: list[RollNote]
    drums: bool = False
    colours: dict[str, tuple[int, int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class Block:
    """A labelled stretch of time: arrangement sections/patterns, or kit-sheet instruments."""

    label: str
    start: float
    end: float
    sub: str = ""


@dataclass
class SheetSpec:
    title: str
    stats: list[tuple[str, str, tuple[int, int, int]]]  # label, value, colour
    audio: Signal
    rate: int
    start: float = 0.0  # visible window (seconds)
    end: float | None = None
    beats: list[float] = field(default_factory=list)
    bars: list[tuple[float, int]] = field(default_factory=list)  # time, bar number
    blocks: list[Block] = field(default_factory=list)
    sub_blocks: list[Block] = field(default_factory=list)
    tracks: list[RollTrack] = field(default_factory=list)
    loop: tuple[float, float] | None = None
    markers: list[tuple[str, float]] = field(default_factory=list)
    pitch: PitchTrack | None = None
    pitch_targets: list[tuple[float, float, float]] = field(default_factory=list)  # start, end, Hz intended
    loudness_curve: bool = False
    notes: list[str] = field(default_factory=list)  # free-text lines under the header


class Canvas:
    def __init__(self, spec: SheetSpec) -> None:
        self.spec = spec
        total = len(spec.audio) / spec.rate
        self.t0 = max(0.0, spec.start)
        self.t1 = min(total, spec.end) if spec.end is not None else total
        if self.t1 <= self.t0:
            self.t1 = self.t0 + 1e-3

    def x(self, t: float) -> float:
        return LEFT + (t - self.t0) / (self.t1 - self.t0) * PLOT

    def visible(self, a: float, b: float) -> bool:
        return b >= self.t0 and a <= self.t1


def _time_step(span: float) -> float:
    for step in (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60):
        if span / step <= 14:
            return step
    return 120.0


def _grid(draw: ImageDraw.ImageDraw, c: Canvas, top: int, bottom: int) -> None:
    """Bar lines (strong) and beat lines; plain time ticks when there's no musical grid."""
    if c.spec.bars or c.spec.beats:
        for beat in c.spec.beats:
            if c.t0 <= beat <= c.t1:
                draw.line([(c.x(beat), top), (c.x(beat), bottom)], fill=GRID)
        for bar, _ in c.spec.bars:
            if c.t0 <= bar <= c.t1:
                draw.line([(c.x(bar), top), (c.x(bar), bottom)], fill=GRID_STRONG)
    else:
        step = _time_step(c.t1 - c.t0)
        t = math.ceil(c.t0 / step) * step
        while t <= c.t1 + 1e-9:
            draw.line([(c.x(t), top), (c.x(t), bottom)], fill=GRID)
            t += step
    if c.spec.loop is not None:
        for edge in c.spec.loop:
            if c.t0 <= edge <= c.t1:
                draw.line([(c.x(edge), top), (c.x(edge), bottom)], fill=LOOP, width=2)
    for _, at in c.spec.markers:
        if c.t0 <= at <= c.t1:
            draw.line([(c.x(at), top), (c.x(at), bottom)], fill=MARKER)


def _axis(draw: ImageDraw.ImageDraw, c: Canvas, y: int) -> int:
    f = font(11)
    if c.spec.bars:
        shown = [(t, n) for t, n in c.spec.bars if c.t0 <= t <= c.t1]
        every = max(1, math.ceil(len(shown) / 24))
        for i, (t, n) in enumerate(shown):
            if i % every == 0:
                draw.text((c.x(t) + 2, y), str(n), fill=DIM, font=f)
        draw.text((6, y), "bar", fill=DIM, font=f)
    step = _time_step(c.t1 - c.t0)
    t = math.ceil(c.t0 / step) * step
    row = y + (13 if c.spec.bars else 0)
    while t <= c.t1 + 1e-9:
        label = f"{t:g}s" if step >= 1 else f"{t:.2f}".rstrip("0").rstrip(".") + "s"
        draw.text((c.x(t) + 2, row), label, fill=DIM, font=f)
        t += step
    if not c.spec.bars:
        draw.text((6, row), "time", fill=DIM, font=f)
    return row + 14 - y


# --- panels --------------------------------------------------------------------------------------


def fit_text(draw: ImageDraw.ImageDraw, text: str, width: float, f: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> str:
    """`text`, shortened with "..." to fit `width` pixels."""
    if draw.textlength(text, font=f) <= width:
        return text
    while text and draw.textlength(text + "...", font=f) > width:
        text = text[:-1]
    return text + "..."


def _header(draw: ImageDraw.ImageDraw, spec: SheetSpec, y: int) -> int:
    draw.text((10, y), fit_text(draw, spec.title, WIDTH - 20, font(18)), fill=TEXT, font=font(18))
    y += 26
    x = 10
    f = font(12)
    for label, value, colour in spec.stats:
        text_label = f"{label} "
        draw.text((x, y), text_label, fill=DIM, font=f)
        lx = x + draw.textlength(text_label, font=f)
        draw.text((lx, y), value, fill=colour, font=f)
        x = int(lx + draw.textlength(value, font=f) + 18)
        if x > WIDTH - 180:
            x, y = 10, y + 16
    y += 18
    for line in spec.notes:
        draw.text((10, y), fit_text(draw, line, WIDTH - 20, f), fill=DIM, font=f)
        y += 15
    return y + 4


def _blocks_panel(draw: ImageDraw.ImageDraw, c: Canvas, blocks: list[Block], y: int, height: int, label: str) -> int:
    draw.rectangle([LEFT, y, LEFT + PLOT, y + height], fill=PANEL)
    draw.text((6, y + height // 2 - 7), label, fill=DIM, font=font(11))
    f = font(11)
    for i, block in enumerate(blocks):
        if not c.visible(block.start, block.end):
            continue
        a, b = max(c.x(block.start), LEFT), min(c.x(block.end), LEFT + PLOT)
        colour = TRACK_COLOURS[i % len(TRACK_COLOURS)]
        fill = tuple(int(v * 0.35 + 22 * 0.65) for v in colour)
        draw.rectangle([a, y + 1, b - 1, y + height - 1], fill=fill, outline=colour)
        text = block.label + (f" {block.sub}" if block.sub else "")
        if draw.textlength(text, font=f) > b - a - 4:
            text = block.label
        if draw.textlength(text, font=f) <= b - a - 4:
            draw.text((a + 3, y + height // 2 - 7), text, fill=TEXT, font=f)
    if label == "sections" or (label == "parts"):
        for name, at in c.spec.markers:
            if c.t0 <= at <= c.t1:
                draw.text((c.x(at) + 2, y - 1), f"v {name}", fill=MARKER, font=f)
    return height + 4


def _roll_panel(draw: ImageDraw.ImageDraw, c: Canvas, track: RollTrack, y: int) -> int:
    rows = max(1, len(track.rows))
    row_h = max(3, min(12, 160 // rows))
    height = rows * row_h
    draw.rectangle([LEFT, y, LEFT + PLOT, y + height], fill=PANEL)
    f = font(10)
    for i, label in enumerate(track.rows):
        top = y + i * row_h
        is_c = label.startswith("C") and not label.startswith("C#") and not track.drums
        if is_c or track.drums:
            draw.line([(LEFT, top + row_h), (LEFT + PLOT, top + row_h)], fill=GRID)
        if track.drums or is_c or rows <= 12:
            if row_h >= 9 or is_c or track.drums:
                draw.text((LEFT - 30, top + row_h // 2 - 6), label, fill=DIM, font=f)
    _grid(draw, c, y, y + height)
    draw.text((6, y + 2), track.name[:9], fill=TEXT, font=font(11))
    for note in track.notes:
        if not c.visible(note.start, note.end):
            continue
        colour = track.colours.get(note.key, TRACK_COLOURS[0])
        a = max(c.x(note.start), LEFT)
        b = max(a + 2, min(c.x(note.end), LEFT + PLOT))
        top = y + note.row * row_h
        shade = 0.45 + 0.55 * min(1.0, note.velocity)
        fill = tuple(int(v * shade) for v in colour)
        draw.rectangle([a, top + 1, b - 1, top + row_h - 1], fill=fill)
        if row_h >= 9 and draw.textlength(note.key, font=f) <= b - a - 3:
            draw.text((a + 2, top + row_h // 2 - 6), note.key, fill=(10, 10, 10), font=f)
    return height + 4


def _wave_panel(draw: ImageDraw.ImageDraw, c: Canvas, y: int, height: int) -> int:
    spec = c.spec
    draw.rectangle([LEFT, y, LEFT + PLOT, y + height], fill=PANEL)
    _grid(draw, c, y, y + height)
    mid = y + height / 2
    draw.line([(LEFT, mid), (LEFT + PLOT, mid)], fill=GRID_STRONG)
    for level in (0.5, -0.5):
        yy = mid - level * height / 2
        draw.line([(LEFT, yy), (LEFT + PLOT, yy)], fill=GRID)
    draw.text((6, y + 2), "wave", fill=TEXT, font=font(11))
    draw.text((LEFT - 22, y - 1), "+1", fill=DIM, font=font(10))
    draw.text((LEFT - 22, y + height - 12), "-1", fill=DIM, font=font(10))
    data = frames_of(spec.audio)
    a, b = int(c.t0 * spec.rate), min(len(data), int(math.ceil(c.t1 * spec.rate)))
    window = data[a:b]
    if len(window) == 0:
        return height + 4
    edges = np.linspace(0, len(window), PLOT + 1).astype(np.int64)
    lo_all = window.min(axis=1)
    hi_all = window.max(axis=1)
    clipped = np.abs(window).max(axis=1) >= 32766.5 / 32767.0
    for col in range(PLOT):
        s, e = edges[col], max(edges[col] + 1, edges[col + 1])
        lo, hi = float(lo_all[s:e].min()), float(hi_all[s:e].max())
        x = LEFT + col
        y_hi = mid - max(-1.0, min(1.0, hi)) * (height / 2 - 1)
        y_lo = mid - max(-1.0, min(1.0, lo)) * (height / 2 - 1)
        colour = CLIP if clipped[s:e].any() else WAVE
        draw.line([(x, y_hi), (x, max(y_lo, y_hi + 1))], fill=colour)
    return height + 4


def spectrogram_image(audio: Signal, rate: int, t0: float, t1: float, width: int, height: int) -> np.ndarray:
    """Log-frequency magnitude image (rows = 30 Hz .. 16 kHz, top = high), dBFS-scaled (a full-scale sine = 0 dB)."""
    m = frames_of(audio).mean(axis=1)
    size = 4096 if rate >= 32000 else 2048
    window = np.hanning(size)
    centres = np.linspace(t0, t1, width, endpoint=False) + (t1 - t0) / width / 2
    starts = np.clip((centres * rate).astype(np.int64) - size // 2, -size, len(m))
    padded = np.pad(m, (size, size))
    frames = np.stack([padded[s + size : s + 2 * size] for s in starts])
    mags = np.abs(np.fft.rfft(frames * window, axis=1)) / (window.sum() / 2)
    db = 20 * np.log10(np.maximum(mags, 1e-9))
    freqs = np.fft.rfftfreq(size, 1.0 / rate)
    high = min(SPEC_HIGH, rate * 0.48)
    row_f = np.exp(np.linspace(math.log(high), math.log(SPEC_LOW), height + 1))
    image = np.zeros((height, width))
    for r in range(height):
        fa, fb = row_f[r + 1], row_f[r]
        ia, ib = np.searchsorted(freqs, fa), np.searchsorted(freqs, fb)
        if ib > ia:
            image[r] = db[:, ia:ib].max(axis=1)
        else:  # narrower than one FFT bin (low notes): interpolate between the two nearest bins
            position = math.sqrt(fa * fb) / (rate / size)
            k = min(int(position), len(freqs) - 2)
            w = position - k
            image[r] = db[:, k] * (1 - w) + db[:, k + 1] * w
    norm = np.clip((image - SPEC_FLOOR) / -SPEC_FLOOR, 0.0, 1.0)
    return CMAP[(norm * 255).astype(np.uint8)]


def freq_to_y(f: float, top: int, height: int, rate: int) -> float:
    high = min(SPEC_HIGH, rate * 0.48)
    return top + (math.log(high) - math.log(f)) / (math.log(high) - math.log(SPEC_LOW)) * height


def _spec_panel(img: Image.Image, draw: ImageDraw.ImageDraw, c: Canvas, y: int, height: int) -> int:
    spec = c.spec
    pixels = spectrogram_image(spec.audio, spec.rate, c.t0, c.t1, PLOT, height)
    img.paste(Image.fromarray(pixels, "RGB"), (LEFT, y))
    f = font(10)
    for octave in range(1, 10):
        hz = 440.0 * 2 ** ((12 * (octave + 1) - 69) / 12)  # C of each octave
        if SPEC_LOW <= hz <= min(SPEC_HIGH, spec.rate * 0.48):
            yy = freq_to_y(hz, y, height, spec.rate)
            draw.line([(LEFT, yy), (LEFT + PLOT, yy)], fill=(70, 70, 90))
            draw.text((LEFT - 40, yy - 6), f"C{octave} ", fill=DIM, font=f)
            draw.text((LEFT - 70, yy - 6), f"{hz:.0f}" if hz < 1000 else f"{hz / 1000:.1f}k", fill=(100, 108, 120), font=f)
    for bar, _ in spec.bars:
        if c.t0 <= bar <= c.t1:
            draw.line([(c.x(bar), y), (c.x(bar), y + 6)], fill=GRID_STRONG)
    for start, end, hz in spec.pitch_targets:
        if c.visible(start, end) and SPEC_LOW <= hz <= SPEC_HIGH:
            yy = freq_to_y(hz, y, height, spec.rate)
            draw.line([(max(LEFT, c.x(start)), yy), (min(LEFT + PLOT, c.x(end)), yy)], fill=(255, 255, 255), width=1)
    if spec.pitch is not None:
        for t, hz in zip(spec.pitch.times, spec.pitch.hz, strict=True):
            if hz > 0 and c.t0 <= t <= c.t1 and SPEC_LOW <= hz <= SPEC_HIGH:
                xx, yy = c.x(float(t)), freq_to_y(float(hz), y, height, spec.rate)
                draw.rectangle([xx - 1, yy - 1, xx + 1, yy + 1], fill=PITCH)
    if spec.loop is not None:
        for edge in spec.loop:
            if c.t0 <= edge <= c.t1:
                draw.line([(c.x(edge), y), (c.x(edge), y + height)], fill=LOOP, width=2)
    draw.text((6, y + 2), "spectrum", fill=TEXT, font=font(11))
    return height + 4


def _loudness_panel(draw: ImageDraw.ImageDraw, c: Canvas, y: int, height: int, target: float | None) -> int:
    spec = c.spec
    draw.rectangle([LEFT, y, LEFT + PLOT, y + height], fill=PANEL)
    _grid(draw, c, y, y + height)
    short = len(spec.audio) < SHORT_CUE_SECONDS * spec.rate  # a 3 s window says little about a 2-6 s cue (#73)
    curve = momentary_lufs(spec.audio, spec.rate) if short else short_term_lufs(spec.audio, spec.rate)
    centre = 0.2 if short else 1.5
    lo, hi = -40.0, 0.0

    def yy(v: float) -> float:
        return y + (hi - max(lo, min(hi, v))) / (hi - lo) * height

    for level in (-10, -20, -30):
        draw.line([(LEFT, yy(level)), (LEFT + PLOT, yy(level))], fill=GRID)
        draw.text((LEFT - 28, yy(level) - 6), str(level), fill=DIM, font=font(10))
    if target is not None:
        draw.line([(LEFT, yy(target)), (LEFT + PLOT, yy(target))], fill=GOOD)
    points = []
    for i, v in enumerate(curve):
        t = i * 0.1 + centre  # window centre
        if c.t0 <= t <= c.t1:
            points.append((c.x(t), yy(float(v))))
    if len(points) > 1:
        draw.line(points, fill=WARN, width=2)
    draw.text((6, y + 2), "LUFS-M" if short else "LUFS-S", fill=TEXT, font=font(11))
    return height + 4


def listen_sheet(spec: SheetSpec, target: float | None = None) -> Image.Image:
    """Render a listen sheet. `target` draws the loudness target on the loudness curve."""
    c = Canvas(spec)
    roll_h = sum(max(1, len(t.rows)) * max(3, min(12, 160 // max(1, len(t.rows)))) + 4 for t in spec.tracks)
    est = 60 + 16 * (len(spec.stats) // 5 + 1) + 15 * len(spec.notes) + 30 * bool(spec.blocks) + 30 * bool(spec.sub_blocks)
    est += roll_h + 124 + 264 + (74 if spec.loudness_curve else 0) + 40
    img = Image.new("RGB", (WIDTH, est), BG)
    draw = ImageDraw.Draw(img)
    y = _header(draw, spec, 8)
    if spec.blocks:
        y += _blocks_panel(draw, c, spec.blocks, y, 22, "sections" if spec.bars else "parts")
    if spec.sub_blocks:
        y += _blocks_panel(draw, c, spec.sub_blocks, y, 20, "patterns")
    for track in spec.tracks:
        y += _roll_panel(draw, c, track, y)
    y += _wave_panel(draw, c, y, 120)
    y += _spec_panel(img, draw, c, y, 260)
    if spec.loudness_curve:
        y += _loudness_panel(draw, c, y, 70, target)
    y += _axis(draw, c, y)
    return img.crop((0, 0, WIDTH, y + 4))


# --- seam view --------------------------------------------------------------------------------


def seam_sheet(title: str, audio: Signal, rate: int, start: int, end: int, click: float, threshold: float) -> Image.Image:
    """The loop's last second + first second spliced together (what the player hears at the loop point),
    plus a +/-10 ms zoom on the splice. A click shows as a jump in the zoom and a vertical line in the spectrum."""
    data = frames_of(audio)
    span = min(rate, (end - start) // 2)
    joined = np.concatenate([data[end - span : end], data[start : start + span]])
    stats = [("splice click", f"{click:.4f}", BAD if click > threshold else GOOD), ("threshold", f"{threshold:g}", DIM),
             ("loop", f"{start}..{end} samples", DIM)]  # fmt: skip
    spec = SheetSpec(f"{title} - loop seam (end | start)", stats, joined, rate, loop=(span / rate, span / rate))
    sheet = listen_sheet(spec)
    zoom_h = 140
    out = Image.new("RGB", (WIDTH, sheet.height + zoom_h + 24), BG)
    out.paste(sheet, (0, 0))
    draw = ImageDraw.Draw(out)
    y = sheet.height + 4
    draw.text((6, y), "±10 ms around the splice (samples)", fill=TEXT, font=font(11))
    y += 16
    zoom = joined[span - rate // 100 : span + rate // 100]
    draw.rectangle([LEFT, y, LEFT + PLOT, y + zoom_h], fill=PANEL)
    mid = y + zoom_h / 2
    draw.line([(LEFT, mid), (LEFT + PLOT, mid)], fill=GRID_STRONG)
    peak = max(1e-6, float(np.abs(zoom).max()))
    for ch in range(zoom.shape[1]):
        points = [(LEFT + i / max(1, len(zoom) - 1) * PLOT, mid - zoom[i, ch] / peak * (zoom_h / 2 - 4)) for i in range(len(zoom))]
        draw.line(points, fill=WAVE if ch == 0 else (200, 160, 255))
    xs = LEFT + PLOT / 2
    draw.line([(xs, y), (xs, y + zoom_h)], fill=MARKER, width=1)
    return out


# --- gallery ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class GalleryItem:
    name: str
    category: str
    audio: Signal
    rate: int
    lufs: float
    target: float | None
    peak: float


def gallery_image(items: Sequence[GalleryItem], title: str) -> Image.Image:
    """Every asset's mini waveform + spectrogram in a grid, then a loudness bar chart by category."""
    cols = 4
    cell_w, wave_h, spec_h = (WIDTH - 20) // cols, 40, 70
    cell_h = 18 + wave_h + spec_h + 10
    rows = max(1, math.ceil(len(items) / cols))
    chart_h = 30 + 18 * len(items) + 20
    img = Image.new("RGB", (WIDTH, 40 + rows * cell_h + chart_h), BG)
    draw = ImageDraw.Draw(img)
    draw.text((10, 8), title, fill=TEXT, font=font(18))
    f = font(11)
    for i, item in enumerate(items):
        x = 10 + (i % cols) * cell_w
        y = 40 + (i // cols) * cell_h
        draw.text((x, y), f"{item.name}  [{item.category}]", fill=TEXT, font=f)
        y += 16
        w = cell_w - 10
        draw.rectangle([x, y, x + w, y + wave_h], fill=PANEL)
        data = frames_of(item.audio)
        if len(data):
            edges = np.linspace(0, len(data), w + 1).astype(np.int64)
            mid = y + wave_h / 2
            for col in range(w):
                seg = data[edges[col] : max(edges[col] + 1, edges[col + 1])]
                hi, lo = float(seg.max()), float(seg.min())
                draw.line([(x + col, mid - hi * (wave_h / 2 - 1)), (x + col, mid - lo * (wave_h / 2 - 1))], fill=WAVE)
            pixels = spectrogram_image(item.audio, item.rate, 0.0, len(data) / item.rate, w, spec_h)
            img.paste(Image.fromarray(pixels, "RGB"), (x, y + wave_h + 2))
        draw.text((x + w - 120, y + 1), f"{len(data) / item.rate:.2f}s {item.lufs:.1f} LUFS", fill=DIM, font=font(10))
    y = 40 + rows * cell_h + 10
    draw.text((10, y), "loudness by asset (bar = LUFS, tick = category target)", fill=TEXT, font=f)
    y += 18
    lo, hi = -40.0, 0.0
    order = sorted(items, key=lambda it: (it.category, it.name))
    for item in order:
        draw.text((10, y), f"{item.category}/{item.name}"[:28], fill=DIM, font=f)
        x0 = 230
        span = WIDTH - x0 - 80

        def px(v: float) -> float:
            return x0 + (max(lo, min(hi, v)) - lo) / (hi - lo) * span

        off = abs(item.lufs - item.target) if item.target is not None else 0.0
        colour = GOOD if off <= 1.0 else WARN if off <= 3.0 else BAD
        draw.rectangle([x0, y + 2, px(item.lufs), y + 12], fill=colour)
        if item.target is not None:
            draw.line([(px(item.target), y), (px(item.target), y + 14)], fill=TEXT, width=2)
        draw.text((x0 + span + 6, y), f"{item.lufs:.1f}", fill=TEXT, font=f)
        y += 18
    return img
