"""Seeded variety at authoring time (#76): `segan kit roll` and `segan suggest song`.

Nothing here changes how a source renders: it proposes sources. Every choice branches from the project seed
(`seed` in segan.toml, picked at random by `segan init`) plus what's being made (the kit or song name, the style
words, a take number), so two projects with the same brief start from different places, while one project gets
the same proposal again for the same request.

- `roll_kit`: a kit from a catalogue of instrument recipes (synth, models, effects, optionally library samples)
  scored against style words, with seeded parameters. A kit has an `identity` group: the game's signature
  instruments, which `--around <kit>` carries into a new kit (a song's extras around the same identity).
- `suggest_song`: key, mode, tempo, meter, opening texture, voicing, progression and instruments for a new song,
  steered away from what the project's songs already use.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from segan.dsp import seed_of, uniform
from segan.notes import Key, note_name, parse_key
from segan.yamlwrite import flow, scalar


class Rng:
    """Deterministic choices from a seed (dsp.uniform: the same on every machine and Python version)."""

    def __init__(self, *parts: object) -> None:
        self.seed = seed_of("suggest", *parts)
        self.count = 0

    def random(self) -> float:
        self.count += 1
        return float(uniform(self.seed, self.count))

    def range(self, lo: float, hi: float, digits: int = 3) -> float:
        return round(lo + (hi - lo) * self.random(), digits)

    def choice(self, items: list[Any] | tuple[Any, ...]) -> Any:
        return items[min(len(items) - 1, int(self.random() * len(items)))]

    def weighted(self, items: list[tuple[Any, float]]) -> Any:
        total = sum(max(w, 0.0) for _, w in items)
        pick = self.random() * total
        for item, weight in items:
            pick -= max(weight, 0.0)
            if pick < 0:
                return item
        return items[-1][0]

    def jitter(self, value: float, spread: float = 0.25, digits: int = 3) -> float:
        """value x 2^(+/- spread octaves)."""
        return round(float(value * 2.0 ** (spread * (2.0 * self.random() - 1.0))), digits)


# --- style words ---------------------------------------------------------------------------------

SYNONYMS = {
    "warm": ("warm", "cosy", "cozy", "human", "crew", "home", "friendly", "tender", "gentle", "analog", "analogue"),
    "cold": ("cold", "icy", "ice", "frozen", "steel", "clinical", "sterile", "winter", "machine", "corporate"),
    "bright": ("bright", "sparkly", "shiny", "happy", "cheerful", "sunny", "upbeat", "joyful"),
    "dark": ("dark", "gloomy", "grim", "brooding", "night", "shadow", "ominous", "dread"),
    "soft": ("soft", "quiet", "calm", "gentle", "lullaby", "sleepy", "peaceful", "mellow", "chill", "relaxed"),
    "hard": ("hard", "loud", "punchy", "heavy", "intense", "driving", "aggressive", "angry", "battle", "combat", "action"),
    "retro": ("retro", "8bit", "8-bit", "chip", "chiptune", "nes", "gameboy", "arcade", "pixel", "16bit", "16-bit"),
    "lofi": ("lofi", "lo-fi", "tape", "dusty", "vintage", "crunchy", "worn"),
    "electronic": ("electronic", "electronics", "synth", "synthwave", "techno", "edm", "trance", "digital", "electro", "cyber", "cyberpunk"),
    "acoustic": ("acoustic", "organic", "natural", "folk", "wood", "wooden", "real", "live", "unplugged"),
    "orchestral": ("orchestral", "orchestra", "cinematic", "epic", "film", "symphonic", "strings", "score", "heroic"),
    "ambient": ("ambient", "atmospheric", "drone", "space", "spacey", "floating", "vast", "ethereal", "dreamy", "dream"),
    "eerie": ("eerie", "creepy", "horror", "haunted", "uneasy", "unsettling", "alien", "strange", "mysterious", "mystery"),
    "world": ("world", "ethnic", "eastern", "asian", "japanese", "african", "desert", "tribal", "celtic", "folk"),
    "jazzy": ("jazzy", "jazz", "lounge", "funky", "funk", "groovy", "swing", "soul"),
    "glassy": ("glassy", "glass", "crystal", "chime", "chimes", "bell", "bells", "magic", "magical", "fairy", "fantasy"),
    "gritty": ("gritty", "dirty", "distorted", "industrial", "grimy", "rough", "noisy", "metal"),
    "playful": ("playful", "cute", "silly", "toy", "whimsical", "quirky", "bouncy", "cartoon"),
}


def style_tags(words: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9-]+", words.lower()))
    return {tag for tag, names in SYNONYMS.items() if tokens & set(names)}


# --- instrument recipes --------------------------------------------------------------------------

Builder = Callable[[Rng], dict[str, Any]]


@dataclass(frozen=True)
class Recipe:
    name: str
    role: str  # bass | lead | harmony | colour | kick | snare | hat | perc | crash
    tags: tuple[str, ...]
    build: Builder
    family: str = ""
    library: str = ""  # a sample library instrument it needs (`vsco2/...`)


def _env(rng: Rng, a: tuple[float, float], d: tuple[float, float], s: tuple[float, float], r: tuple[float, float]) -> list[float]:
    return [rng.range(*a), rng.range(*d), rng.range(*s, digits=2), rng.range(*r)]


def _lp(rng: Rng, cutoff: float, res: tuple[float, float] = (0.0, 0.3), **extra: Any) -> dict[str, Any]:
    return {"type": "lp", "cutoff": round(rng.jitter(cutoff, 0.4), -1), "resonance": rng.range(*res, digits=2), **extra}


R: list[Recipe] = []


def recipe(name: str, role: str, tags: str, family: str = "", library: str = "") -> Callable[[Builder], Builder]:
    def wrap(fn: Builder) -> Builder:
        R.append(Recipe(name, role, tuple(tags.split()), fn, family or name, library))
        return fn

    return wrap


# basses
@recipe("tri_bass", "bass", "retro soft warm playful", "soft")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "triangle", "env": _env(r, (0.001, 0.004), (0.04, 0.1), (0.85, 0.98), (0.03, 0.08)), "range": ["E1", "C4"]}


@recipe("square_bass", "bass", "retro hard electronic playful", "pulse")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pulse", "duty": r.choice([0.5, 0.25, 0.4]), "env": _env(r, (0.001, 0.004), (0.08, 0.2), (0.6, 0.85), (0.04, 0.1)),
            "filter": _lp(r, 900, env_amount=r.range(0.8, 2.0, 2), env=[0.001, r.range(0.08, 0.2), 0.0, 0.05]), "range": ["E1", "C4"]}


@recipe("sub_sine", "bass", "ambient soft dark electronic cold", "soft")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "sine", "sub": {"octave": -1, "level": r.range(-12, -6, 1)}, "env": _env(r, (0.01, 0.05), (0.2, 0.5), (0.85, 1.0), (0.2, 0.5)),
            "range": ["E1", "C4"]}


@recipe("fm_bass", "bass", "electronic hard bright jazzy funky", "fm")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "fm", "fm": {"ratio": r.choice([1, 2]), "index": r.range(1.5, 4, 2), "env": [0.001, r.range(0.1, 0.3), r.range(0.1, 0.3, 2), 0.1]},
            "env": _env(r, (0.001, 0.005), (0.2, 0.5), (0.5, 0.8), (0.05, 0.15)), "range": ["E1", "C4"]}


@recipe("acid_bass", "bass", "electronic gritty hard retro", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "filter": _lp(r, 500, (0.55, 0.8), env_amount=r.range(2, 3.5, 2), env=[0.001, r.range(0.12, 0.3), 0.0, 0.05], slope=24),
            "env": _env(r, (0.001, 0.003), (0.15, 0.3), (0.6, 0.85), (0.03, 0.08)), "fx": [{"drive": {"amount": r.range(0.2, 0.5, 2)}}], "range": ["E1", "C4"]}


@recipe("pluck_bass", "bass", "acoustic warm jazzy world folk", "pluck")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pluck", "pluck": {"preset": "bass", "decay": r.range(1.5, 3.0, 2), "brightness": r.range(0.2, 0.45, 2)}, "range": ["E1", "C4"]}


@recipe("upright_bass", "bass", "orchestral acoustic jazzy dark", "sample", "vsco2/basses_pizz")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/basses_pizz", "voices": 2, "gain": r.range(-2, 1, 1)}


@recipe("moog_bass", "bass", "warm electronic retro funky", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "sub": -1, "filter": _lp(r, 700, (0.2, 0.45), slope=24, env_amount=r.range(1, 2, 2), env=[0.002, r.range(0.15, 0.35), 0.2, 0.1]),
            "env": _env(r, (0.002, 0.006), (0.2, 0.4), (0.7, 0.9), (0.05, 0.12)), "range": ["E1", "C4"]}


# leads
@recipe("pulse_lead", "lead", "retro bright playful chip", "pulse")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pulse", "duty": r.choice([0.125, 0.25, 0.5]), "env": _env(r, (0.002, 0.01), (0.05, 0.15), (0.5, 0.75), (0.06, 0.15)),
            "vibrato": [r.range(5, 6.5, 1), r.range(0.05, 0.15, 2), r.range(0.1, 0.25, 2)], "range": ["C4", "C7"]}


@recipe("sync_lead", "lead", "electronic hard bright retro gritty", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "sync": {"ratio": r.range(1.5, 2.5, 2), "env_amount": r.range(1, 2, 2), "env": [0.001, r.range(0.2, 0.5), 0.2, 0.2]},
            "filter": _lp(r, 4000), "env": _env(r, (0.002, 0.01), (0.2, 0.4), (0.6, 0.8), (0.1, 0.2)), "range": ["C3", "C6"]}


@recipe("flute_additive", "lead", "soft acoustic world ambient warm fantasy", "additive")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "additive", "additive": r.choice(["flute", "hollow"]), "vibrato": [r.range(4.5, 5.5, 1), r.range(0.08, 0.15, 2), 0.3],
            "env": _env(r, (0.05, 0.12), (0.2, 0.4), (0.75, 0.9), (0.15, 0.3)), "fx": [{"reverb": {"mix": r.range(0.15, 0.3, 2), "decay": r.range(1.2, 2.2, 1)}}],
            "range": ["C4", "C7"]}


@recipe("vocal_lead", "lead", "ambient dreamy eerie warm orchestral", "formant")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "formant", "formant": {"vowel": r.choice(["oo", "ah", "oh"]), "voice": r.choice(["soprano", "alto"])},
            "vibrato": [r.range(4.8, 5.8, 1), r.range(0.1, 0.2, 2), 0.25], "env": _env(r, (0.08, 0.2), (0.2, 0.4), (0.8, 0.95), (0.3, 0.6)), "range": ["C4", "C6"]}


@recipe("wavetable_lead", "lead", "electronic cold bright glassy", "wavetable")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "wavetable", "wavetable": {"table": r.choice(["digital", "harmonic", "pulse", "sync"]), "position": r.range(0.1, 0.5, 2),
            "env": [0.01, r.range(0.4, 1.2), 0.3, 0.5], "env_amount": r.range(0.2, 0.5, 2)},
            "env": _env(r, (0.005, 0.02), (0.2, 0.4), (0.6, 0.85), (0.15, 0.3)), "fx": [{"delay": {"time": r.choice(["1/8.", "1/4", "1/8"]), "feedback": r.range(0.2, 0.4, 2), "mix": 0.2}}],
            "range": ["C4", "C7"]}  # fmt: skip


@recipe("glide_saw", "lead", "electronic warm retro hard", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "unison": 2, "detune": r.range(4, 9, 1), "filter": _lp(r, 2500, (0.1, 0.35)), "pitch_env": [r.choice([-2, -1, 2]), 0.04],
            "env": _env(r, (0.004, 0.02), (0.2, 0.4), (0.6, 0.85), (0.1, 0.25)), "fx": [{"chorus": {"mix": r.range(0.2, 0.4, 2)}}], "range": ["C3", "C6"]}


@recipe("violin_solo", "lead", "orchestral acoustic warm folk", "sample", "vsco2/violin_solo")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/violin_solo", "env": [0.05, 0.0, 1.0, 0.3], "vibrato": [5.2, 0.08, 0.3]}


@recipe("muted_trumpet", "lead", "jazzy orchestral warm", "sample", "vsco2/trumpet_sus")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/trumpet_sus", "mute": r.choice(["harmon", "cup", "straight"]), "env": [0.03, 0.0, 1.0, 0.2]}


@recipe("fm_lead", "lead", "bright electronic glassy retro", "fm")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "fm", "fm": {"algorithm": "stack", "ops": [{"ratio": 1}, {"ratio": r.choice([1, 2, 3]), "index": r.range(0.8, 2.0, 2)},
            {"ratio": r.choice([4, 5, 7]), "index": r.range(0.2, 0.6, 2), "env": [0.001, 0.2, 0.0, 0.1]}]},
            "env": _env(r, (0.003, 0.01), (0.2, 0.5), (0.5, 0.8), (0.1, 0.25)), "range": ["C4", "C7"]}  # fmt: skip


# harmony (pads, strings, choirs, organs, keys)
@recipe("bowed_section", "harmony", "orchestral acoustic warm dark epic", "bowed")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "bowed", "bowed": {"body": "auto", "bow": r.range(0.2, 0.4, 2)}, "unison": r.choice([4, 5, 6]), "detune": r.range(4, 8, 1), "voices": 5,
            "env": _env(r, (0.15, 0.4), (0.2, 0.5), (0.85, 1.0), (0.4, 0.8)), "vibrato": [r.range(4.8, 5.6, 1), r.range(0.06, 0.12, 2), 0.3],
            "fx": ["ensemble"], "range": ["G2", "E6"]}  # fmt: skip


@recipe("choir", "harmony", "orchestral eerie ambient dark epic dreamy", "formant")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "formant", "formant": {"vowel": r.choice([["ah", "oh"], "oo", "ah", ["oh", "oo"]]), "voice": "auto"}, "unison": r.choice([4, 5, 6]),
            "detune": r.range(6, 10, 1), "voices": 4, "env": _env(r, (0.3, 0.6), (0.3, 0.6), (0.85, 1.0), (0.6, 1.2)), "range": ["C3", "C5"]}  # fmt: skip


@recipe("glass_pad", "harmony", "glassy cold ambient electronic dreamy", "wavetable")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "wavetable", "wavetable": {"table": r.choice(["glass", "vocal", "harmonic"]), "lfo": [r.range(0.1, 0.4, 2), r.range(0.3, 0.7, 2)]},
            "unison": 2, "detune": r.range(5, 10, 1), "voices": 5, "env": _env(r, (0.5, 1.5), (0.5, 1.0), (0.7, 0.9), (1.0, 2.0)),
            "fx": [{"reverb": {"mix": r.range(0.25, 0.45, 2), "decay": r.range(2, 4, 1)}}], "range": ["C3", "C6"]}  # fmt: skip


@recipe("string_machine", "harmony", "retro warm electronic dreamy", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "filter": _lp(r, 3000), "voices": 6, "env": _env(r, (0.2, 0.6), (0.3, 0.6), (0.8, 0.95), (0.4, 0.9)),
            "fx": [{"ensemble": {"depth": r.range(0.4, 0.8, 2)}}], "range": ["C3", "C6"]}


@recipe("organ", "harmony", "warm jazzy retro eerie", "additive")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "additive", "additive": {"drawbars": r.choice(["888000000", "008800000", "868000000", "808000008", "888400000"])}, "voices": 5,
            "env": [0.005, 0.0, 1.0, 0.08], "fx": [{"chorus": {"rate": r.range(5, 7, 1), "depth": 1.2, "mix": 0.35}}], "range": ["C3", "C6"]}  # fmt: skip


@recipe("supersaw_pad", "harmony", "electronic bright epic hard", "supersaw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "supersaw", "supersaw": {"spread": r.range(20, 40, 1), "mix": r.range(0.4, 0.7, 2)}, "filter": _lp(r, 5000), "voices": 5,
            "env": _env(r, (0.05, 0.3), (0.3, 0.6), (0.7, 0.9), (0.3, 0.7)), "range": ["C3", "C6"]}


@recipe("warm_pad", "harmony", "warm soft ambient electronic", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "unison": r.choice([2, 3, 4]), "detune": r.range(6, 15, 1), "filter": _lp(r, 1300, lfo=[r.range(0.1, 0.3, 2), r.range(0.3, 0.8, 2)]),
            "voices": 5, "env": _env(r, (0.5, 1.4), (0.5, 1.2), (0.75, 0.9), (1.0, 2.2)), "range": ["A2", "D5"]}


@recipe("fm_keys", "harmony", "soft warm jazzy electronic", "fm")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "fm", "fm": {"ratio": 1, "index": r.range(0.8, 1.6, 2), "env": [0.001, r.range(0.6, 1.0, 2), 0.15, 0.4]}, "voices": 4,
            "env": [0.004, r.range(2.0, 3.0, 1), 0.0, r.range(0.5, 0.9, 2), "exp"], "tremolo": [r.range(3.5, 5, 1), r.range(0.05, 0.12, 2)], "range": ["A2", "D6"]}


@recipe("piano", "harmony", "acoustic warm soft jazzy orchestral", "sample", "vsco2/piano")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/piano", "voices": 8, "max_ring": r.range(1.0, 2.0, 1)}


@recipe("strings", "harmony", "orchestral acoustic epic warm", "sample", "vsco2/violins_sus")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/violins_sus", "voices": 4, "env": [r.range(0.04, 0.2, 2), 0.0, 1.0, 0.4]}


# colour (plucks, mallets, bells, arps, textures)
@recipe("nylon", "colour", "acoustic warm soft world folk", "pluck")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pluck", "pluck": {"preset": r.choice(["nylon", "guitar", "steel"]), "brightness": r.range(0.3, 0.6, 2)}, "voices": 6, "range": ["E2", "B5"]}


@recipe("koto", "colour", "world eastern acoustic bright", "pluck")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pluck", "pluck": {"preset": "koto", "decay": r.range(1.5, 2.5, 2)}, "voices": 4, "vibrato": [5, 0.05, 0.3], "range": ["C3", "C6"]}


@recipe("harp", "colour", "fantasy orchestral soft dreamy glassy", "pluck")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pluck", "pluck": {"preset": "harp", "brightness": r.range(0.35, 0.55, 2)}, "voices": 8, "range": ["C2", "C7"]}


@recipe("marimba", "colour", "playful warm acoustic world soft", "modal")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "modal", "modal": {"material": r.choice(["marimba", "wood", "kalimba"]), "strike": r.range(0.3, 0.6, 2)}, "voices": 4, "range": ["C3", "C6"]}


@recipe("vibes", "colour", "jazzy soft dreamy warm", "modal")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "modal", "modal": {"material": "vibraphone", "strike": r.range(0.3, 0.5, 2)}, "tremolo": [r.range(4, 6, 1), r.range(0.15, 0.3, 2)],
            "voices": 4, "range": ["F3", "F6"]}


@recipe("glass_bell", "colour", "glassy cold bright fantasy eerie", "modal")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "modal", "modal": {"material": r.choice(["glass", "tubular", "bell"]), "strike": r.range(0.4, 0.8, 2)}, "voices": 4,
            "fx": [{"delay": {"time": r.choice(["1/4", "1/8."]), "feedback": r.range(0.25, 0.45, 2), "mix": 0.25}}], "range": ["C4", "C7"]}


@recipe("steel_drum", "colour", "playful bright world", "modal")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "modal", "modal": {"material": "steel_drum", "strike": r.range(0.4, 0.7, 2)}, "voices": 3, "range": ["C4", "C6"]}


@recipe("pulse_arp", "colour", "retro electronic bright playful", "pulse")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pulse", "duty": r.choice([0.25, 0.3, 0.125]), "filter": _lp(r, 2000, env_amount=1.2, env=[0.002, 0.15, 0.0, 0.1]),
            "env": _env(r, (0.002, 0.005), (0.2, 0.4), (0.0, 0.1), (0.1, 0.2)), "voices": 2, "range": ["C3", "C6"]}


@recipe("fm_bell", "colour", "glassy cold bright electronic", "fm")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "fm", "fm": {"ratio": r.choice([3.5, 1.4, 2.76]), "index": r.range(1, 2, 2), "env": [0.001, 0.6, 0.1, 0.3]}, "voices": 4,
            "env": [0.002, r.range(1.5, 2.5, 1), 0.0, 1.0, "exp"], "range": ["C4", "C7"]}


@recipe("phased_saw", "colour", "electronic dreamy retro ambient", "saw")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "saw", "filter": _lp(r, 2200), "env": _env(r, (0.01, 0.05), (0.3, 0.6), (0.4, 0.7), (0.3, 0.6)), "voices": 3,
            "fx": [{"phaser": {"rate": r.choice(["1/2", "1", "2"]), "mix": 0.5}}], "range": ["C3", "C6"]}


@recipe("bit_texture", "colour", "lofi retro gritty eerie", "noise")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "bitnoise", "env": _env(r, (0.001, 0.01), (0.2, 0.5), (0.0, 0.2), (0.05, 0.2)), "crush": {"bits": r.choice([4, 6, 8]), "rate": 0},
            "gain": -8, "range": ["C3", "C6"]}


@recipe("harpsichord", "colour", "orchestral bright playful", "pluck")
def _(r: Rng) -> dict[str, Any]:
    return {"osc": "pluck", "pluck": "harpsichord", "voices": 4, "range": ["C2", "C6"]}


@recipe("glockenspiel", "colour", "orchestral glassy bright fantasy", "sample", "vsco2/glockenspiel")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/glockenspiel", "voices": 4, "gain": -6}


@recipe("pizzicato", "colour", "orchestral playful acoustic", "sample", "vsco2/violins_pizz")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/violins_pizz", "voices": 4}


# drums
@recipe("kick_round", "kick", "soft warm ambient electronic", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "kick", "tune": r.range(44, 55, 0), "decay": r.range(0.3, 0.5, 2), "punch": r.range(6, 14, 0), "click": r.range(0.0, 0.15, 2)}


@recipe("kick_punch", "kick", "hard electronic retro gritty", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "kick", "tune": r.range(46, 56, 0), "decay": r.range(0.2, 0.32, 2), "punch": r.range(26, 36, 0), "click": r.range(0.3, 0.5, 2)}


@recipe("frame_drum", "kick", "world acoustic folk eerie", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "tom", "tune": r.range(60, 90, 0), "decay": r.range(0.3, 0.5, 2), "punch": 4, "noise": 0.15}


@recipe("snare_tight", "snare", "hard electronic retro", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "snare", "tune": r.range(170, 210, 0), "noise": r.range(0.55, 0.75, 2), "decay": r.range(0.12, 0.2, 2), "tone": r.range(3000, 4500, -2)}


@recipe("rim", "snare", "soft jazzy acoustic warm world", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "rim", "tune": r.range(1400, 2000, -1), "decay": r.range(0.02, 0.05, 3)}


@recipe("clap", "snare", "electronic bright playful funky", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "clap", "decay": r.range(0.15, 0.25, 2), "tone": r.range(1100, 1600, -1)}


@recipe("brush", "snare", "jazzy soft acoustic", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "brush", "decay": r.range(0.2, 0.35, 2)}


@recipe("hat_closed", "hat", "electronic hard retro bright", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "hat", "decay": r.range(0.025, 0.05, 3), "tone": r.range(7000, 10000, -2)}


@recipe("shaker", "hat", "acoustic world soft warm playful", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "shaker", "decay": r.range(0.06, 0.12, 2), "tone": r.range(5000, 8000, -2)}


@recipe("tick", "hat", "soft ambient cold electronic", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "hat", "decay": r.range(0.015, 0.03, 3), "tone": r.range(2000, 4000, -2)}


@recipe("conga", "perc", "world funky playful acoustic", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "conga", "tune": r.range(180, 260, 0)}


@recipe("cowbell", "perc", "funky playful retro", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "cowbell", "tune": r.range(520, 600, 0)}


@recipe("block", "perc", "playful acoustic world soft", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "block", "tune": r.range(900, 1500, -1)}


@recipe("metal_hit", "perc", "gritty eerie cold hard", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "metal", "tune": r.range(250, 450, 0), "decay": r.range(0.5, 1.2, 2)}


@recipe("cymbal", "crash", "hard epic orchestral bright electronic", "drum")
def _(r: Rng) -> dict[str, Any]:
    return {"drum": "cymbal", "decay": r.range(0.9, 1.6, 2)}


@recipe("timpani", "crash", "orchestral epic dark", "sample", "vsco2/timpani")
def _(r: Rng) -> dict[str, Any]:
    return {"sample": "vsco2/timpani", "voices": 2, "max_ring": 1.5}


KEYS = {"bass": "bmn", "lead": "lqr", "harmony": "pwvo", "colour": "gaeyz", "kick": "k", "snare": "sc", "hat": "ht", "perc": "ij", "crash": "x"}
ROLE_GAINS = {"bass": (-6, -2), "lead": (-11, -7), "harmony": (-15, -11), "colour": (-13, -9), "kick": (-4, -1), "snare": (-8, -5), "hat": (-16, -12),
              "perc": (-12, -8), "crash": (-15, -12)}  # fmt: skip


@dataclass
class RolledKit:
    name: str
    style: str
    seed: int
    instruments: dict[str, tuple[str, dict[str, Any]]]  # key -> (name, patch)
    identity: list[str]
    libraries: list[str] = field(default_factory=list)
    kept: dict[str, Any] = field(default_factory=dict)  # identity instruments carried over (raw mappings)

    def yaml(self) -> str:
        lines = [f"name: {self.name}", f"description: {scalar(f'Rolled from {self.style!r} (seed {self.seed}); edit freely')}",
                 "# identity = the game's signature instruments (keep them in every kit: `segan kit roll --around " + self.name + "`)", "instruments:"]  # fmt: skip
        for key, (name, data) in self.instruments.items():
            lines.append(f"  {key}: {flow({'name': name, **data})}")
        drums = [k for k, (_, d) in self.instruments.items() if "drum" in d or d.get("sample") in ("vsco2/timpani",)]
        lines += ["groups:", f"  identity: {flow(self.identity)}"]
        if drums:
            lines.append(f"  drums: {flow(drums)}")
        return "\n".join(lines) + "\n"


def roll_kit(name: str, style: str, project_seed: int, around: dict[str, Any] | None = None, samples: bool | None = None, take: int = 0) -> RolledKit:
    """A kit for `style` words: identity (2-3 signature instruments: kept from `around`'s identity group, else the
    rolled lead, harmony and colour), a bass, harmony and colour parts, 3-5 drums. `samples`: allow library
    instruments (default: when the style words call for acoustic/orchestral sounds)."""
    rng = Rng(project_seed, "kit", name, style, take)
    tags = style_tags(style)
    allow_samples = samples if samples is not None else bool(tags & {"orchestral", "acoustic"})
    instruments: dict[str, tuple[str, dict[str, Any]]] = {}
    identity: list[str] = []
    families: set[str] = set()
    names: set[str] = set()
    if around:
        raw = around.get("instruments", {})
        for key in (around.get("groups", {}) or {}).get("identity", []) or list(raw)[:3]:
            if key in raw:
                inst = dict(raw[key])
                label = str(inst.pop("name", key))
                instruments[str(key)] = (label, inst)
                identity.append(str(key))
                names.add(label)
    plan = ["lead", "harmony", "colour", "bass", "harmony" if rng.random() < 0.5 else "colour", "kick", "snare", "hat"]
    if rng.random() < 0.6:
        plan.append("perc")
    if tags & {"epic", "orchestral", "hard"} or rng.random() < 0.3:
        plan.append("crash")
    for role in plan:
        if around and role in ("lead", "harmony", "colour") and any(_role_of(instruments[k][1]) == role for k in identity):
            continue  # the identity already covers it
        pool = [rc for rc in R if rc.role == role and (allow_samples or not rc.library) and rc.name not in names]
        if not pool:
            continue
        drum = role in ("kick", "snare", "hat", "perc", "crash")
        scored = [(rc, max(0.2, 1.0 + (1.0 if drum else 2.0) * len(tags & set(rc.tags)) - (1.5 if rc.family in families and not drum else 0.0))) for rc in pool]
        pick: Recipe = rng.weighted([(rc, score**2) for rc, score in scored])
        data = pick.build(rng)
        lo, hi = ROLE_GAINS[role]
        data["gain"] = data.get("gain", rng.range(lo, hi, 0))
        key = next((k for k in KEYS[role] if k not in instruments), next(k for k in "abcdefghijklmnopqrstuvwxyz" if k not in instruments))
        instruments[key] = (pick.name, data)
        names.add(pick.name)
        families.add(pick.family)
        if not around and role in ("lead", "harmony", "colour") and len(identity) < 3:
            identity.append(key)
    libraries = sorted({d["sample"] for _, d in instruments.values() if isinstance(d.get("sample"), str) and "/" in d["sample"]})
    return RolledKit(name, style, project_seed, instruments, identity, libraries)


def _role_of(data: dict[str, Any]) -> str:
    rng = data.get("range")
    if "drum" in data:
        return "drum"
    if isinstance(rng, list) and rng and isinstance(rng[0], str) and rng[0][-1:] in "12" and rng[0][:1] in "ABCDEFG":
        return "bass"
    if data.get("voices", 1) >= 4 and data.get("osc") not in ("pluck", "modal"):
        return "harmony"
    return "colour" if data.get("osc") in ("pluck", "modal") else "lead"


# --- song suggestions ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Mood:
    words: tuple[str, ...]
    tempo: tuple[int, int]
    modes: tuple[tuple[str, float], ...]  # mode, weight


MOODS: dict[str, Mood] = {
    "calm": Mood(("calm", "quiet", "soft", "sleepy", "lullaby", "peaceful", "ambient", "relaxed", "gentle", "night", "sad", "melancholy", "lonely"),
                 (58, 92), (("major", 1), ("lydian", 1.2), ("dorian", 1), ("minor", 1), ("pentatonic_major", 0.6), ("mixolydian", 0.5))),
    "tense": Mood(("tense", "combat", "battle", "fight", "boss", "chase", "action", "danger", "urgent", "angry", "fast"),
                  (128, 176), (("minor", 1), ("phrygian", 1.2), ("harmonic_minor", 1.2), ("dorian", 0.8), ("locrian", 0.3), ("blues", 0.4))),
    "bright": Mood(("happy", "bright", "menu", "shop", "town", "cheerful", "playful", "upbeat", "victory", "fun", "cozy", "cosy", "warm"),
                   (92, 128), (("major", 1), ("mixolydian", 1), ("lydian", 0.7), ("pentatonic_major", 0.8), ("dorian", 0.5))),
    "dark": Mood(("dark", "dungeon", "cave", "eerie", "horror", "creepy", "mystery", "mysterious", "ominous", "cold", "alien"),
                 (64, 110), (("phrygian", 1), ("harmonic_minor", 1), ("locrian", 0.5), ("minor", 0.8), ("whole_tone", 0.4), ("dorian", 0.5))),
    "adventure": Mood(("adventure", "explore", "exploration", "overworld", "journey", "travel", "field", "heroic", "epic", "open"),
                      (96, 138), (("dorian", 1.2), ("mixolydian", 1), ("major", 0.8), ("minor", 0.8), ("lydian", 0.6))),
}  # fmt: skip
ANY_MOOD = Mood((), (64, 160), (("major", 1), ("minor", 1), ("dorian", 1), ("mixolydian", 0.7), ("lydian", 0.6), ("phrygian", 0.5), ("harmonic_minor", 0.5)))
METERS = (((4, 4), 1.0), ((3, 4), 0.35), ((6, 8), 0.3), ((5, 4), 0.1), ((7, 8), 0.08), ((2, 4), 0.1))
TEXTURES = (
    ("pad chords", "sustained chords, one per bar or two"),
    ("ostinato", "a one-bar figure repeated under everything (strings, pluck or synth)"),
    ("arpeggio", "broken chords in eighths or sixteenths"),
    ("pulse", "one repeated chord tone in eighths, the harmony moving underneath"),
    ("drone and melody", "a held root or fifth with a melody over it"),
    ("drums first", "two bars of drums or percussion alone, then the harmony"),
    ("solo line", "the melody alone for two bars, then the rest joins"),
    ("chorale", "block chords in four voices moving stepwise"),
    ("bass riff", "a bass line alone, then chords on top"),
    ("call and response", "two instruments trading one-bar phrases"),
)
PROGRESSIONS: dict[str, tuple[str, ...]] = {
    "major": ("I V vi IV", "I IV ii V", "vi IV I V", "I iii IV V", "IV I V vi", "I vi ii V", "ii V I vi", "I IV vi V"),
    "minor": ("i VI III VII", "i iv VII III", "i VII VI VII", "i v VI iv", "iv i v i", "i III VII iv", "VI VII i i", "i iv v i"),
    "dorian": ("i IV i IV", "i ii IV i", "i VII IV i", "i IV VII i"),
    "phrygian": ("i II i VII", "i II VII i", "i iv II i"),
    "lydian": ("I II I II", "I II vii I", "I II iii II"),
    "mixolydian": ("I VII IV I", "I v IV I", "I VII v IV"),
    "harmonic_minor": ("i iv V i", "i VI V i", "i iv VI V"),
    "locrian": ("i II i II", "i v II i"),
}
ROOTS = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


def mood_of(words: str) -> str | None:
    tokens = set(re.findall(r"[a-z]+", words.lower()))
    scores = {m: len(tokens & set(spec.words)) for m, spec in MOODS.items()}
    best = max(scores, key=lambda m: scores[m])
    return best if scores[best] else None


def suggest_song(name: str, words: str, project_seed: int, existing: list[Any], kits: dict[str, dict[str, Any]], take: int = 0) -> dict[str, Any]:
    """A plan for a new song away from `existing` (fingerprints): key and mode, tempo, meter, texture, opening
    voicing, progression and instruments (the identity plus extras)."""
    from segan.api import chord as diatonic_chord

    rng = Rng(project_seed, "song", name, words, take)
    mood = mood_of(words)
    spec = MOODS[mood] if mood else ANY_MOOD
    used_sets = [tuple(f.pitch_set) for f in existing]
    used_roots = [k.root for f in existing if (k := parse_key(f.key)) is not None]
    used_tempos = [f.tempo for f in existing]
    used_meters = [tuple(f.meter) for f in existing]
    used_openings = {tuple(f.opening) for f in existing}
    why: list[str] = []
    # key: a mode for the mood, a root whose pitch set the project uses least
    options: list[tuple[Key, float]] = []
    for mode, weight in spec.modes:
        for root in range(12):
            candidate = parse_key(f"{ROOTS[root]} {mode}")
            assert candidate is not None
            pcs = tuple(sorted({(root + i) % 12 for i in candidate.intervals}))
            crowd = used_sets.count(pcs) + 0.5 * used_roots.count(root)
            options.append((candidate, weight / (1.0 + 2.0 * crowd) ** 2))
    key: Key = rng.weighted(options)
    if used_sets:
        why.append(f"{key.describe()}: {sum(1 for s in used_sets if s == tuple(sorted({(key.root + i) % 12 for i in key.intervals})))} of {len(used_sets)} songs share its notes")
    # tempo: inside the mood's range, as far as the dice allow from the tempos in use
    lo, hi = spec.tempo
    candidates = [lo + (hi - lo) * rng.random() for _ in range(12)]
    tempo = round(max(candidates[:6], key=lambda t: min((abs(t - u) for u in used_tempos), default=0.0) + 4 * rng.random()) if used_tempos else candidates[0])
    if used_tempos:
        why.append(f"{tempo} bpm: the nearest song is {min(abs(tempo - u) for u in used_tempos):.0f} bpm away")
    meter = rng.weighted([(m, w / (1.0 + used_meters.count(m) / max(1, len(used_meters)) * 2)) for m, w in METERS])
    texture, texture_hint = rng.choice(TEXTURES)
    family = key.scale if key.scale in PROGRESSIONS else ("major" if key.scale in ("pentatonic_major", "whole_tone") else "minor")
    progression = rng.choice(PROGRESSIONS[family]).split()
    turn = int(rng.random() * len(progression)) if rng.random() < 0.4 else 0  # sometimes start elsewhere in the cycle
    progression = progression[turn:] + progression[:turn]
    # opening voicing: the first chord, inverted/spread/coloured and placed in a register; never one already used
    opening: list[int] = []
    shape = {}
    for attempt in range(24):
        degree = _degree(progression[0])
        size = rng.choice([3, 3, 4]) if len(key.intervals) == 7 else 3
        register = rng.choice(["low", "middle", "middle", "high"])
        octave = {"low": 2, "middle": 3, "high": 4}[register]
        notes = diatonic_chord(degree, key, octave, size) if len(key.intervals) == 7 else [12 * (octave + 1) + key.root + key.intervals[i % len(key.intervals)] for i in (0, 2, 4)]
        inversion = rng.choice([0, 0, 1, 2])
        for _ in range(inversion):
            notes = notes[1:] + [notes[0] + 12]
        spread = rng.choice(["close", "close", "open", "wide"])
        if spread == "open" and len(notes) >= 3:
            notes = sorted([notes[0], notes[2], notes[1] + 12, *notes[3:]])
        elif spread == "wide":
            notes = sorted([notes[0] - 12, *notes[1:], notes[-1] + 12])
        bass = notes[0] - 12 if rng.random() < 0.7 else None
        opening = sorted(([bass] if bass is not None else []) + notes)
        shape = {"degree": progression[0], "inversion": ("root position", "1st inversion", "2nd inversion")[inversion], "spread": spread, "register": register,
                 "size": size, "bass": bass is not None}  # fmt: skip
        if tuple(opening) not in used_openings:
            break
    instruments = _instrument_plan(kits, rng)
    return {
        "name": name,
        "mood": mood,
        "key": key.describe(),
        "tempo": tempo,
        "meter": list(meter),
        "steps_per_beat": 2 if meter[1] == 8 else 4,
        "texture": texture,
        "texture_hint": texture_hint,
        "progression": " ".join(progression),
        "opening": {"notes": [key.name(m) for m in opening], **shape},
        "instruments": instruments,
        "seed": int(rng.random() * 1_000_000),
        "why": why,
        "command": f'segan new song {name} --key "{key.describe()}" --tempo {tempo}' + (f" --kit {instruments['kit']}" if instruments.get("kit") else "")
                   + (f" --meter {meter[0]}/{meter[1]}" if meter != (4, 4) else ""),
    }  # fmt: skip


def _degree(numeral: str) -> int:
    from segan.api import ROMAN

    return ROMAN.get(numeral.lower().rstrip("°+7"), 1)


def _instrument_plan(kits: dict[str, dict[str, Any]], rng: Rng) -> dict[str, Any]:
    """The kit's identity instruments plus 1-2 extras from its other instruments (or a recipe to add)."""
    if not kits:
        return {}
    name = rng.choice(sorted(kits))
    raw = kits[name].get("instruments", {}) or {}
    groups = kits[name].get("groups", {}) or {}
    identity = [k for k in groups.get("identity", []) if k in raw]
    rest = [k for k, v in raw.items() if k not in identity and isinstance(v, dict) and "drum" not in v]
    extras = []
    for _ in range(min(2, len(rest))):
        pick = rng.choice(rest)
        rest.remove(pick)
        extras.append(pick)
    label = {k: (raw[k].get("name", k) if isinstance(raw[k], dict) else k) for k in raw}
    plan: dict[str, Any] = {"kit": name, "identity": [f"{k} {label[k]}" for k in identity], "extras": [f"{k} {label[k]}" for k in extras]}
    if not extras or rng.random() < 0.5:  # a new colour from the wider palette
        fresh = rng.choice([rc for rc in R if rc.role in ("colour", "lead", "harmony") and not rc.library])
        plan["new_instrument"] = {"name": fresh.name, "patch": fresh.build(rng)}
    return plan


def tempo_label(tempo: float) -> str:
    return "slow" if tempo < 80 else "medium" if tempo < 120 else "fast"


__all__ = ["R", "Recipe", "Rng", "RolledKit", "math", "note_name", "roll_kit", "style_tags", "suggest_song"]
