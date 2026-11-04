# Long form

Long-form music: section changes and flow graphs.

## Long-form music: section changes and `flow`

An 8-bar loop on repeat wears players out within minutes. Write more material cheaply, and let the game walk it:

**Section changes.** A section is a pattern list or a mapping that changes its patterns' notes as they play:

```yaml
sections:
  verse: [a, b, a, c]
  verse_up: { from: verse, semitones: 2 }                  # same section a tone higher (a key change)
  chorus: { patterns: [d, d, e, f] }
  chorus_soft: { from: chorus, mute: [drums], velocity: 0.7, instrument_swap: { p: q } }
  breakdown: { patterns: [a, b], mute: [lead, harmony] }
  bridge: { patterns: [g, h], key: A major }               # same scale degrees in another key/mode
```

`patterns` or `from` (another section: its patterns and changes, then this one's fields over them), `transpose`
(scale steps), `semitones`, `key`, `instrument_swap`, `group_swap`, `mute` (tracks), `velocity` (0.05-2, or
`{ track: scale }`). Pitch changes apply at play time, so `semitones: 2` doesn't need the rows to exist; a song
variant applies first, the section's changes on top. Ranges (E007) and voices (E014) are checked per section.

**Flow (the game picks the next section).** Without `flow`, a song is one arrangement with one loop. With it,
the game (SEGAN's Godot director, or your own player from the manifest) chains sections at run time:

```yaml
arrangement: [intro, verse, chorus, verse_up, chorus, bridge, chorus]   # still the linear version (preview, simple games)
flow:
  start: intro                       # or a list: one is picked
  next:                              # which sections may follow which: a list, or weights
    intro: [verse]
    verse: { chorus: 3, breakdown: 1 }
    verse_up: [chorus]
    chorus: { verse: 2, verse_up: 1, bridge: 1, chorus_soft: 1 }
    chorus_soft: [verse, bridge]
    breakdown: [chorus]
    bridge: { chorus: 1, verse_up: 1 }
  end: outro                         # optional: played when the game ends the song (any section may go to it)
  no_repeat: true                    # never the same section twice in a row unless it's the only way on (default)
  variants: [danger]                 # variants that get flow clips too (default: none)
```

Every flow section must be whole bars (E017); every section reachable from `start` and able to go on (or be
the `end`). Each section is built as clips: `flow/<song>/<section>.head.wav` (its first bar(s), cold),
`<section>.from.<prev>.wav` (the same bars with the previous section's ring-out baked in), `<section>.wav` (the
rest) and `<section>.tail.wav` (its ring-out when the music stops after it). Chained back to back they equal a
linear render of that path, so every seam is clean whatever order the game picks. W015: a section shorter than
the ring-out before it (that ring-out gets cut).

Writing for flow: 5-10 sections of 4-8 bars with real contrast (a breakdown, a bridge, a key change, a soft
chorus) give minutes before an order repeats; derive most of them with section changes. Keep each section's
first bar playable after any of its predecessors (the harmony joins), and end each section on a cadence that
can lead into all of its `next` sections. `segan preview <song> --output walk` (or `walk:<seed>`) renders a
3-minute seeded walk from the clips (`<song>.walk1.wav`, sections marked on the sheet, `join_error` in
the analysis: max difference from a straight render of the path, < 0.001): listen to that, not just the arrangement.
