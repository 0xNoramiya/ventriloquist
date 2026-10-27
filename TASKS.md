# Ventriloquist task list

Status: `[x]` done, `[~]` in progress, `[ ]` to do. Updated as work proceeds.

## Phase 0: Scaffold and verification (2026-10-26)
- [x] Preflight: kickoff time check, toolchain (git, Python 3.12, Node 22, ffmpeg), Meta key verified with `GET /v1/models`
- [x] Repo layout, `.gitignore`, `.env.example`, `config.yaml`, MIT `LICENSE`, `Makefile`
- [x] Read Meta, Baseten and Modal docs; `docs/API_NOTES.md`
- [x] Probes `scripts/probe_*.py` (skip gracefully without keys)
- [x] Verify problem-statement sources (`docs/SOURCES.md`)
- [x] README skeleton, `HACKATHON_LOG.md`, docs skeletons
- [x] DoD: `make setup && make test` passes; `make dev` serves backend and frontend

## Phase 1: Engine (Section 8)
- [x] Types, taxonomy v1 (EN/ID), attribute partitions
- [x] Priors with bounded context and personal multipliers (Safety rule 8)
- [x] Closed-form EIG under a noisy channel, question selection
- [x] Bayesian update with per-observation error, UNCLEAR handling
- [x] Policy: confirm gating, fatigue, spelling offer, caps; explicit state machine
- [x] Spelling mode: probability-balanced letter groups, checkpoints, completions
- [x] Personal learning (Dirichlet, 3-day half-life)
- [x] Engine tests (all of 8.10) incl. hypothesis property tests
- [x] Simulation harness + first `docs/EVAL.md`
- [x] DoD: at eps=0.10 with strong context, EIG+context beats the fixed-order board

## Phase 2: Backend
- [x] FastAPI REST + WebSocket, session orchestrator, SQLite store
- [x] Mock providers (VisionLanguage, Tracker, Transcriber, MemoryModel)
- [x] Safety: sensitive detector, advice validator, policy checks
- [x] Session JSONL logs, budget guard, cost meter
- [x] Scenario fixtures: daughter, suction, cold, spelling
- [x] DoD: `make demo-mock` runs a full session from the CLI and writes a JSONL log

## Phase 3: Frontend
- [x] Vite + React + TS strict + Zustand + Tailwind + i18n (en, id), HTTPS dev server, proxy
- [x] Routes: `/`, `/setup`, `/calibrate`, `/patient/:sid`, `/caregiver/:sid`, `/memory/:pid`, `/eval`, `/settings` (+ `/demo/:sid` for the hosted demo)
- [x] Mock keyboard answers, speech, sync, emergency, spelling, overrides
- [x] DoD: daughter scenario end to end in mock mode; Lighthouse a11y 100 on patient view (phone over LAN still to try on real hardware)

## Phase 4: Live adapters
- [x] Meta Responses API client; Spark roles (calibration, scene, priors, questions, judge, completer)
- [x] SAM 3.1 tracker, Voice Transcribe, Wonder curator/selector, Baseten client
- [x] Feature flags, timeouts, retries, cost logging; contract tests against recorded fixtures
- [x] DoD: probes pass with keys; live session works (caregiver override fallback)

## Phase 5: Perception tuning (needs recorded clips)
- [x] `scripts/eval_detector.py` (confusion matrices per source + fused, latency)
- [ ] Record labeled clips (Rifqi + consenting actors) into `data/labeled/`; deferred, Rifqi judged the synthetic results enough for now
- [x] Tune thresholds, latency work, SAM overlay rendering (DTW temperature fitted on calibration LOO; 8 fps windows; early decision needs a clear YES/NO with a template margin; recording starts when the phone finishes speaking)

## Phase 6: Memory and privacy
- [x] Live memory curator + learning curve (Wonder curator verified live; caregiver approval UI in frontend)
- [~] Privacy mode end to end on Baseten (adapter + contract tests done; live run needs `BASETEN_API_KEY`)
- [x] Muse Image pictograms for all 34 messages
- [x] On-premises Muse Glimmer tier (text roles), Modal as alternative Spark Open host
- [ ] Optional: SAM 3.1 open weights self-hosted on Modal (client ready; deployment needs an account)

## Phase 7: Polish and submission
- [x] README with eval charts, screenshots and Mermaid diagrams; SAFETY.md, ARCHITECTURE.md, API_NOTES.md, LIVE_CHECK.md
- [ ] UI polish after a session on real phones (Rifqi)
- [x] Hosted simulation-only demo (no camera, no keys): real engine in the browser via Pyodide, live at https://0xnoramiya.github.io/ventriloquist/ and verified there with Playwright
- [ ] Host the full app on fly.io (later, Rifqi's call)
- [x] `docs/DEMO_SCRIPT.md` and X post draft
- [ ] Demo rehearsal and video (recorded last, with a consenting actor)
- [ ] Feature freeze 2026-11-03 12:00 UTC; submission due 2026-11-05 02:00 UTC

## Needs Rifqi
- [x] Public repo https://github.com/0xNoramiya/ventriloquist, Pages enabled, release v0.1.0 (2026-10-27)
- [ ] `BASETEN_API_KEY` (or `MODAL_SPARK_URL`) to run privacy mode live and get the open-weight bonus verified
- [~] Review `docs/I18N_REVIEW.md` and the sensitive keyword lists (first pass done 2026-10-27; the toilet message and open questions still need a native reader)
- [ ] Record labelled clips with consenting volunteers into `data/labeled/`, run `scripts/eval_detector.py --mode live`
- [ ] Try a full session on a phone over the LAN (`make dev`, open the QR code)
- [ ] Test Indonesian Voice Transcribe on real speech (and Banjar if possible)
