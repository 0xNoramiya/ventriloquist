# Live check

Run 2026-10-26T17:43:07+00:00 with `scripts/live_check.py` against the real Meta Model API (`APP_MODE=live`). Fictional patients and synthetic media only. Total spend for this run: **$0.050**.

## Sessions (simulated patient answers, live context models)

- **daughter**: confirmed ['I want to see my daughter, Aisyah.'] in 5 questions; wall time 4.7 s; model calls: prior_builder 4420 ms, question_proposer 3037 ms
- **spelling**: confirmed ['Kucing'] in 22 questions; wall time 13.5 s; model calls: prior_builder 2960 ms, question_proposer 4444 ms, spelling_completer 1428 ms, spelling_completer 2347 ms, sensitive_classifier 1453 ms, sentence_builder 2227 ms, sensitive_classifier 1223 ms

## Memory curator (Muse Wonder)

- Ibu Sri (fictional): 0 proposed; 
- Pak Hasan (fictional): 1 proposed; The patient's daughter is named Aisyah.
