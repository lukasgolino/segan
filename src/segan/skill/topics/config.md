# Config

segan.toml settings and fields common to songs and SFX.

## Common fields (songs and SFX)

`description` (always), `tags: [...]`, `status: draft|approved` (approved only after a human listened),
`style_version` (set by `segan mark --current`), `template: true` (never built; for `extends`),
`lint: { disable: [W009] }` (warnings that are wrong by design for this asset).


## `segan.toml`

```toml
mode = "strict"               # strict: kits only; open: inline instruments allowed
default_kit = "nes"
output_dir = "build/audio"    # e.g. ../game/assets/generated/audio (apart from PAGAN's output: both write manifest.json)
preview_dir = "previews"
export = ["wav"]              # + "godot" (.import loops/compression, randomizer/synchronized .tres), "stems",
                              #   "ogg" (music as Ogg Vorbis, ~10x smaller; SFX stay WAV; pip install "segan[ogg]"),
                              #   "web" (segan_audio.js, a Web Audio player; not with "godot")
style_version = 1
seed = 4417312093             # the project seed (`segan init` picks one): suggestions and rolled kits branch from it; renders don't use it

[mix]                         # shared by every asset; any change re-renders everything
sample_rate = 44100           # 22050 | 32000 | 44100 | 48000
oversample = 2                # 1 | 2 | 4 | 8: synthesis rate multiplier (anti-aliasing; 4 for very high leads)
music_channels = "stereo"
sfx_channels = "mono"
tuning = 440.0
room = 0.15                   # shared reverb amount
room_decay = 0.6              # seconds to fall 60 dB
crush_bits = 0                # 0 off; e.g. 8
crush_rate = 0                # Hz, 0 off
declick = true                # micro-fades at note edges
limiter = -1.0                # true-peak ceiling, dBFS
brightness = 0.0              # dB tilt
warmth = 0.0                  # dB low-mid
tail_trim_db = -70.0          # room tail cut this far below the peak (-40 = shorter files)

[room]                        # room send per category, 0-1 x mix.room (unlisted: 1); e.g. ui = 0 (dry, no tail)

[bus.pickup]                  # mix bus per category (optional; unlisted categories play on Master)
bus = "SFX"                   #   engine bus name: a letter, then letters, digits or '_'
volume_db = -3                #   the category's default playback volume, -60..12 dB (the bus stays at 0 dB)
                              # same TOML: [bus] pickup = { bus = "SFX", volume_db = -3 }; `segan config set bus.pickup.volume_db -3`

[loudness]                    # LUFS per category, -60..-5 (songs: integrated; SFX: loudest 400 ms; unlisted categories, songs too, use sfx)
music = -16.0
sfx = -14.0
ui = -20.0
foley = -22.0                 # add any category: boss = -12
# short_sfx = "duration"      # opt-in: one-shots shorter than 400 ms are measured over their own length, not 400 ms
                              # zero-padded (default "window": a 60 ms click comes out about 8 dB hotter than it sounds)

[godot]
compress = "qoa"              # qoa | ima | none

[sfx]
source = "auto"               # auto: synthesise stylised sounds, record real-world ones (the skill's rule);
                              # synth: no recordings (W020); recorded: prefer recordings
                              # `init --style chiptune|synth` (and plain `init`) write "synth"

[ogg]
quality = 0.4                 # Vorbis quality 0-1 (0.4 is about 128 kbit/s stereo)

[lint]
disable = []
max_seam_click = 0.02         # W007
max_leading_silence_ms = 5    # W005
max_instruments = 8           # W003
max_aliasing_db = -50.0       # W010
max_limiting_db = 3.0         # W001: the most the limiter may take off before the target counts as out of reach
max_dc_offset = 0.01          # W008
loudness_tolerance = 1.0      # W001/W013, LU
max_similarity = 0.85         # W024-W026: how alike (0-1) two songs' first 8 bars may be

[similarity]
local_store = false           # true: keep song fingerprints in ~/.cache/segan/fingerprints (on build and `segan similarity`)
                              #   and compare with your other projects on this machine (W026)
shipped = true                # compare with SEGAN's own examples (W025)
```
