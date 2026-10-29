# Detector evaluation

Mode `privacy`, 13 clips at 15 fps.
Generated clips of a fictional patient (docs/DETECTOR_DATA_GENERATED.md). Privacy mode: Muse Spark Open on Baseten judges a 2x slowed crop; the tracker is the on-device optical flow (no SAM).
Calibration leave-one-out accuracy: {'local': 0.3333333333333333, 'spark': 0.8571428571428571}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}.
Latency per answer window: median 7471 ms, p90 8365 ms.

## fused (accuracy 0.85)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 4 | 0 | 0 | 0 |
| none | 0 | 2 | 2 | 0 | 0 |
| emergency | 0 | 0 | 0 | 2 | 0 |

## local (accuracy 0.46)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 0 | 0 | 2 | 1 | 0 |
| no | 0 | 0 | 4 | 0 | 0 |
| none | 0 | 0 | 4 | 0 | 0 |
| emergency | 0 | 0 | 0 | 2 | 0 |

## spark (accuracy 0.85)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 4 | 0 | 0 | 0 |
| none | 0 | 2 | 2 | 0 | 0 |
| emergency | 0 | 0 | 0 | 2 | 0 |
