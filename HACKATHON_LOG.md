# Hackathon log

Meta Global AI Developer Hackathon 2026, Indie Developer track, theme "Build for Your World".
Kickoff 2026-10-26 16:00 UTC. Submission due 2026-11-05 02:00 UTC.
Every line of code in this repository was written inside the hackathon window. Times are UTC.

| Date (UTC) | Phase | Entry |
|---|---|---|
| 2026-10-26 16:45 | 0 | Preflight: kickoff confirmed (`date -u` 16:45), empty repo initialised. Toolchain: git 2.43, Python 3.12 (venv via uv), Node 22, ffmpeg 6.1. Meta Model API key verified via `GET /v1/models` (lists muse-spark-1.3, sam-3.1, muse-voice-transcribe-1.0, muse-wonder-1.0, muse-image-1.0). No Baseten key yet. |
| 2026-10-26 16:55 | 0 | Defaults chosen without asking: FastAPI + SQLite backend, Vite/React/TS frontend, MIT licence, `muse-spark-1.3` as the Standard Muse Spark id (newest listed), local `.env` defaults to `APP_MODE=mock` so development never spends credit by accident. |
| 2026-10-26 17:04 | 1 | Engine: taxonomy v1 (EN/ID), bounded priors (bisection keeps cap, floor and "other" minimum simultaneously), closed-form EIG, per-observation Bayes, confirm gating, fatigue caps, spelling with probability-balanced contiguous letter groups, personal Dirichlet base rates, explicit state machine. Property tests with hypothesis. Added body sub-partitions after noise-free tests showed a linear scan for some messages. |
| 2026-10-26 17:08 | 0 | Docs read and every Meta endpoint probed with synthetic media (about $0.08): `docs/API_NOTES.md`, probes in `scripts/`, 31 recorded responses as contract fixtures. Problem-statement sources checked (`docs/SOURCES.md`); letter statistics built from public-domain text and Indonesian statutes. |
| 2026-10-26 17:12 | 1 | Simulation: 2,000 trials per cell. At eps 0.10 with strong context, EIG + context 4.89 mean questions vs 6.41 for a fixed-order board (Phase 1 DoD met). |
| 2026-10-26 17:34 | 2 | Backend: FastAPI + WebSocket, session orchestrator, mock providers, scenario fixtures (daughter, suction, cold, spelling), JSONL logs, budget guard, memory curator with provenance checks, CLI demo (`make demo-mock`). Session-level safety tests. |
| 2026-10-26 17:44 | 4 | Live adapters (Responses API with strict JSON schema and `store: false`, SAM 3.1 wire format, Voice Transcribe with language bias, Baseten with slug fallback) plus contract tests. `scripts/live_check.py` against the real API found three issues the docs don't mention (max 5 videos per Spark request, strict schema rejects free-form maps, reasoning budgets) and a runaway spelling loop; all fixed, loop capped as a cost guard. Live spend so far about $0.85. |
| 2026-10-26 17:48 | 7 | Docs: README, SAFETY, ARCHITECTURE, I18N review list, demo script with X post draft, detector evaluation script (synthetic run only; real clips still to record). Frontend being built in parallel. |
