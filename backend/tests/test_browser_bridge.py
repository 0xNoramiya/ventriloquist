"""The in-browser demo bridge drives a real mock session through JSON messages only."""

from __future__ import annotations

import asyncio
import json
import sys

from app.browser import BrowserDemo


async def test_bridge_runs_daughter_scenario(tmp_path):
    pushed: list[dict] = []
    demo = BrowserDemo(lambda m: pushed.append(json.loads(m)), str(tmp_path))
    config = json.loads(demo.config())
    assert config["browser_demo"] and {s["id"] for s in config["scenarios"]} >= {
        "daughter",
        "spelling",
    }
    snap = json.loads(await demo.scenario("daughter"))
    assert snap["state"] == "IDLE"
    await demo.handle(json.dumps({"type": "start"}))
    for _ in range(30):
        view = pushed[-1]["snapshot"]
        p = view["prompt"]
        if view["state"] == "DONE":
            break
        if view["state"] in ("ASKING", "CONFIRMING", "POST_CHECK", "SPEAKING"):
            await demo.handle(json.dumps({"type": "spoken", "prompt_id": p["id"]}))
        elif view["state"] == "LISTENING":
            yes = p["kind"] == "post_check" or "see_person:aisyah" in p["question"]["yes_ids"]
            await demo.handle(
                json.dumps(
                    {"type": "answer", "prompt_id": p["id"], "answer": "yes" if yes else "no"}
                )
            )
        await asyncio.sleep(0)
    final = pushed[-1]["snapshot"]
    assert final["state"] == "DONE"
    assert final["messages"][0]["text_en"] == "I want to see my daughter, Aisyah."


def test_bridge_imports_without_opencv_httpx_or_fastapi():
    """Pyodide has no OpenCV build we want to download and no use for the web server."""
    import subprocess

    code = "import sys, app.browser; print(sorted(m for m in ('cv2', 'httpx', 'fastapi') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


async def test_simulated_demo_patients_do_not_share_a_seed(tmp_path):
    # With one fixed seed every hosted demo flipped the same two answers and the daughter
    # scenario never reached Aisyah.
    demo = BrowserDemo(lambda m: None, str(tmp_path))
    draws = set()
    for _ in range(3):
        await demo.scenario("daughter", simulated=True)
        draws.add(demo.session.sim.rng.random())
    assert len(draws) == 3
