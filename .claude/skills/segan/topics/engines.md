# Engines

Other engines (Unity, Unreal, web, ...).

## Other engines

The audio files are plain 16-bit PCM WAV (and Ogg Vorbis for music with export "ogg"): every engine imports them.
What differs per engine is the import settings (loop points, compression, streaming), how variations, buses and
playback hints are expressed, and the runtime helper. `manifest.json` carries all of it engine-neutrally; for an
engine other than Godot, build with `output_dir` outside any Godot project (manifest paths are then relative to
`output_dir`) and read the manifest in the game. Two rules hold everywhere:

- **Loop points come from the manifest**, not the WAV: only Godot gets them written into its import settings. A
  song's loop starts after its intro (`loop.start` > 0), so an engine that loops a whole clip (below) needs the
  song played as intro, then the loop region, sample-exactly; one-shot SFX don't loop, and looping SFX loop from
  frame 1 to the end (frame 0 is a lead-in copy of the last frame: start playback at frame 1 or ignore it).
- **One SFX = a pool of files**: `variations` (and `takes`); play a random one, not the same twice in a row. The
  main `file` is in the pool only when there are no variations (`sfx/<name>.tres` in Godot does the same).

| | import | loops | variations | buses / volume | playback hints |
|---|---|---|---|---|---|
| Web | `fetch` + `decodeAudioData` (`segan_audio.js`) | `loopStart`/`loopEnd` from the manifest (handled) | handled | a GainNode per bus | handled |
| Unity | AudioClip; Load Type: Decompress On Load (SFX), Streaming (music); Force To Mono off (SEGAN sets channels) | `AudioSource.loop` loops the whole clip: schedule intro + loop (`PlayScheduled`, `timeSamples`) | a script, or an Audio Random Container (Unity 6) | AudioMixer groups by `bus`; `volume_db` on the source | a script (max instances, min gap, repeat attenuation) |
| Unreal | SoundWave (import WAV) | the SoundWave's Looping flag loops the whole wave: intro + loop needs a MetaSound or two waves | Sound Cue Random node or a MetaSound | Sound Class / Submix by `bus` | a Sound Concurrency (max count, stop oldest, volume scale) |
| Defold | sound component (`.sound`: `sound`, `looping`, `group`, `gain`); WAV or Ogg | `looping` repeats the whole file: no loop points | pick a component per variation in a script | `group` = `bus`, `sound.set_group_gain` | a script |

Only Godot and the web have a SEGAN helper; for the others, what verifying them needs is tracked in https://github.com/lukasgolino/segan/issues/34.

**Web** (`export = ["wav", "web"]`): `segan build` writes `segan_audio.js` (an ES module, no dependencies) next to
`manifest.json`. It plays SFX by name (random variation, never twice in a row; category bus and `volume_db`;
`playback` hints) and songs looping at their manifest loop points, with the Web Audio API:

```js
import { SeganAudio } from "./audio/segan_audio.js";
const audio = await SeganAudio.open("./audio/manifest.json");   // create it after a user gesture
await audio.load();                    // decode every SFX
audio.play("coin");                    // returns { source, gain } or null (dropped by min_gap_s)
await audio.playSong("overworld");     // or playSong("overworld", { variant: "danger" })
audio.stop("overworld");
audio.bus("SFX").gain.value = 0.5;
```

Flow songs, soundtracks and stems aren't played by it (the manifest has their timing). Browsers differ in which
compressed formats they decode: WAV works everywhere; check Ogg Vorbis on the browsers you target. "web" can't be
combined with "godot" (Godot writes `res://` paths into the manifest).
