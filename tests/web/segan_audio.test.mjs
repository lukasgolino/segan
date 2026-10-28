// Headless tests of the web helper (src/segan/templates/segan_audio.js) against a fake AudioContext.
// Run by tests/test_web.py with `node --test`; with SEGAN_WEB_BUILD=<dir> also against a real `segan build`.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const helper = process.env.SEGAN_AUDIO_JS;
const { SeganAudio, sfxChoices, loopSeconds, dbToGain } = await import(pathToFileURL(helper).href);

class FakeParam {
  constructor(value) {
    this.value = value;
  }
}

class FakeNode {
  constructor() {
    this.outputs = [];
  }
  connect(node) {
    this.outputs.push(node);
    return node;
  }
  disconnect() {
    this.outputs = [];
  }
}

class FakeSource extends FakeNode {
  constructor(context) {
    super();
    this.context = context;
    this.playbackRate = new FakeParam(1);
    this.loop = false;
    this.loopStart = 0;
    this.loopEnd = 0;
    this.started = null;
    this.stopped = false;
    this.onended = null;
  }
  start(when) {
    this.started = when;
    this.context.sources.push(this);
  }
  stop() {
    this.stopped = true;
  }
  finish() {
    if (this.onended) this.onended();
  }
}

class FakeContext {
  constructor() {
    this.currentTime = 0;
    this.destination = new FakeNode();
    this.sources = [];
  }
  createBufferSource() {
    return new FakeSource(this);
  }
  createGain() {
    const node = new FakeNode();
    node.gain = new FakeParam(1);
    return node;
  }
  async decodeAudioData(bytes) {
    const view = new DataView(bytes);
    assert.equal(String.fromCharCode(...new Uint8Array(bytes, 0, 4)), "RIFF");
    return { sampleRate: view.getUint32(24, true), bytes: bytes.byteLength };
  }
}

const fakeFetch = (files) => async (url) => {
  if (!(url in files)) return { ok: false, status: 404 };
  return { ok: true, status: 200, json: async () => files[url], arrayBuffer: async () => files[url] };
};

function wav(rate) {
  const bytes = new ArrayBuffer(44);
  const view = new DataView(bytes);
  [..."RIFF"].forEach((c, i) => view.setUint8(i, c.charCodeAt(0)));
  view.setUint32(24, rate, true);
  return bytes;
}

const MANIFEST = {
  assets: {
    coin: { kind: "sfx", category: "pickup", sample_rate: 22050, file: "sfx/coin.wav", loop: null,
            variations: [{ file: "sfx/coin.1.wav", loop: null }, { file: "sfx/coin.2.wav", loop: null }, { file: "sfx/coin.3.wav", loop: null }],
            bus: "SFX", playback: { max_instances: 2, min_gap_s: 0.05, repeat_attenuation_db: 3 } },
    hit: { kind: "sfx", category: "sfx", sample_rate: 22050, file: "sfx/hit.wav", loop: null,
           takes: [{ take: 2, file: "sfx/hit.t2.wav", loop: null }, { take: 3, variations: [{ file: "sfx/hit.t3.1.wav", loop: null }] }] },
    engine: { kind: "sfx", category: "sfx", sample_rate: 22050, file: "sfx/engine.wav", loop: { start: 1, end: 22051 } },
    theme: { kind: "song", category: "music", sample_rate: 44100, file: "music/theme.wav", loop: { start: 88200, end: 441000 },
             variants: { calm: { file: "music/theme.calm.wav", loop: { start: 44100, end: 220500 } } } },
  },
  buses: { pickup: { bus: "SFX", volume_db: -6 } },
};

function player(random = () => 0) {
  const files = { "base/manifest.json": MANIFEST };
  for (const entry of Object.values(MANIFEST.assets)) {
    for (const f of [entry.file, ...(entry.variations || []).map((v) => v.file), ...(entry.takes || []).flatMap((t) => [t.file, ...(t.variations || []).map((v) => v.file)]),
                     ...Object.values(entry.variants || {}).map((v) => v.file)]) {
      if (f) files[`base/${f}`] = wav(entry.sample_rate);
    }
  }
  const context = new FakeContext();
  return { context, open: () => SeganAudio.open("base/manifest.json", { context, fetch: fakeFetch(files), random }) };
}

test("choices match the Godot randomizer", () => {
  assert.deepEqual(sfxChoices(MANIFEST.assets.coin).map((c) => c.file), ["sfx/coin.1.wav", "sfx/coin.2.wav", "sfx/coin.3.wav"]);
  assert.deepEqual(sfxChoices(MANIFEST.assets.hit).map((c) => c.file), ["sfx/hit.wav", "sfx/hit.t2.wav", "sfx/hit.t3.1.wav"]);
  assert.deepEqual(sfxChoices(MANIFEST.assets.engine).map((c) => c.file), ["sfx/engine.wav"]);
  assert.deepEqual(loopSeconds(MANIFEST.assets.engine, 22050), { start: 1 / 22050, end: 22051 / 22050 });
  assert.equal(loopSeconds(MANIFEST.assets.coin, 22050), null);
  assert.ok(Math.abs(dbToGain(-6) - 0.501187) < 1e-6);
});

