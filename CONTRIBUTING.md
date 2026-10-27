# Contributing

Issues and pull requests are welcome.

## Setup

```bash
make setup   # backend venv (uv) and frontend packages
make test    # backend tests, frontend typecheck and tests
make lint    # ruff and eslint, as CI runs them
```

## Ground rules

- Everything must keep working in mock mode, with no API keys and no network. Tests never call a
  live API; recorded responses in `backend/tests/fixtures/` stand in for it.
- No real patient data anywhere: fictional profiles, synthetic media, or recordings of consenting
  actors kept outside the repository.
- The engine must never propose, rank or ask about sensitive topics. Read
  [`docs/SAFETY.md`](docs/SAFETY.md) before touching the engine, prompts or safety code, and keep
  each rule covered by a test.
- Model request shapes must match the provider's documentation; record what you verified in
  [`docs/API_NOTES.md`](docs/API_NOTES.md).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `docs:`, ...).
