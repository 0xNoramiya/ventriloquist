# Detector evaluation

Mode `mock`, 9 clips (SYNTHETIC cartoon clips: not evidence about real patients).
Calibration leave-one-out accuracy: {'local': 0.8888888888888888}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}.
Latency per answer window: median 741 ms, p90 845 ms.

## fused (accuracy 0.89)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 2 | 0 | 1 |
| emergency | 0 | 0 | 0 | 0 | 0 |

## local (accuracy 1.00)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 3 | 0 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 0 | 0 |
