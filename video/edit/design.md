# Ventriloquist demo video: design

The video uses the app's colors and type from `frontend/src/index.css`, so the story scenes, cards
and screen recordings read as one film.

## Colors

| Role | Hex | Use |
|---|---|---|
| Night | `#0b252b` | Main ground for cards and captions; the patient phone's background |
| Night 2 | `#12343b` | Panels on night |
| Night 3 | `#1d4850` | Rules and borders on night |
| Mist | `#c9d8d8` | Secondary text on night |
| Paper | `#ffffff` | Primary text on night |
| Linen | `#f1f4f3` | Light ground (the console's page color) |
| Ink | `#0f2e35` | Text on light grounds |
| Voice | `#f3c14b` | The accent: the patient's voice, highlights, the title's mark |
| Voice deep | `#7a5300` | Voice on light grounds |
| Alarm | `#b3261e` | The emergency only |
| Good | `#2c6a3f` | Confirmations only |

## Type

Atkinson Hyperlegible Next (variable, 200 to 800), the app's typeface. It was designed for readers
with low vision, which suits a film about access. Local files in `fonts/`. Headlines 700, body 500,
labels 600 with tabular numbers.

## Corners and depth

Rounded panels (24px on video), flat fills, no glass, no gradients across the frame. Depth comes
from footage, not shadows.

## Don'ts

- No purple, no neon, no gradient text, no emoji.
- Alarm red only for the emergency beat.
- Never cover a face with a caption or card.
- Never imply the app did something it didn't: every UI moment is a real screen recording.
