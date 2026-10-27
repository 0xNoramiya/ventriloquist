"""HTTP API in mock mode (FastAPI TestClient, temp data dir, no keys)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

PROFILE = {
    "display_name": "Test Patient (fictional)",
    "language": "id",
    "honorific": "Ibu",
    "family": [{"name": "Dewi", "relation": "daughter"}],
    "simulation_consent": True,
}


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = load_settings().model_copy(
        update={
            "app_mode": "mock",
            "data_dir": tmp_path,
            "model_api_key": None,
            "baseten_api_key": None,
            "live_passcode": None,
        }
    )
    with TestClient(create_app(settings)) as c:
        yield c


def synthetic_clip(path: Path, moving: str | None, seconds: float = 4.0, fps: int = 15) -> Path:
    """A grey frame with a white bar; 'up' moves it up twice, 'side' moves it sideways twice."""
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    n = int(seconds * fps)
    for i in range(n):
        img = np.full((120, 160, 3), 90, np.uint8)
        phase = np.sin(2 * np.pi * 2 * i / n) if moving else 0.0
        dy = int(12 * max(phase, 0)) if moving == "up" else 0
        dx = int(14 * phase) if moving == "side" else 0
        cv2.rectangle(img, (55 + dx, 40 - dy), (105 + dx, 52 - dy), (255, 255, 255), -1)
        w.write(img)
    w.release()
    return path


def test_health_and_config(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["mode"] == "mock"
    cfg = client.get("/api/config").json()
    assert {s["id"] for s in cfg["scenarios"]} == {"cold", "daughter", "spelling", "suction"}
    assert len(cfg["taxonomy"]) >= 30


def test_patient_requires_simulation_consent(client):
    r = client.post("/api/patients", json={**PROFILE, "simulation_consent": False})
    assert r.status_code == 400
    r = client.post("/api/patients", json=PROFILE)
    assert r.status_code == 200 and r.json()["id"].startswith("pt_")


def test_live_mode_needs_passcode(client):
    r = client.put("/api/settings", json={"app_mode": "live"})
    assert r.status_code == 403


def test_calibration_skip_then_session_flow(client):
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    cal = client.post(
        f"/api/calibration/{pid}/finalize", json={"skip": True, "hint": "blink"}
    ).json()
    assert cal["skipped"] and cal["description"]["yes"]["body_part"] == "eyes"
    snap = client.post("/api/sessions", json={"patient_id": pid}).json()
    sid = snap["session_id"]
    snap = client.post(f"/api/sessions/{sid}/start").json()
    assert snap["state"] == "ASKING" and snap["prompt"]["text"].startswith("Apakah")
    p = snap["prompt"]["id"]
    assert client.post(f"/api/sessions/{sid}/spoken", json={"prompt_id": p}).json()["ok"]
    assert client.post(f"/api/sessions/{sid}/answer", json={"prompt_id": p, "answer": "no"}).json()[
        "ok"
    ]
    r = client.post(f"/api/sessions/{sid}/event", json={"kind": "suctioned", "label": "Suctioned"})
    assert r.status_code == 200
    r = client.post(
        f"/api/sessions/{sid}/transcript", json={"speaker": "Nurse", "text": "Dewi suka kucing."}
    )
    assert r.status_code == 200
    r = client.post(f"/api/sessions/{sid}/override", json={"action": "pause"}).json()
    assert r["ok"] and r["snapshot"]["state"] == "PAUSED"
    summary = client.post(f"/api/sessions/{sid}/end").json()
    assert "confirmed" in summary
    log = client.get(f"/api/sessions/{sid}/log").json()
    assert log[0]["event"] == "session_start"


def test_calibration_with_clips_local_tracker(client, tmp_path):
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    clips = [
        ("rest", None),
        ("yes", "up"),
        ("yes", "up"),
        ("yes", "up"),
        ("no", "side"),
        ("no", "side"),
        ("no", "side"),
    ]
    for i, (label, motion) in enumerate(clips):
        path = synthetic_clip(
            tmp_path / f"{label}{i}.mp4", motion, seconds=15 if label == "rest" else 4
        )
        with path.open("rb") as f:
            r = client.post(
                f"/api/calibration/{pid}/clip",
                data={"label": label},
                files={"file": (path.name, f, "video/mp4")},
            )
        assert r.status_code == 200
    assert r.json()["counts"] == {"rest": 1, "yes": 3, "no": 3, "emergency": 0}
    cal = client.post(f"/api/calibration/{pid}/finalize", json={"hint": "eyebrows"}).json()
    assert not cal["skipped"]
    assert cal["accuracy"]["local"] >= 0.8
    assert 0.03 <= cal["error_rates"]["a"] <= 0.45
    # clips are deleted after processing (Safety rule 12)
    assert client.get(f"/api/calibration/{pid}").json()["counts"] == {
        "rest": 0,
        "yes": 0,
        "no": 0,
        "emergency": 0,
    }


def test_memory_add_approve_delete(client):
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    r = client.post(
        f"/api/memory/{pid}",
        json={"text": "Daughter Dewi visits after work.", "category": "family"},
    )
    assert r.status_code == 200 and r.json()["source_type"] == "caregiver"
    bad = client.post(f"/api/memory/{pid}", json={"text": "Gives 5 mg morphine at night"})
    assert bad.status_code == 400
    sens = client.post(f"/api/memory/{pid}", json={"text": "Wants to sign the will"})
    assert sens.status_code == 400
    mem = client.get(f"/api/memory/{pid}").json()
    assert len(mem["entries"]) == 1
    entry = mem["entries"][0]["id"]
    assert client.delete(f"/api/memory/{pid}/{entry}").json()["deleted"]


def test_curator_proposes_from_transcript_and_caregiver_approves(client):
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    sid = client.post("/api/sessions", json={"patient_id": pid}).json()["session_id"]
    client.post(
        f"/api/sessions/{sid}/transcript",
        json={"speaker": "Family", "text": "Ibu always listens to the radio at night."},
    )
    res = client.post(f"/api/memory/{pid}/curate").json()
    assert res["proposed"] >= 1
    ops = client.get(f"/api/memory/{pid}").json()["ops"]
    op = ops[0]
    assert op["source_refs"][0]["ref"].startswith("transcript:")
    assert client.post(f"/api/memory/{pid}/ops/{op['id']}/approve").json()["op"] == "add"
    entries = client.get(f"/api/memory/{pid}").json()["entries"]
    assert entries[0]["source_type"] == "transcript" and entries[0]["status"] == "approved"


def test_delete_patient(client):
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    client.post("/api/sessions", json={"patient_id": pid})
    r = client.delete(f"/api/patients/{pid}").json()
    assert r["deleted"] and r["counts"]["patients"] == 1
    assert client.get(f"/api/patients/{pid}").status_code == 404


def test_scenario_endpoint_and_websocket(client):
    snap = client.post("/api/scenarios/daughter", json={}).json()
    sid = snap["session_id"]
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["snapshot"]["state"] == "IDLE"
        ws.send_json({"type": "start"})
        msg = ws.receive_json()
        while msg["snapshot"]["state"] != "ASKING":
            msg = ws.receive_json()
        assert msg["snapshot"]["prompt"]["kind"] == "ask"
        ws.send_json({"type": "ping"})
        while msg.get("type") != "pong":
            msg = ws.receive_json()


@pytest.mark.skipif(
    subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="ffmpeg"
)
@pytest.mark.parametrize("spoken_first", [True, False])
def test_answer_clip_through_pipeline(client, tmp_path, spoken_first):
    """The phone starts recording when it finishes speaking, so the clip can reach the server
    before the "spoken" message does."""
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    for i, (label, motion) in enumerate(
        [("rest", None), ("yes", "up"), ("yes", "up"), ("no", "side"), ("no", "side")]
    ):
        path = synthetic_clip(tmp_path / f"c{i}.mp4", motion, seconds=15 if label == "rest" else 4)
        with path.open("rb") as f:
            client.post(
                f"/api/calibration/{pid}/clip",
                data={"label": label},
                files={"file": (path.name, f, "video/mp4")},
            )
    client.post(f"/api/calibration/{pid}/finalize", json={})
    sid = client.post("/api/sessions", json={"patient_id": pid}).json()["session_id"]
    snap = client.post(f"/api/sessions/{sid}/start").json()
    p = snap["prompt"]["id"]
    if spoken_first:
        client.post(f"/api/sessions/{sid}/spoken", json={"prompt_id": p})
    clip = synthetic_clip(tmp_path / "answer.mp4", "up")
    with clip.open("rb") as f:
        r = client.post(
            f"/api/sessions/{sid}/clip",
            data={"prompt_id": p},
            files={"file": ("a.mp4", f, "video/mp4")},
        )
    body = r.json()
    assert body["accepted"] and body["observation"]["answer"] in ("yes", "unclear")
    assert "local" in body["observation"]["sources"]["sources"]
    # a late "spoken" for the answered prompt changes nothing
    before = client.get(f"/api/sessions/{sid}").json()
    client.post(f"/api/sessions/{sid}/spoken", json={"prompt_id": p})
    after = client.get(f"/api/sessions/{sid}").json()
    assert (after["state"], after["prompt"]["id"]) == (before["state"], before["prompt"]["id"])


def test_idle_clip_ignored_after_session_end(client, tmp_path):
    pid = client.post("/api/patients", json=PROFILE).json()["id"]
    sid = client.post("/api/sessions", json={"patient_id": pid}).json()["session_id"]
    client.post(f"/api/sessions/{sid}/end")
    clip = synthetic_clip(tmp_path / "idle.mp4", "up")
    with clip.open("rb") as f:
        r = client.post(f"/api/sessions/{sid}/idle", files={"file": ("idle.mp4", f, "video/mp4")})
    assert r.json() == {"answer": "none", "ignored": "session ended"}


def test_acknowledging_a_message(client):
    started = client.post("/api/scenarios/cold", json={"simulated": True, "noise": 0.0}).json()
    sid = started["session_id"]
    client.post(f"/api/sessions/{sid}/start")
    deadline = time.monotonic() + 15
    snap = client.get(f"/api/sessions/{sid}").json()
    while snap["state"] != "DONE" and time.monotonic() < deadline:
        time.sleep(0.05)
        snap = client.get(f"/api/sessions/{sid}").json()
    assert snap["state"] == "DONE"
    pending = snap["pending_ack"]
    assert [m["text_en"] for m in pending] == ["I'm cold."]
    assert not client.post(f"/api/sessions/{sid}/messages/nope/ack").json()["ok"]
    r = client.post(f"/api/sessions/{sid}/messages/{pending[0]['id']}/ack").json()
    assert r["ok"] and r["snapshot"]["pending_ack"] == []
    assert r["snapshot"]["messages"][-1]["acknowledged_at"]