test("load fetches next to the manifest and decodes every SFX file", async () => {
  const { open } = player();
  const audio = await open();
  await audio.load();
  assert.equal(audio.buffers.size, 7); // coin: its 3 variations (the randomizer has no main file), hit: 3 takes, engine
  assert.ok(audio.buffers.has("sfx/hit.t3.1.wav") && !audio.buffers.has("music/theme.wav"));
});

test("variations never repeat back to back", async () => {
  let n = 0;
  const sequence = [0, 0, 0.99, 0.99, 0.5];
  const { open, context } = player(() => sequence[n++ % sequence.length]);
  const audio = await open();
  await audio.load(["coin"]);
  const picks = [];
  for (let i = 0; i < 5; i++) {
    context.currentTime += 1;
    const voice = audio.play("coin");
    picks.push(voice.source.buffer === audio.buffers.get("sfx/coin.1.wav") ? 1 : voice.source.buffer === audio.buffers.get("sfx/coin.2.wav") ? 2 : 3);
    voice.source.finish();
  }
  for (let i = 1; i < picks.length; i++) assert.notEqual(picks[i], picks[i - 1], picks.join());
});

test("bus, category volume and playback hints", async () => {
  const { open, context } = player();
  const audio = await open();
  await audio.load(["coin"]);
  const first = audio.play("coin");
  assert.ok(Math.abs(first.gain.gain.value - dbToGain(-6)) < 1e-12);
  assert.equal(first.gain.outputs[0], audio.bus("SFX"));
  assert.equal(audio.bus("SFX").outputs[0], context.destination);
  assert.equal(audio.play("coin"), null); // within min_gap_s
  context.currentTime = 0.1;
  const second = audio.play("coin", { volumeDb: -2 });
  assert.ok(Math.abs(second.gain.gain.value - dbToGain(-6 - 3 - 2)) < 1e-12); // one copy sounding: -3 dB
  context.currentTime = 0.2;
  const third = audio.play("coin");
  assert.ok(first.source.stopped && !second.source.stopped); // max_instances 2: the oldest stops
  assert.deepEqual(audio.sounding("coin"), [second, third]);
  second.source.finish();
  assert.deepEqual(audio.sounding("coin"), [third]);
  audio.stop("coin");
  assert.ok(third.source.stopped && audio.sounding("coin").length === 0);
});

test("looping SFX and songs loop at the manifest points", async () => {
  const { open } = player();
  const audio = await open();
  await audio.load(["engine"]);
  const hum = audio.play("engine");
  assert.ok(hum.source.loop && hum.source.loopStart === 1 / 22050 && hum.source.loopEnd === 22051 / 22050);
  assert.equal(audio.busFor("engine"), "Master");
  const song = await audio.playSong("theme");
  assert.ok(song.source.loop && song.source.loopStart === 2 && song.source.loopEnd === 10);
  const calm = await audio.playSong("theme", { variant: "calm" });
  assert.ok(calm.source.loopStart === 1 && calm.source.loopEnd === 5);
  await assert.rejects(audio.playSong("coin"), /no song named coin/);
});

test("unknown names and unloaded files play nothing", async () => {
  const { open } = player();
  const audio = await open();
  const errors = [];
  const original = console.error;
  console.error = (message) => errors.push(message);
  try {
    assert.equal(audio.play("nope"), null);
    assert.equal(audio.play("engine"), null);
  } finally {
    console.error = original;
  }
  assert.match(errors[0], /no SFX named nope/);
  assert.match(errors[1], /isn't loaded/);
});

test("a real segan build", { skip: !process.env.SEGAN_WEB_BUILD }, async () => {
  const root = process.env.SEGAN_WEB_BUILD;
  const fetchDisk = async (url) => {
    try {
      const data = await readFile(join(root, url));
      const bytes = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
      return { ok: true, status: 200, json: async () => JSON.parse(data.toString("utf-8")), arrayBuffer: async () => bytes };
    } catch {
      return { ok: false, status: 404 };
    }
  };
  const context = new FakeContext();
  const audio = await SeganAudio.open("manifest.json", { context, fetch: fetchDisk });
  await audio.load();
  const names = Object.keys(audio.manifest.assets).filter((n) => audio.manifest.assets[n].kind === "sfx");
  assert.ok(names.length > 0);
  for (const name of names) assert.ok(audio.play(name), name);
  for (const name of Object.keys(audio.manifest.assets).filter((n) => audio.manifest.assets[n].kind === "song")) {
    const voice = await audio.playSong(name);
    assert.equal(voice.source.buffer.sampleRate, audio.manifest.assets[name].sample_rate);
  }
});
