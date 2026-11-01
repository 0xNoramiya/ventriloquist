# Evaluation

Every number published in this repository is produced by one of the three harnesses here. Each one
writes a document under `docs/`, so a claim in the README can always be traced to the command that
made it.

| Harness | Produces | Costs | Run it |
|---|---|---|---|
| `sim/` | [`docs/EVAL.md`](../docs/EVAL.md), `docs/sim_results.json`, the charts in `docs/img/` | nothing: simulated patients, no model calls | `make sim` |
| `detector.py` | `docs/DETECTOR_EVAL_*.md`, `data/labeled/results.json` | $0.90 for the three live runs behind the current report | `make eval-detector` |
| `live_check.py` | [`docs/LIVE_CHECK.md`](../docs/LIVE_CHECK.md), `data/live_check/live_check.json` | $0.17 for the last run, under $0.50 typically | see below |

Nothing here needs an API key except where a cost is listed.

## The engine simulation

```bash
make sim                                   # 2,000 seeded trials per cell, about 3 minutes
python -m eval.sim.learning_curve          # 300 simulated patients over 10 daily sessions
```

Five question-selection strategies under identical simulated patients, with answers flipped at a
given rate. It writes `docs/EVAL.md` whole, charts included, so a hand edit there is lost on the
next run. The seed is fixed: the same command reproduces the same numbers.

**It is a simulation, not clinical evidence.** The simulated patient answers from a known message
with a known error rate, which is the one thing a real patient will not do.

## The detector

```bash
make eval-detector                                     # mock mode, free, checks the plumbing
PYTHONPATH=backend:. backend/.venv/bin/python eval/detector.py \
  --mode live --data data/labeled --name REAL --runs 3 --verbose
```

Calibrates on `data/labeled/calibration/`, then runs every labelled clip through the whole
perception pipeline and reports a confusion matrix per source (SAM tracker, on-device optical flow,
blind Muse Spark judge) and fused, with latency. `--mode privacy` runs the same thing on Muse Spark
Open. `--runs N` scores every clip N times on one calibration, because the judge is a language model
and one pass over a small set reports luck as much as accuracy.

Clips are never committed. What exists today is generated video
([`docs/DETECTOR_DATA_GENERATED.md`](../docs/DETECTOR_DATA_GENERATED.md)) and one unscored run on a
real face; a labelled set from a consenting adult takes twenty minutes
([`docs/RECORD_CLIPS.md`](../docs/RECORD_CLIPS.md)).

## The live check

```bash
PYTHONPATH=backend:. backend/.venv/bin/python eval/live_check.py [--part roles]
```

Calls every Meta model this project uses, against the real API, on synthetic media, and writes down
what each one returned: the request, the response, the latency and the cost. It is the answer to
"did these models really do this", and it is the only document here that is not a score.
