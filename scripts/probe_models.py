"""Probe: GET /v1/models, GET /v1/models/{id} for every configured Meta model, GET /v1/status.

Free (no inference). Checks that every model id in config.yaml is enabled for this team.
Run: backend/.venv/bin/python scripts/probe_models.py
"""

from __future__ import annotations

import httpx
from _probe_common import META_BASE_URL, MODELS, ProbeRun, Timer, key_tree, require_env


def main() -> None:
    key = require_env("MODEL_API_KEY")
    run = ProbeRun("probe_models")
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(base_url=META_BASE_URL, headers=headers, timeout=30) as http:
        with Timer() as t:
            r = http.get("/models")
        run.record("GET /models", "-", t.s, status=f"HTTP {r.status_code}")
        if r.status_code != 200:
            run.note(f"list models failed: {r.text[:300]}")
            run.finish()
            return
        listing = r.json()
        print(key_tree(listing, max_items=20))
        run.save_fixture("models_list", listing)
        ids = [m["id"] for m in listing.get("data", [])]
        run.note(f"GET /v1/models ids: {', '.join(ids)}")

        meta_models = {k: v for k, v in MODELS.items() if k not in ("spark_open", "sam_open")}
        for role, model_id in meta_models.items():
            with Timer() as t:
                r = http.get(f"/models/{model_id}")
            ok = r.status_code == 200
            run.record(f"GET /models/{model_id}", model_id, t.s, status=f"HTTP {r.status_code}",
                       extra="" if ok else r.text[:200])
            if ok and role == "spark":
                run.save_fixture("models_retrieve_spark", r.json())
            if model_id not in ids:
                run.note(f"config models.{role}={model_id} is NOT in /v1/models")

    with Timer() as t:
        r = httpx.get(f"{META_BASE_URL}/status", timeout=30)  # unauthenticated health endpoint
    run.record("GET /status (no auth)", "-", t.s, status=f"HTTP {r.status_code}")
    if r.headers.get("content-type", "").startswith("application/json"):
        print(key_tree(r.json()))
        run.save_fixture("status", r.json())
    run.finish()


if __name__ == "__main__":
    main()
