// SEGAN web audio helper: plays SEGAN sounds by name from manifest.json with the Web Audio API, the way the
// Godot helpers do: a random variation each play (never the same twice in a row), the category's bus and default
// volume ([bus] in segan.toml), each SFX's playback hints (max_instances, min_gap_s, repeat_attenuation_db), and
// songs looping at their manifest loop points.
// Written by `segan build` next to manifest.json when `export` has "web"; don't edit it (every build overwrites it).
//
//   import { SeganAudio } from "./audio/segan_audio.js";
//   const audio = await SeganAudio.open("./audio/manifest.json");   // after a user gesture (browsers start audio then)
//   await audio.load();                     // decode every SFX (or audio.load(["coin", "hit"]))
//   audio.play("coin");                     // a random variation, on its category's bus at its volume
//   const hum = audio.play("engine", { volumeDb: -6 });   // a looping SFX plays until stopped
//   audio.stop("engine");
//   await audio.playSong("overworld");      // loops by itself; playSong(name, { variant: "danger" })
//   audio.bus("SFX").gain.value = 0.5;      // every bus is a GainNode into the destination
//
// play() returns { source, gain } or null when a hint dropped the play (min_gap_s), the name is unknown or its
// audio isn't loaded yet. Flow songs, soundtracks and stems aren't played by this helper (see the manifest).

export const SEGAN_AUDIO_VERSION = 1;

export function dbToGain(db) {
  return Math.pow(10, db / 20);
}

/** The file entries an SFX picks from on each play: the same list as the Godot AudioStreamRandomizer (its
 * variations, every take's variations or the take itself), or its own file. */
export function sfxChoices(entry) {
  const choices = [...(entry.variations || [])];
  if (entry.takes) {
    if (!choices.length && entry.file) choices.push(entry);
    for (const take of entry.takes) {
      if (take.variations && take.variations.length) choices.push(...take.variations);
      else if (take.file) choices.push(take);
    }
  }
  if (!choices.length && entry.file) choices.push(entry);
  return choices;
}

/** Loop points of a manifest file entry in seconds ({ start, end }, end exclusive), or null. */
export function loopSeconds(fileEntry, sampleRate) {
  const loop = fileEntry && fileEntry.loop;
  return loop ? { start: loop.start / sampleRate, end: loop.end / sampleRate } : null;
}

export class SeganAudio {
  /**
   * @param manifest the parsed manifest.json
   * @param options  context: an AudioContext (default: a new one); baseUrl: where the manifest's relative file
   *                 paths start (default ""); fetch: a fetch function; random: () => [0, 1) (default Math.random)
   */
  constructor(manifest, options = {}) {
    this.manifest = manifest;
    this.context = options.context || new AudioContext();
    this.baseUrl = options.baseUrl === undefined ? "" : options.baseUrl;
    this.fetch = options.fetch || globalThis.fetch.bind(globalThis);
    this.random = options.random || Math.random;
    this.buffers = new Map(); // file -> AudioBuffer
    this.buses = new Map(); // bus name -> GainNode
    this.playing = new Map(); // SFX name -> [{ source, gain }] still sounding, oldest first
    this.lastStart = new Map(); // SFX name -> context time of its last start
    this.lastPick = new Map(); // SFX name -> index of the file it played last
  }

  /** Fetch manifest.json and make a player whose file paths start next to it. */
  static async open(manifestUrl, options = {}) {
    const fetchFn = options.fetch || globalThis.fetch.bind(globalThis);
    const response = await fetchFn(manifestUrl);
    if (!response.ok) throw new Error(`SeganAudio: can't read ${manifestUrl} (${response.status})`);
    const base = manifestUrl.slice(0, manifestUrl.lastIndexOf("/") + 1);
    return new SeganAudio(await response.json(), { baseUrl: base, ...options, fetch: fetchFn });
  }

  /** The asset's manifest entry, or null. kind: "sfx", "song" or undefined (either). */
  entry(name, kind) {
    const found = (this.manifest.assets || {})[name];
    return found && (kind === undefined || found.kind === kind) ? found : null;
  }

  url(file) {
    if (file.startsWith("res://")) throw new Error(`SeganAudio: ${file} is a Godot path (build without "godot" in export for the web)`);
    return this.baseUrl + file;
  }

  /** Decode the files of these assets (default: every SFX). Already decoded files are kept. */
  async load(names) {
    const assets = this.manifest.assets || {};
    const wanted = names || Object.keys(assets).filter((n) => assets[n].kind === "sfx");
    const files = [];
    for (const name of wanted) {
      const entry = assets[name];
      if (!entry) throw new Error(`SeganAudio: no asset named ${name} in the manifest`);
      const choices = entry.kind === "sfx" ? sfxChoices(entry) : [entry, ...Object.values(entry.variants || {})];
      files.push(...choices.map((c) => c.file));
    }
    await Promise.all(files.filter((f) => f && !this.buffers.has(f)).map((f) => this.loadFile(f)));
  }

