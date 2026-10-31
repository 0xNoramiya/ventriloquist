# Generated test clips: a photoreal, fictional patient

The cartoon clips in [`DETECTOR_EVAL_SYNTHETIC.md`](DETECTOR_EVAL_SYNTHETIC.md) passed easily, which
says little about real faces. Filming patients is out of the question, so we generated a fictional
ICU patient and animated the answer signals. Nobody in these clips exists.

![Generated patient and gestures](img/generated-patient.jpg)

## How the clips were made

The start frame is an AI-generated still. The prompt, in short: a fictional Indonesian man in his
early 60s, awake in an ICU bed, endotracheal tube taped at the mouth, seen by a phone on the bed
rail.

An image-to-video model animated that same frame, one prompt per clip (fast variant, 480p, 4 s, no
audio). The output is 752x560 at 24 fps. Every prompt starts "locked-off static camera" and
describes one movement.

In the clips, YES is both eyebrows raised, once or twice. NO is both eyes squeezed shut for about
one to two seconds. "No answer" clips are still, with distractors: natural blinks, a gaze shift to
the side, a swallow. The emergency signal is the eyebrows raised three or more times.

Calibration uses 8 clips (a 12-second rest, 3 YES, 3 NO, 1 emergency) and evaluation 13 (3 YES,
4 NO, 4 no answer, 2 emergency). The YES clips include a late raise and a small, tired one.

We checked every label instead of assuming the model followed its prompt. For each clip we measured
motion over time in a brow region and an eye region and looked at frame strips. One clip was
excluded: its prompt asked for two raises and the model produced three, which is the emergency
signal, so its label was ambiguous.

The clips stay in `data/labeled_generated/` (gitignored), with a manifest of each clip's label and
variation.

Run it: `PYTHONPATH=backend:. backend/.venv/bin/python scripts/eval_detector.py --mode live
--data data/labeled_generated --name GENERATED --verbose`.

## What the realistic face exposed

Live models, the same 13 evaluation windows at every step. "Wrong" means a confident wrong answer;
"unclear" means the question is asked again.

| Step | Judge correct | Fused correct | Wrong | Unclear |
|---|---:|---:|---:|---:|
| Start: judge sees the whole 320x240 frame | 4 of 11 | 5 | 1 | 7 |
| Judge sees a crop around the signal body parts | 9 of 12 | 6 | 0 | 7 |
| Judge prompt v4 (a blink is not a held squeeze); SAM "seen" feature | 10 of 11 | 7 | 0 | 6 |
| Fusion as a logarithmic opinion pool | 12 of 12 | 11 | 0 | 2 |

The judge sometimes times out, so its count varies. Its answers also vary between runs: an
identical run at the first step scored 8 of 13 fused, 3 of them wrong. A judge-only check with two
runs per clip gave 12 of 26 on the whole frame, 24 of 26 on the crop, and 26 of 26 on the crop with
prompt v4.

### Three runs on the finished pipeline

One pass over 13 windows reports luck as well as accuracy, so the whole set was scored three times
on one calibration (`--runs 3`, $0.90, report
[`DETECTOR_EVAL_GENERATED.md`](DETECTOR_EVAL_GENERATED.md)):

| Run | Fused correct | Wrong | Asked again | Judge correct / answered | Median latency |
|---|---:|---:|---:|---:|---:|
| 1 | 12 | 0 | 1 | 12 / 13 | 3.7 s |
| 2 | 12 | 0 | 1 | 13 / 13 | 4.0 s |
| 3 | 10 | 0 | 3 | 10 / 12 | 4.6 s |

Correct 11.3 of 13 on average (10 to 12), and the number that matters for a patient: **no
confidently wrong answer in 39 judgments**. The judge was wrong three times across the three runs
and SAM disagreed each time, so fusion returned UNCLEAR and the phone asked again instead of
guessing. Every YES, NO and emergency signal was read in all three runs except one small, late
raise in run 3; the clip that is hardest is the same one each time, a resting window the judge
reads as NO.

Run it:

```bash
PYTHONPATH=backend:. backend/.venv/bin/python scripts/eval_detector.py \
  --mode live --data data/labeled_generated --name GENERATED --runs 3
```

1. **Resolution.** On a whole 320x240 frame this face is about 110 px wide and an eyebrow raise
   moves a few pixels. The judge reported "eyes open resting, no eyebrow raise" on clear raises.
   Calibration now takes the area SAM 3.1 tracked on the calibration clips, widens it, and the
   judge always watches that crop, cut from the phone's full-resolution clip
   (`calibration.signal_roi`).
