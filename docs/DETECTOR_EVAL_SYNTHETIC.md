# Detector evaluation

Mode `live`, 12 clips at 15 fps (SYNTHETIC cartoon clips: not evidence about real patients).
Calibration leave-one-out accuracy: {'local': 1.0, 'tracker': 1.0, 'spark': 1.0}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}.
Latency per answer window: median 3024.0 ms, p90 8500 ms.

## fused (accuracy 1.00)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 3 | 0 |

## tracker (accuracy 1.00)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 3 | 0 |

## spark (accuracy 1.00)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 2 | 0 | 0 |
| emergency | 0 | 0 | 0 | 1 | 0 |
