# Live check

Last run 2026-10-26T18:13:40+00:00 with `scripts/live_check.py` against the real Meta Model API (`APP_MODE=live`). Fictional patients and synthetic media only. Cost of the last run: $0.321; all live-check runs in this data directory: $0.979.

## Model roles

| role | ok | latency (ms) | cost (USD) | output (truncated) |
|---|---|---:|---:|---|
| framing_check | True | 2182 | 0.0018 | `{"face_visible": true, "upper_body_visible": true, "lighting_ok": true, "advice": "Keep the phone steady with the face centered like this."}` |
| scene_reader | True | 2428 | 0.0019 | `{"facts": ["hospital bed with blue blanket and white pillow appears empty", "wooden bedside table with three drawers next to bed", "framed p` |
| prior_builder | True | 4765 | 0.0071 | `{"multipliers": [{"hypothesis_id": "see_person:aisyah", "factor": 4.0, "evidence_ids": ["T1", "S1", "E1"], "reason": "nurse said Aisyah went` |
| question_proposer | True | 3859 | 0.0039 | `{"questions": [{"text_en": "Is it about family?", "text_id": "Apakah ini tentang keluarga, {hon}?", "yes_ids": ["see_person:aisyah", "see_pe` |
| spelling_completer | True | 2335 | 0.0020 | `{"words": [{"word": "KUCING", "p": 0.25}, {"word": "KUAT", "p": 0.2}, {"word": "KURSI", "p": 0.15}, {"word": "KUNCI", "p": 0.1}, {"word": "K` |
| sentence_builder | True | 2035 | 0.0020 | `{"sentences": [{"text_en": "I am thinking about my cat.", "text_id": "Saya memikirkan kucing saya.", "p": 0.5}, {"text_en": "I miss my cat a` |
| sensitive_classifier | True | 1944 | 0.0013 | `{"sensitive": true, "categories": ["refuse_treatment"]}` |

## Calibration on synthetic clips

- Muse Spark description: YES = raises both eyebrows upward briefly (eyebrows); NO = shakes head repeatedly (head); distinct = True
- Leave-one-out accuracy: {'local': 0.7142857142857143, 'tracker': 0.8571428571428571, 'spark': 1.0}; error rates {'a': 0.07692307692307693, 'b': 0.07692307692307693}; ok = True; 52.8 s

## Answer windows (full perception pipeline)

| true | fused answer | confidence | latency (ms) | cost | sources |
|---|---|---:|---:|---:|---|
| yes | yes | 0.924 | 4690 | 0.0302 | tracker: yes 0.957, spark: yes 0.9 |
| no | no | 0.849 | 8419 | 0.024 | tracker: no 0.999, spark: none 0.0 |
| none | none | 0.971 | 5949 | 0.0302 | tracker: none 1.0, spark: none 0.95 |

## Sessions (simulated patient answers, live context models)

- **daughter**: confirmed ['I want to see my daughter, Aisyah.'] in 5 questions; wall time 5.7 s; model calls: prior_builder 5352 ms, question_proposer 4988 ms
- **spelling**: confirmed ['Kucing'] in 24 questions; wall time 13.1 s; model calls: prior_builder 2683 ms, question_proposer 5325 ms, spelling_completer 1382 ms, spelling_completer 1736 ms, sensitive_classifier 1478 ms, sentence_builder 1943 ms, sensitive_classifier 782 ms

## Memory curator (Muse Wonder)

- Ibu Sri (fictional): 0 proposed; 
- Pak Hasan (fictional): 1 proposed; Patient's daughter is named Aisyah.
