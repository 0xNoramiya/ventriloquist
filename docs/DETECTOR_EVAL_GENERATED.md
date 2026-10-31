# Detector evaluation

Mode `live`, 13 clips scored 3 times (39 judgments) at 15 fps.
AI-generated photoreal clips of one fictional ICU patient (one generated start frame, animated image-to-video), labels checked frame by frame; not evidence about real patients.
Calibration leave-one-out accuracy: {'local': 0.3333333333333333, 'tracker': 0.75, 'spark': 1.0}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}.
Latency per answer window: median 4057 ms, p90 5681 ms.

## 3 runs over the same 13 clips

One calibration, every clip scored again in each run. The blind judge is a language
model and does not always answer the same way, so a single pass over a set this small
reports luck as well as accuracy.

| run | fused correct | wrong | ask again | judge correct / answered | median latency |
|---|---:|---:|---:|---:|---:|
| 1 | 12 | 0 | 1 | 12 / 13 | 3680 ms |
| 2 | 12 | 0 | 1 | 13 / 13 | 3974 ms |
| 3 | 10 | 0 | 3 | 10 / 12 | 4607 ms |

Fused correct 11.3 (range 10-12) of 13; confidently wrong 0; ask again 1.7 (range 1-3).

The matrices below pool every run, so each cell counts 3 judgments per clip.

## fused (accuracy 0.87)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 8 | 0 | 0 | 0 | 1 |
| no | 0 | 12 | 0 | 0 | 0 |
| none | 0 | 0 | 8 | 0 | 4 |
| emergency | 0 | 0 | 0 | 6 | 0 |

## tracker (accuracy 0.55)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 1 | 0 | 3 | 3 | 0 |
| no | 0 | 1 | 6 | 2 | 0 |
| none | 0 | 0 | 9 | 0 | 0 |
| emergency | 0 | 0 | 0 | 6 | 0 |

## local (accuracy 0.38)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 0 | 0 | 2 | 0 | 0 |
| no | 0 | 0 | 3 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 0 | 0 |

## spark (accuracy 0.92)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 8 | 0 | 0 | 0 | 0 |
| no | 0 | 12 | 0 | 0 | 0 |
| none | 1 | 2 | 9 | 0 | 0 |
| emergency | 0 | 0 | 0 | 6 | 0 |
