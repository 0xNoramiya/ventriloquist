# Ventriloquist developer commands. Everything works in mock mode without API keys.
PY := backend/.venv/bin/python
export PYTHONPATH := $(CURDIR)/backend:$(CURDIR)

.PHONY: setup dev backend frontend frontend-local test lint format sim probe demo-mock eval-detector letter-stats clean

setup:
	cd backend && uv venv --python 3.12 -q --allow-existing .venv && uv sync -q
	cd frontend && npm install --no-fund --no-audit
	@test -f .env || cp .env.example .env
	@mkdir -p data

dev:
	@echo "Laptop: http://localhost:5174  Phone: https://<LAN-IP>:5173  Backend: http://127.0.0.1:8000"
	@trap 'kill 0' INT TERM EXIT; \
	  $(MAKE) --no-print-directory backend & \
	  $(MAKE) --no-print-directory frontend & \
	  $(MAKE) --no-print-directory frontend-local & \
	  wait

backend:
	cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app

frontend:
	cd frontend && npm run dev

# Plain HTTP on 127.0.0.1 only: no certificate warning on the laptop, camera still allowed.
frontend-local:
	cd frontend && VENTRILOQUIST_HTTP=1 npx vite

test:
	cd backend && .venv/bin/pytest
	cd frontend && npm run typecheck && npm test --silent

lint:
	cd backend && .venv/bin/ruff check app tests ../sim ../scripts && .venv/bin/ruff format --check app tests ../sim ../scripts
	cd frontend && npm run lint

format:
	cd backend && .venv/bin/ruff check --fix app tests ../sim ../scripts && .venv/bin/ruff format app tests ../sim ../scripts

sim:
	$(PY) -m sim.simulate

probe:
	$(PY) scripts/probe_all.py

demo-mock:
	$(PY) -m app.cli demo --scenario daughter

eval-detector:
	$(PY) scripts/eval_detector.py

letter-stats:
	$(PY) scripts/build_letter_stats.py

clean:
	rm -rf backend/.pytest_cache backend/.ruff_cache frontend/dist