  async loadFile(file) {
    const response = await this.fetch(this.url(file));
    if (!response.ok) throw new Error(`SeganAudio: can't fetch ${file} (${response.status})`);
    const buffer = await this.context.decodeAudioData(await response.arrayBuffer());
    this.buffers.set(file, buffer);
    return buffer;
  }

  /** The GainNode of a bus (created at unity gain on first use, into the context's destination). */
  bus(name) {
    if (!this.buses.has(name)) {
      const gain = this.context.createGain();
      gain.gain.value = 1;
      gain.connect(this.context.destination);
      this.buses.set(name, gain);
    }
    return this.buses.get(name);
  }

  /** The bus the asset's category plays on ("Master" when [bus] doesn't list it). */
  busFor(name) {
    const entry = this.entry(name);
    return (entry && entry.bus) || "Master";
  }

  /** The category's default volume, less repeat_attenuation_db per copy of the SFX still sounding. */
  volumeDbFor(name) {
    const entry = this.entry(name) || {};
    const category = (this.manifest.buses || {})[entry.category] || {};
    const hints = entry.playback || {};
    return (category.volume_db || 0) - (hints.repeat_attenuation_db || 0) * this.sounding(name).length;
  }

  /** Copies of the SFX still sounding, oldest first. */
  sounding(name) {
    return this.playing.get(name) || [];
  }

  /** The file to play: random, never the one played last (when there are several). */
  pick(name, count) {
    if (count === 1) return 0;
    const last = this.lastPick.get(name);
    let index = Math.floor(this.random() * (last === undefined ? count : count - 1));
    if (last !== undefined && index >= last) index += 1;
    this.lastPick.set(name, index);
    return index;
  }

  /** Play an SFX. options: volumeDb (extra dB), playbackRate (1 = as built), when (context time, default now). */
  play(name, options = {}) {
    const entry = this.entry(name, "sfx");
    if (!entry) {
      console.error(`SeganAudio: no SFX named ${name} in the manifest`);
      return null;
    }
    const choices = sfxChoices(entry);
    const now = this.context.currentTime;
    const hints = entry.playback || {};
    if (hints.min_gap_s !== undefined && this.lastStart.has(name) && now - this.lastStart.get(name) < hints.min_gap_s) return null;
    const choice = choices[this.pick(name, choices.length)];
    const buffer = this.buffers.get(choice.file);
    if (!buffer) {
      console.error(`SeganAudio: ${choice.file} isn't loaded (await load() first)`);
      return null;
    }
    if (hints.max_instances !== undefined) {
      while (this.sounding(name).length >= Math.max(1, hints.max_instances)) this.end(name, this.sounding(name)[0]);
    }
    const voice = this.start(buffer, loopSeconds(choice, entry.sample_rate), this.busFor(name), this.volumeDbFor(name) + (options.volumeDb || 0), options);
    this.playing.set(name, [...this.sounding(name), voice]);
    voice.source.onended = () => this.forget(name, voice);
    this.lastStart.set(name, now);
    return voice;
  }

  /** Stop every copy of the SFX (or song). */
  stop(name) {
    for (const voice of [...this.sounding(name)]) this.end(name, voice);
    this.playing.delete(name);
  }

  /** Play a song (or one of its variants), looping at its manifest loop points when it has them. */
  async playSong(name, options = {}) {
    const entry = this.entry(name, "song");
    if (!entry) throw new Error(`SeganAudio: no song named ${name} in the manifest`);
    const fileEntry = options.variant ? (entry.variants || {})[options.variant] : entry;
    if (!fileEntry || !fileEntry.file) throw new Error(`SeganAudio: ${name} has no file${options.variant ? ` for variant ${options.variant}` : ""}`);
    const buffer = this.buffers.get(fileEntry.file) || (await this.loadFile(fileEntry.file));
    const voice = this.start(buffer, loopSeconds(fileEntry, entry.sample_rate), this.busFor(name), this.volumeDbFor(name) + (options.volumeDb || 0), options);
    this.playing.set(name, [...this.sounding(name), voice]);
    voice.source.onended = () => this.forget(name, voice);
    return voice;
  }

  start(buffer, loop, busName, volumeDb, options) {
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    if (loop) {
      source.loop = true;
      source.loopStart = loop.start;
      source.loopEnd = loop.end;
    }
    if (options.playbackRate) source.playbackRate.value = options.playbackRate;
    const gain = this.context.createGain();
    gain.gain.value = dbToGain(volumeDb);
    source.connect(gain);
    gain.connect(this.bus(busName));
    source.start(options.when || 0);
    return { source, gain };
  }

  end(name, voice) {
    voice.source.onended = null;
    try {
      voice.source.stop();
    } catch (error) {
      // already stopped
    }
    voice.gain.disconnect();
    this.forget(name, voice);
  }

  forget(name, voice) {
    const alive = this.sounding(name).filter((v) => v !== voice);
    if (alive.length) this.playing.set(name, alive);
    else this.playing.delete(name);
  }
}
