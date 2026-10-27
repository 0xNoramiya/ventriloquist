# Detector evaluation

Mode `live`, 9 clips at 8 fps (SYNTHETIC cartoon clips: not evidence about real patients).
Calibration leave-one-out accuracy: {'local': 0.8888888888888888, 'tracker': 1.0, 'spark': 1.0}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}.
Latency per answer window: median 3037 ms, p90 3518 ms.

## fused (accuracy 0.89)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 2 | 0 | 0 | 1 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 0 | 0 |

## tracker (accuracy 1.00)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 0 | 0 |

## spark (accuracy 0.75)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 0 | 0 | 0 | 1 | 0 |
| no | 0 | 1 | 0 | 0 | 0 |
| none | 0 | 0 | 2 | 0 | 0 |
| emergency | 0 | 0 | 0 | 0 | 0 |
