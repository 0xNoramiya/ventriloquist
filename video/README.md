# Demo video

Production files for the 3-minute demo video. Nothing here is part of the app or runs in it. The
app's own models are all Meta's (see the main README). The script and timeline are in
[`../docs/DEMO_SCRIPT.md`](../docs/DEMO_SCRIPT.md).

Three kinds of material:

- **App footage.** Screen recordings of the running app, on fly.io or on a local server running the
  same build (`VENT_BASE=http://127.0.0.1:8010`). In live mode the camera is the generated Mr Hasan
  gesture clips from `data/labeled_generated` (the detector eval set), so SAM 3.1 and the blind
  Muse Spark judge really read every answer; in the privacy take Muse Spark Open on Baseten reads
  them. The spelling beat is a mock run with the simulated patient, and says so on screen.
- **Story scenes.** Generated stills and image-to-video clips of the same fictional patient, nurse
  and daughter. They never show the app doing anything.
- **Sound.** Generated narration, a second generated voice standing in for the phone's built-in
  speech, an instrumental score and room sounds. The app's chime and alarm are rendered from the
  app's own code.

## Rebuilding it

Everything generated lands in `media/` and `edit/assets/` (both gitignored). `npm run audio` and
`caption-timings.mjs` call the ElevenLabs API with `ELEVENLABS_API_KEY` from `../.env.local`. Run
from this folder:

```bash
npm install
npm run audio                          # narration, phone lines, score, effects
node render-app-sounds.mjs             # the app's chime and alarm, from frontend/src/lib/alarm.ts
node --env-file=../.env.local caption-timings.mjs   # word timings for the captions

# app footage: live takes need the fly.io passcode (never commit it)
VENT_PASSCODE=... node record-app.mjs calibrate
VENT_PASSCODE=... node record-app.mjs session
VENT_PASSCODE=... node record-app.mjs privacy   # needs BASETEN_API_KEY on the server
node record-app.mjs spelling           # mock mode, simulated patient

cd edit
node build.mjs                         # cuts the footage, writes index.html, mixes assets/mix.wav
npm run check                          # lint, runtime, layout and contrast checks
npm run render                         # renders/…mp4
```

No script here makes the story clips and stills in `media/gen/`. Their prompts are in
`docs/DEMO_SCRIPT.md` under "Shots to generate".

## Files

| File | What it does |
|---|---|
| `cues.json` | Narration lines (N1 to N9, N8b), the phone's lines (P0 to P8), the score's sections, the effects; `say` is a spelling for the voice only |
| `generate-audio.mjs` | Generates the narration, phone lines, score and effects; keeps files that exist unless `--force` |
| `caption-timings.mjs` | Speech-to-text word timings for the narration, with the script's spelling kept |
| `render-app-sounds.mjs` | The app's chime and alarm as WAV, from the same oscillator calls as the app |
| `record-app.mjs` | Drives the app in Chromium, fakes the camera with the generated clips, records both screens |
| `edit/build.mjs`, `edit/lib.mjs` | The edit: every cut, layer, caption and sound cue |
| `edit/style.css`, `edit/page.tpl`, `edit/design.md` | The film's look, taken from the app's palette and font |
