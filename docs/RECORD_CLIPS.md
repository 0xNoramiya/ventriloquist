# Recording a real face (about 20 minutes)

Every detector number in this repository comes from generated video. The one thing that would change
what can be claimed is a real human face, and that does not need a patient, a ward or an ethics
committee: it needs one consenting adult who can lie still and raise their eyebrows. Record
yourself.

Clips stay in `data/` and are never committed. Delete them whenever you like; nothing else depends
on them.

## Set up the shot

Put the phone where it would sit on a bed rail: roughly 40 to 60 cm away, a little above the face,
looking down at it. Lie back. Ordinary room light, nothing behind you that moves. Record 1080p if
the phone offers it; the app downsamples anyway.

## What to record

Two sets, every clip about 4 seconds except the long rest clip. Say the label out loud before each
take so the files are easy to sort afterwards.

**Calibration** (`data/labeled/calibration/`), one take each:

| File | What to do |
|---|---|
| `rest_0.mp4` | 12 seconds, still, blink naturally |
| `yes_0.mp4`, `yes_1.mp4`, `yes_2.mp4` | your YES: one raise held about a second; then two raises; then one raise early in the clip |
| `no_0.mp4`, `no_1.mp4`, `no_2.mp4` | your NO: eyes squeezed shut about a second; a longer squeeze; a shorter one |
| `emergency_0.mp4` | three or more quick raises |

**Evaluation** (`data/labeled/{yes,no,rest,emergency}/`), the part that gets scored:

- `yes/` three clips, and make them unequal: one clear, one small, one late in the window.
- `no/` four clips.
- `rest/` four clips of doing nothing, with the distractors that fooled the judge on generated video:
  natural blinks, a gaze to the side, a swallow.
- `emergency/` two clips.

Check each file before you score it. If a take does not show what its name says, delete it; a wrong
label is worse than a missing clip.

## Trim to 4 seconds

```bash
ffmpeg -ss 0.5 -i IN.mp4 -t 4 -an -c:v libx264 -pix_fmt yuv420p data/labeled/yes/yes_0.mp4
```

## Score them

```bash
PYTHONPATH=backend:. backend/.venv/bin/python scripts/eval_detector.py \
  --mode live --data data/labeled --name REAL --runs 3 --verbose
```

Three runs because the blind judge does not answer identically every time; the report gives each run
and the spread. It writes `docs/DETECTOR_EVAL_REAL.md` and costs well under a dollar.

## Reading the result

The number that matters is not how many were right. It is **how many were confidently wrong**, since
an unclear reading only makes the phone ask again, and a wrong one puts a word in someone's mouth.
On generated clips that number is zero across 39 judgments.

A worse score on a real face is worth more than a perfect score on generated video, and belongs in
the README either way.
