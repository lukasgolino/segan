# Soundtrack

Soundtracks: states, song pools, transitions, families.

## Soundtrack - `music/<name>.soundtrack.yaml`

Which songs a game plays in which state, and how it moves between states (played by the Godot director):

```yaml
name: main
start: explore
states:
  explore: { songs: { overworld: 2, village: 1, cave: 1 }, play: [120, 240], gap: [10, 40], fade_out: 3, crossfade: 4 }
  combat: { songs: [combat, overworld.danger] }      # `song.variant`
  menu: [title]                                      # a list = songs only
families:                                            # songs that cross-fade into each other inside a state
  a_minor: [overworld, village]                      # (`overworld` is the main version; list variants as `song.variant`)
transitions:                                         # most specific wins: "from>to", "from>*", "*>to", "*"
  "*": { at: bar, fade: 2 }                          # the default is { at: bar, fade: 2 }
  explore>combat: { at: beat, fade: 0.5, stinger: hit, start: main }
  combat>explore: { at: section, fade: 4, fade_in: 2 }
```

State: `songs` (list, or weights; never the same song twice in a row when there are others), `play` (seconds a
song plays before it ends, a number or [min, max]; a flow song then finishes its section and plays `end` or
its tail, a looping song fades out over `fade_out`; default: forever when the state has one song and no gap,
else [120, 240]), `gap` (seconds of silence between songs, number or [min, max]: silence makes music last),
`crossfade` (seconds; when the next song is in the same family as the one ending, it comes in on the next bar
and the two overlap this long, no gap; songs of different families still fade out, wait the gap and start;
default 0 = never). `families`: family -> songs (each song in one family; a song in none is its own family).
A big shuffled pool of short loops: put the loops of one key/tempo in a family, give the state a `crossfade`
and a short `play` (e.g. [30, 60]), and they flow into each other; changing family gets a breath of silence.
Transition: `at` (`now`, `beat`, `bar`, `section`, `end`: when the switch happens, on the old song's grid),
`fade` (seconds the old song fades out; 0 with `at: section` lets a flow song ring out naturally), `fade_in`,
`stinger` (an SFX played at the switch), `start` (a section of the new song to start at). E018: unknown
state/song/variant/SFX/section or family member, or a bad field; W016: a cross-fade between songs whose keys
clash, in a transition or a family (keep fades between related keys, or use a short fade with a stinger).
