# Samples

Sampled instruments: libraries, sample:, SFZ/SF2/WAV, fetching.

## Samples (recorded instruments: any kit can mix them with synths)

`sample:` replaces `osc`/`drum`; envelope, filter, vibrato, pitch keyframes, gain, voices, crush, `mute` and `fx` still
apply. A sampled instrument is an ordinary kit instrument: a synth kit can have a real piano, an erhu or a brush kit
next to its pulse lead.

```yaml
instruments:
  v: { name: violins, sample: vsco2/violins_sus, voices: 4, env: [0.04, 0, 1, 0.35] }   # library instrument
  r: { name: harp, sample: vsco2/harp, voices: 8 }                                        # one-shot: rings to its end
  T: { name: timpani, sample: vsco2/timpani, voices: 2 }
  B: { name: bass_drum, sample: vsco2/bass_drum }                                        # unpitched: drum lanes
  g: { sample: { sf2: samples/GeneralUser.sf2, preset: 48, bank: 0 } }                   # SoundFont preset (number or name)
  k: { sample: { sfz: samples/keys.sfz, velocity: 100 } }                                # always that velocity layer
  z: { sample: { wav: samples/zap.wav, root: A4, loop: true } }                           # one WAV, pitched from root
```

- **Libraries** (all CC0; `segan samples list` shows every instrument with its size and range):
  - `vcsl` = Versilian Community Sample Library: keys (`grand_piano`, `fm_piano` electric piano, `clavisynth`,
    `harpsichord`, `pipe_organ`, `pipe_organ_loud`), plucked (`folk_harp`, `dan_tranh` zither/koto-like, `strumstick`),
    mallets and bells (`vibraphone`, `vibraphone_hard`, `tubular_bells`, `hand_chimes`, `balafon`, `kalimba`, `mbira`),
    winds (`harmonica`, `tenor_sax`, `recorder`, `ocarina`, `bowed_psaltery`), hand and world percussion (`conga`,
    `conga_mute`, `quinto`, `tumba`, `bongo_high`/`_low`, `cajon_1`-`_3`, `darbuka_1`/`_3`/`_5`, `frame_drum`,
    `frame_drum_small`, `shaker`, `cowbell`, `woodblock`, `claves`, `agogo_high`/`_low`, `clap`, `cabasa`, `guiro`,
    `slit_drum_high`/`_low`, `sleigh_bells`, `finger_cymbals`), kit pieces (`snare_drum`, `snare_off`, `hihat`,
    `hihat_open`, `tom_high`, `tom_low`) and found metal (`anvil`, `brake_drum`).
  - `karoryfer` = Karoryfer Lecolds: guitars (`clean_guitar`, `gretsch`, `gretsch_mute` palm-muted, `hofner`), basses
    (`bass_guitar`, `bass_guitar_dark`, `upright_pizz`, `upright_arco`), `erhu`, `erhu_stac`, and a drum kit (`kick`,
    `cajon_kick`, `snare`, `snare_edge`, `brush` (a brush stirred on the snare), `hat_closed`, `hat_tight`, `hat_half`,
    `hat_open`, `hat_foot`, `tom_floor`, `tom_low`, `tom_mid`, `tom_high`, `tom_very_high`, `crash`, `ride`, `splash`,
    `china`, `djembe`).
  - `neosound` = NeoSoundFonts (Simone Piervergili): `voice_oohs` (a male "ooh": stack `voices` for a small choir, or
    use the `formant` model), `steel_guitar`, `bamboo_flute`.
  - `vsco2` = VSCO 2 Community Edition (CC0, Versilian Studios): strings (sections: `violins_`, `violas_`,
  `cellos_` `sus|trem|pizz|spic`, `basses_sus|pizz`, `violin_solo`, `harp`), brass (`horn_`, `trumpet_`, `trombone_`,
  `tuba_` `sus|stac`), woodwinds (`flute_`, `oboe_`, `clarinet_`, `bassoon_` `sus|stac`, `piccolo`), percussion
  (`timpani`, `timpani_roll`, `glockenspiel`, `marimba`, `xylophone`, `bass_drum`, `snare`, `crash`, `sus_cymbal`,
  `tam_tam`, `triangle`, `tambourine`), `piano` (upright).
  The audio isn't in SEGAN: `segan samples fetch <library> <instrument...>` downloads only those (pinned commits, checked)
  into a user cache shared by every project. Lint says what to fetch if a kit needs more. Every library instrument is
  levelled to the same loudness (plain notes), so kit `gain` is pure balance. Unpitched ones (hits) play in drum lanes.
- Paths (wav/sfz/sf2) are relative to the project folder (the one with segan.toml). WAV: PCM 8-32-bit or float,
  any rate, mono or stereo (mixed to mono; tracks pan and the room widens). `smpl` loops are used.
- `env` defaults to the file's own (SFZ `ampeg_*`, SF2 volume envelope); `range` defaults to the mapped keys
  (E007 outside). Note velocity picks the layer: plain notes 80 (mf), accents `X` 120, ghosts `o` 28.
- Sustained samples (`_sus`) play while the note is held, then release; a note held longer than its sample
  is silent at the end (W014: shorten it or re-strike). One-shots (`pizz`, `stac`, `harp`, percussion, SFZ
  `loop_mode=one_shot`, `one_shot: true`) ring to their natural end whatever the note length; `voices` caps how
  many ring at once. In an SFX layer, `length:` chokes a one-shot (then its `env` release).
- SFZ subset: `<control> <global> <master> <group> <region>`, `sample default_path key lokey hikey
  pitch_keycenter lovel hivel tune transpose volume amplitude offset end loop_mode loop_start loop_end
  seq_length seq_position lorand hirand trigger ampeg_*`, `#define`. SF2: key/velocity zones, root key, tuning,
  loops, attenuation, volume envelope (modulators, filters and effects are ignored).
  `segan samples list file.sf2` lists a SoundFont's presets.
- Sampled songs render slower than synth ones (a 30 s orchestral loop ~20 s cold); renders are cached.
