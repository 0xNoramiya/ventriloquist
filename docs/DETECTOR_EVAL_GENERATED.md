# Detector evaluation

Mode `live`, 13 clips at 15 fps.
AI-generated photoreal clips of one fictional ICU patient (Higgsfield: GPT Image 2.5 start frame, Seedance 2.0 image-to-video), labels checked frame by frame; not evidence about real patients.
Calibration leave-one-out accuracy: {'local': 0.3333333333333333, 'tracker': 0.625, 'spark': 1.0}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}.
Latency per answer window: median 3808 ms, p90 5682 ms.

## fused (accuracy 0.85)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 4 | 0 | 0 | 0 |
| none | 0 | 0 | 2 | 0 | 2 |
| emergency | 0 | 0 | 0 | 2 | 0 |

## tracker (accuracy 0.60)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 1 | 0 | 1 | 0 | 0 |
| no | 0 | 0 | 2 | 1 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 2 | 0 |

## local (accuracy 0.33)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 0 | 0 | 1 | 0 | 0 |
| no | 0 | 0 | 1 | 0 | 0 |
| none | 0 | 0 | 1 | 0 | 0 |
| emergency | 0 | 0 | 0 | 0 | 0 |

## spark (accuracy 1.00)

| true \ predicted | yes | no | none | emergency | unclear |
|---|---:|---:|---:|---:|---:|
| yes | 3 | 0 | 0 | 0 | 0 |
| no | 0 | 4 | 0 | 0 | 0 |
| none | 0 | 0 | 3 | 0 | 0 |
| emergency | 0 | 0 | 0 | 2 | 0 |
