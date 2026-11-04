# Recorded

Recorded SFX: Freesound search, licences, sounds.lock, recorded layers.

## Recorded SFX

Real-world sounds start from recordings that are processed and layered, the way film sound is made (a film lion
is often a tiger pitched down, stretched and layered with a sub growl). Synth recipes can't get there.

1. **Find candidates** (needs `FREESOUND_API_KEY`): `segan sounds search "lion roar" --max-seconds 4 --json`.
   Only CC0 and CC BY sounds come back (never non-commercial). Pick 3-5 by name, tags, duration and rating, then
   `segan sounds inspect freesound:<id> ...` compares them without hearing: length, loudness, peak, brightness
   (`centroid_hz`), pitch, onsets (one clean hit or a clatter of several?). Prefer clean, close, dry recordings:
   a room can be added, never removed.
   **No key?** Search freesound.org on the web, then `segan sounds add https://freesound.org/people/<user>/sounds/<id>/`
   (or `freesound:<id>`): without a key SEGAN reads the licence, author and HQ preview from the public page and applies
   the same CC0 / CC BY rule. From another site with a clear CC0 / CC BY licence: check the licence on its page,
   download it into the project (`sounds/`) and `segan sounds add <file> --licence ... --source <page> --author ...`.
   Never use a sound whose licence you couldn't check.
2. **Keep it**: `segan sounds add freesound:<id>`: checks the licence, fetches the preview into the user cache
   (not the repo) and records it in `sounds.lock` (commit sounds.lock; builds fetch and check the file).
3. **Write the layer**: `sample: freesound:<id>` (or a file path, or a list: one per variation), then shape it:
   `trim: [start, end]` (seconds of the file), `shift: -7` (semitones, length stays), `stretch: 1.5` (x length,
   pitch stays), `reverse`, `fade: [in, out]`, plus the usual `gain`, `filter`, `cutoff` keyframes, `distort`,
   `start`, `length`. Bigger and heavier = shift down a few semitones and stretch a little; distant = low-pass
   (`filter: { type: lp, cutoff: 2500 }`), quieter transient, more room. Add synth layers for weight (a `sine`
   sub or `drum: kick` thump) or sparkle. Variations: a list of 2-4 similar recordings beats pitch jitter.
4. `segan lint` (E019 a missing/changed file, E020 a licence problem), `segan preview` and check the sheet as
   for any SFX (W011 if the recording runs past `duration`: `trim` it or `fade` it out).
5. **Credits**: CC BY requires attribution. `segan sounds credits` writes `SOUND_CREDITS.md`; tell the game
   agent/owner to ship it with the game's credits. `segan sounds vendor` copies the sounds in use into the
   project, only when asked (offline builds).

**What a game agent should put in a sound request** (tell your orchestrator, or ask): what it is and what
makes it ("a lion roar"), realistic or stylised, length ("~2 s"), distance and context ("distant, in a canyon";
"close, UI feedback"), how often it plays (frequent sounds get variations), and the game's style reference.


## Recorded layers (realistic SFX)

```yaml
name: lion_roar
description: "Big cat roar, distant, ~2 s: a CC BY recording pitched down and stretched, with a sub growl."
duration: 2.2
layers:
  - id: roar
    sample: freesound:123456       # in sounds.lock (`segan sounds add freesound:123456`); or a file: sounds/roar.wav
    trim: [0.12, 2.0]              # seconds of the file: [start, end] (or just the start)
    shift: -4                      # semitones, the length stays (-24..24)
    stretch: 1.15                  # x the length, the pitch stays (0.25-4)
    fade: [0, 0.4]                 # seconds: [in, out]
    filter: { type: lp, cutoff: 3000 }
  - { id: sub, osc: sine, pitch: [[0, A1], [1.6, E1]], slide: true, env: [0.05, 0.6, 0.4, 0.5], gain: -8 }
variations: { count: 3, seed: 1, gain: 1 }
```

`sample:` in an SFX layer makes it a **recorded layer** when it is a sound file path (`.wav`, `.ogg`, `.flac`,
`.mp3`; relative to the project; ogg/flac/mp3 need `pip install "segan[ogg]"`), `freesound:<id>`, or a list of
them (one is picked per variation, from the seed; the same every render). A recorded layer plays its file as
recorded: one-shot, mixed to mono, peak-normalised (so `gain` is the balance against the other layers, whatever
level it was recorded at). Its own fields: `trim`, `reverse: true`, `fade: [in, out]`, `shift` (semitones) and
`stretch` (x length): pitch and length change **independently** (phase vocoder with phase locking; transients
soften a little at big stretches). Applied in that order: trim, reverse, stretch/shift, fades. Every other layer
field works too: `pitch` keyframes are varispeed (C4 = as recorded: `pitch: [[0, C4], [1, G3]]` slows down like
tape), `gain`/`cutoff` keyframes, `filter`, `env` (default: plays as recorded), `length` (chokes it, then
`env`'s release), `distort`, `ring`, `delay`, `start`. `osc`/`drum`/`instrument` can't be on a recorded layer:
synth sounds go on their own layers (they mix freely). The mapping form `sample: { wav: x.wav, root: A4 }` stays
a pitched sampled instrument.

**Licences** (E020): only CC0 and CC BY (any version), never non-commercial, share-alike or unknown. A Freesound
sound's licence, author and page come from `sounds.lock`; a local file needs `licence:` (`CC0`, `CC-BY-4.0`, or the
creativecommons.org URL), `source:` (the page it came from, or "own recording") and, for CC BY, `author:` on
the layer, or a sounds.lock entry (`segan sounds add sounds/x.wav --licence CC-BY-4.0 --source URL --author NAME`).
A project that has cleared another licence itself (a royalty-free library under its own terms, e.g. the GDC bundles)
names it in segan.toml: `[sounds] extra_licences = ["Sonniss-GDC"]`; its sounds then need `licence: Sonniss-GDC` and a
`source`, and `segan sounds credits` lists them under "Other licences". Only the owner clears a licence: don't add
one on your own.

**sounds.lock** (next to segan.toml; commit it): one `[sounds."<ref>"]` table per sound with `name`, `author`,
`licence`, `licence_url`, `url` (the Freesound page) or `source`, `file` (`preview-hq-ogg`, `local`), `download`,
`sha256`. Freesound files live in the user cache (`$SEGAN_SOUNDS`, else `~/.cache/segan/sounds`), fetched on first
use and checked against the sha256 (a mismatch is E019); `segan sounds vendor` copies them into
`<project>/sounds/freesound/`, which builds use first. SEGAN fetches Freesound's HQ Ogg preview (~192 kbit/s;
the API key alone allows it); originals need an OAuth2 login and aren't supported.
