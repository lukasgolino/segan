# Orchestra example

A SEGAN project with sampled instruments from **VSCO 2 Community Edition** (Versilian Studios, CC0 1.0):
`kits/orchestra.kit.yaml` (string sections, horn, trumpet, flute, oboe, harp, glockenspiel, timpani, orchestral
percussion), `music/overture.song.yaml` (an 8-bar D minor adventure loop with a 2-bar intro, written by
`make_overture.py` with `segan.api`, grouped into adaptive stems: `calm` = strings + harp, `full` = + horn and
percussion) and `sfx/sting.sfx.yaml` (a timpani/crash/horn hit).

The samples aren't in the repository. Download the ones the kit and the sting use (~550 MB, into a cache shared by every
project; `SEGAN_SAMPLES` moves it):

```sh
cd examples/orchestra
segan samples list vsco2                       # what's there, what's downloaded
segan samples fetch vsco2 violins_sus violas_sus cellos_sus basses_sus cellos_pizz violins_spic horn_sus \
    trumpet_sus flute_sus oboe_sus harp glockenspiel timpani bass_drum crash snare horn_stac
segan kit show                                 # every instrument: previews/kits/orchestra.listen.png
segan preview music/overture.song.yaml --output main --output mix:calm
segan build                                    # build/audio/: WAVs, stems, manifest.json
```