2. **Blinks.** The judge read natural blinks as the NO squeeze. Prompt v4 spells out the
   difference: a blink lasts one or two frames, a squeeze stays shut for a second or more with
   tight wrinkles at the eye corners.
3. **Vanishing eyes.** With eyes squeezed shut, SAM sometimes no longer finds "eyes", and the
   pipeline treated the lost box as noise. Whether the part was seen at all is now a feature of its
   own. It did not fix SAM on these clips: here SAM mostly still found the closed eyes, and its
   box barely changed.
4. **Fusion.** A weighted average let two agreeing but modest readings (SAM "no answer" at 0.84,
   judge at 0.45) fall below the 0.65 threshold together. Independent sources now multiply, each
   raised to its calibration weight: agreement reinforces, and a YES-against-NO split stays UNCLEAR.

The cartoon set still scores 12 of 12 after these changes.

## Privacy mode on Muse Spark Open (Baseten)

Same 13 windows, privacy mode: Muse Spark Open on Baseten writes the calibration description and is
the blind judge; with no self-hosted SAM, the tracker is the on-device optical flow. Report:
[`DETECTOR_EVAL_GENERATED_PRIVACY.md`](DETECTOR_EVAL_GENERATED_PRIVACY.md). "Asked again" is an
unclear reading or no movement seen on a signal clip; "wrong" is a confident different answer.

| Step | Right | Wrong | Asked again | What it showed |
|---|---:|---:|---:|---|
| First live run | 1 | 0 | 12 | Calibration failed: `400 "Too many videos: 5 (max 2)"`, so the judge had no signal description |
| Describer sends one YES and one NO clip, labelled | 7 | 1 | 5 | No SAM, so no crop: YES 0 of 3 on the whole frame |
| Crop from where the calibration clips move | 9 to 10 | 1 | 2 to 3 | Emergency 0 of 2: "one sustained brow lift" |
| Clips played at half speed | 11 | 2 | 0 | Final; the two errors are resting clips read as NO |

1. **Two videos per request.** Meta's API takes 5 videos; Muse Spark Open takes 2 (Baseten's docs
   say so too; the code didn't respect it). The adapter had also dropped the "YES clip 1" labels
   on videos, so the describer could not have told the clips apart anyway.
2. **A crop without SAM.** Calibration now averages frame-to-frame change over the YES and NO clips,
   subtracts the rest clip (blinks, noise), and pads the moving region into the same square the
   SAM crop uses. On these clips it lands on the eyebrows; nothing leaves the device to find it.
3. **Two frames per second.** Numbered test frames showed Baseten samples video at 2 fps of video
   time whatever the clip's rate, with no request field for it (Meta's API takes `fps`). The judge
   saw about 8 frames of a 4-second window. Slowing the clip gives it more frames, but slowed too
   far the judge measures how long the eyes stay shut in playback time, and a blink looks like a
   held squeeze. Judge alone, each window judged twice:

   | Clip as sent | Right of 26 | Asked again | Wrong | Emergency | Median latency |
   |---|---:|---:|---:|---:|---:|
   | Real speed (2 fps) | 17 | 7 | 2 | 0 of 4 | 3.9 s |
   | 3 fps, 1.5x slower | 18 | 3 | 5 | 2 of 4 | 7.4 s |
   | **4 fps, 2x slower (kept)** | **25** | **0** | **1** | **4 of 4** | **6.0 s** |
   | 4 fps, 2x slower, real time printed on each frame | 19 | 0 | 7 | 4 of 4 | 6.9 s |
   | 8 fps, 4x slower (one full run, 13 windows) | 9 | 1 | 3 | 2 of 2 | 9.0 s |

   With the time printed on every frame the judge read it ("held shut for about 0.6-0.7 s") and
   still called the blink a NO, so the stamp was dropped.

The remaining error is the one that matters most: two of four resting clips came back as NO. The
sweep had 7 of 8 resting windows right with a calibration that described NO as "closes both eyes
and holds them closed"; the full run's calibration called it "a prolonged blink". Each calibration
writes its own description, so the result moves with it. Muse Spark on Meta's API, with SAM, made
no confident errors on the same clips.

## Limits

One fictional identity, one start frame for calibration and evaluation (same pose and lighting),
generated motion that is cleaner than a weak or sedated patient's, and 13 evaluation windows. SAM's
box geometry is the weak part on this face (6 of 10 where it tracked); the judge carries the
decision. These numbers say nothing about real patients.
