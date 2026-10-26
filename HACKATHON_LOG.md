# Hackathon log

Meta Global AI Developer Hackathon 2026, Indie Developer track, theme "Build for Your World".
Kickoff 2026-10-26 16:00 UTC. Submission due 2026-11-05 02:00 UTC.
Every line of code in this repository was written inside the hackathon window. Times are UTC.

| Date (UTC) | Phase | Entry |
|---|---|---|
| 2026-10-26 16:45 | 0 | Preflight: kickoff confirmed (`date -u` 16:45), empty repo initialised. Toolchain: git 2.43, Python 3.12 (venv via uv), Node 22, ffmpeg 6.1. Meta Model API key verified via `GET /v1/models` (lists muse-spark-1.3, sam-3.1, muse-voice-transcribe-1.0, muse-wonder-1.0, muse-image-1.0). No Baseten key yet. |
| 2026-10-26 16:55 | 0 | Defaults chosen without asking: FastAPI + SQLite backend, Vite/React/TS frontend, MIT licence, `muse-spark-1.3` as the Standard Muse Spark id (newest listed), local `.env` defaults to `APP_MODE=mock` so development never spends credit by accident. |
