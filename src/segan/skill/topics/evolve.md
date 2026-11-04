# Evolve

Changing the sound over time: mix adjust, config, style bump.

## Changing the sound over time

Global changes go through the shared mix, so **every asset changes at once** and the set stays consistent:

| Owner says | Do |
|---|---|
| "too dry" / "too much echo" | `segan mix adjust --room 0.1` / `--room -0.1` |
| "brighter" / "darker", "muddy" | `segan mix adjust --brightness 2` / `-2` |
| "warmer" / "thinner" | `segan mix adjust --warmth 2` / `-2` |
| "more retro / lo-fi" | `segan mix adjust --crush 8` (`0` = off) |
| "everything too loud" | `segan mix adjust --loudness -2` (all targets) or `segan config set loudness.sfx -16` |
| "UI too loud" | `segan config set loudness.ui -23` |
| "short clicks/lasers too hot" (peak as high as an explosion) | `segan config set loudness.short_sfx duration` (one-shots under 400 ms measured over their own length); `segan gallery` shows peaks and that level in brackets |
| "high notes sound harsh/buzzy" | `segan config set mix.oversample 4` (less aliasing) |
| "the lead should be softer" | edit the kit instrument (every song using it changes); `segan kit show` |
| "make the music more tense" | variants (`tempo`, `key`, `instrument_swap`) or new sections |

Always `--dry-run` first, then `segan gallery` (every asset side by side + a loudness chart by category) and
log the change in BRIEF.md. When existing sources must be rewritten (a new kit, new drum style):
`segan style bump "what changed"`, update SOUND.md, go through the assets `segan status` flags (W006), and
`segan mark <name> --current` each one after a human listened.
