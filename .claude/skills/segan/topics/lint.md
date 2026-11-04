# Lint

Lint rules E001-E0xx and W0xx: what each means and how to fix it.

## Lint rules

Errors (the build stops): E000 command/usage, E001 YAML/field problem, E002 unknown character in a lane,
E003 row width or row count wrong, E004 missing pattern/section/marker target, E005 kit problem, E006 variant
problem (unknown key/group, group sizes differ, a key with no instrument), E007 note outside an instrument's
range (also in variants), E008 bad loop/phase/crossfade, E009 inline instruments in strict mode, E010 derived
pattern problem, E011 row label doesn't match its row, E012 duplicate asset name, E013 SFX problem, E014 more
notes at once than an instrument's voices, E015 hold with nothing to hold, E016 `stems:` problem (a track in no
group or two, unknown stem in a mix), E017 `flow:` problem (unknown or unreachable section, dead end, bad weight,
a section that isn't whole bars), E018 soundtrack problem (unknown state, song, variant, stinger SFX or start
section; a bad field), E019 recorded sound can't be used (file missing or undecodable, not in sounds.lock, sha256
mismatch, fetch failed), E020 recorded sound's licence (missing, not CC0/CC BY, no source, CC BY without an author).

Warnings: W001 loudness target out of reach without more limiting than `max_limiting_db` (too short/spiky:
stagger layer starts 3-9 ms, tame the peakiest layer (`preview --json` `layers`), give it body, or a quieter category; for a percussive song: `category: music_soft` + `music_soft = -19` under
`[loudness]`), W002 unused pattern or section, W003 too many instruments in one song (with `stems.mixes`: in one mix),
W004 silent pattern or sound, W005 lead-in silence in an SFX, W006 made under an older style version, W007
click at a loop point, W008 DC offset, W009 tracks clash (minor 2nd/tritone) on a beat (the felt beat: every 3 units in 6/8, 9/8, 12/8; a held note counts while above -30 dB), W010 aliasing (raise
`[mix] oversample` or play lower), W011 SFX still sounding at `duration`, W012 note cut at the end of its
pattern, W013 loudness off target with `normalize: false`, W014 a note held longer than its sample (no loop):
it goes silent before it ends, W015 a flow section shorter than the ring-out of a section before it, W016 a
soundtrack cross-fade between songs in clashing keys, W017 a stem mix that can't reach its target even with its
trim, W018 an SFX noise layer whose filter removes more than 12 dB of its level and that ends up more than 12 dB under the
loudest layer (a narrow band-pass, a low cutoff; a filtered bed on its own never warns): raise its gain,
W019 a looping song's file runs more than 2 bars past the song because its last notes ring that long: give those
instruments `max_ring`, W020 a recorded layer in a project with `[sfx] source = "synth"`, W028 a `sounds.lock` entry no SFX plays (`segan sounds prune`), W027 a transient inside a
looping SFX's (or phase's) first `crossfade` seconds: the seam blend fades it (start it later or shorten the crossfade).
Sameness (songs are compared with every other song of the project; `segan similarity` shows the numbers): W021 two
songs open on the same notes (step 1, two or more notes), W022 more than half of the songs share one pitch set (D minor
= F major) or sit within 10 bpm, W023 every song plays one kit with nearly the same instruments, W024 two songs' first 8
bars score over `lint.max_similarity` (harmony, rhythm, instruments), W025 a song close to SEGAN's own examples (the
demo, the generator example in `segan docs api`), W026 a song close to one from another project on this machine (`[similarity]
local_store`). W022/W023 are reported on segan.toml.
Turn warnings off for one asset with `lint: { disable: [...] }`, for every asset of a category with
`[lint.<category>] disable = ["W017"]` (e.g. `[lint.battle_music]`), project-wide with `[lint] disable`.
