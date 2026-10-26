# Ventriloquist task list

Status: `[x]` done, `[~]` in progress, `[ ]` to do. Updated as work proceeds.

## Phase 0: Scaffold and verification (2026-10-26)
- [x] Preflight: kickoff time check, toolchain (git, Python 3.12, Node 22, ffmpeg), Meta key verified with `GET /v1/models`
- [x] Repo layout, `.gitignore`, `.env.example`, `config.yaml`, MIT `LICENSE`, `Makefile`
- [~] Read Meta, Baseten and Modal docs; `docs/API_NOTES.md`
- [~] Probes `scripts/probe_*.py` (skip gracefully without keys)
- [~] Verify problem-statement sources (`docs/SOURCES.md`)
- [ ] README skeleton, `HACKATHON_LOG.md`, docs skeletons
- [ ] DoD: `make setup && make test` passes; `make dev` serves backend and frontend

## Phase 1: Engine (Section 8)
- [ ] Types, taxonomy v1 (EN/ID), attribute partitions
- [ ] Priors with bounded context and personal multipliers (Safety rule 8)
- [ ] Closed-form EIG under a noisy channel, question selection
- [ ] Bayesian update with per-observation error, UNCLEAR handling
- [ ] Policy: confirm gating, fatigue, spelling offer, caps; explicit state machine
- [ ] Spelling mode: probability-balanced letter groups, checkpoints, completions
- [ ] Personal learning (Dirichlet, 3-day half-life)
- [ ] Engine tests (all of 8.10) incl. hypothesis property tests
- [ ] Simulation harness + first `docs/EVAL.md`
- [ ] DoD: at eps=0.10 with strong context, EIG+context beats the fixed-order board

## Phase 2: Backend
- [ ] FastAPI REST + WebSocket, session orchestrator, SQLite store
- [ ] Mock providers (VisionLanguage, Tracker, Transcriber, MemoryModel)
- [ ] Safety: sensitive detector, advice validator, policy checks
- [ ] Session JSONL logs, budget guard, cost meter
- [ ] Scenario fixtures: daughter, suction, cold, spelling
- [ ] DoD: `make demo-mock` runs a full session from the CLI and writes a JSONL log

## Phase 3: Frontend
- [ ] Vite + React + TS strict + Zustand + Tailwind + i18n (en, id), HTTPS dev server, proxy
- [ ] Routes: `/`, `/setup`, `/calibrate`, `/patient/:sid`, `/caregiver/:sid`, `/memory/:pid`, `/eval`, `/settings`
- [ ] Mock keyboard answers, speech, sync, emergency, spelling, overrides
- [ ] DoD: daughter scenario end to end in mock mode; Lighthouse a11y >= 90 on patient view

## Phase 4: Live adapters
- [ ] Meta Responses API client; Spark roles (calibration, scene, priors, questions, judge, completer)
- [ ] SAM 3.1 tracker, Voice Transcribe, Wonder curator/selector, Baseten client
- [ ] Feature flags, timeouts, retries, cost logging; contract tests against recorded fixtures
- [ ] DoD: probes pass with keys; live session works (caregiver override fallback)

## Phase 5: Perception tuning (needs recorded clips)
- [ ] `scripts/eval_detector.py` (confusion matrices per source + fused, latency)
- [ ] Record labeled clips (Rifqi + consenting actors) into `data/labeled/` — needs a human
- [ ] Tune thresholds, latency work, SAM overlay rendering

## Phase 6: Memory and privacy
- [ ] Live memory curator + learning curve
- [ ] Privacy mode end to end on Baseten (needs `BASETEN_API_KEY`)
- [ ] Optional: SAM 3.1 on Modal; Muse Image pictograms for intents

## Phase 7: Polish and submission
- [ ] UI polish, final README with eval charts and Mermaid diagram, SAFETY.md
- [ ] Hosted simulation-only demo (no camera, no keys)
- [ ] `docs/DEMO_SCRIPT.md`, X post draft; demo rehearsal (video recorded last)
- [ ] Feature freeze 2026-11-03 12:00 UTC; submission due 2026-11-05 02:00 UTC
