"""HTTP API and WebSocket (brief Section 12). The backend owns all state and all model calls;
the browser never sees an API key."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.config import ROOT, Settings, get_settings
from app.engine.taxonomy import load_taxonomy
from app.memory import curator
from app.perception import calibration as calib
from app.providers.registry import Mode, ProviderHub
from app.relay.channels import WhatsAppChannel, parse_webhook, verify_signature
from app.roles import Roles
from app.scenarios import load as load_scenario
from app.scenarios import names as scenario_names
from app.schemas import (
    AnswerCreate,
    EventCreate,
    OverrideCreate,
    PatientProfile,
    SessionCreate,
    SettingsUpdate,
    TranscriptLine,
)
from app.sessions.manager import SessionManager
from app.sessions.session import AppContext, Session
from app.storage import Store, new_id

log = logging.getLogger("ventriloquist")
MAX_UPLOAD = 60 * 1024 * 1024
CAL_LABELS = ("rest", "yes", "no", "emergency")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = Store(settings.data_dir)
    hub = ProviderHub(settings, store)
    relay_channel = (
        WhatsAppChannel(settings, settings.whatsapp_token, settings.whatsapp_phone_number_id)
        if settings.whatsapp_token and settings.whatsapp_phone_number_id
        else None
    )
    ctx = AppContext(settings, store, hub, Roles(hub, settings), relay_channel)
    manager = SessionManager(ctx)

    @asynccontextmanager
    async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
        yield
        await manager.shutdown()

    app = FastAPI(title="Ventriloquist", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.raw["app"].get("cors_origins", []),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.ctx = ctx
    app.state.manager = manager

    # ------------------------------------------------------------------ helpers
    def patient_or_404(pid: str) -> dict[str, Any]:
        p = store.get_patient(pid)
        if not p:
            raise HTTPException(404, "patient not found")
        return p

    def session_or_404(sid: str) -> Session:
        s = manager.get(sid)
        if not s:
            raise HTTPException(404, "session not found")
        return s

    def check_passcode(passcode: str | None, switching: bool = False) -> None:
        """Live and privacy mode spend credit and send media out, so the UI needs a passcode.
        Without LIVE_PASSCODE only the operator can choose live mode (APP_MODE=live in .env)."""
        expected = settings.live_passcode
        if not expected:
            if switching or settings.app_mode != "live":
                raise HTTPException(
                    403, "Set LIVE_PASSCODE in .env to enable live or privacy mode from the UI."
                )
            return
        if not secrets.compare_digest(passcode or "", expected):
            raise HTTPException(403, "live mode needs the passcode")

    def unlocked(request: Request, passcode: str | None = None) -> bool:
        """With LIVE_PASSCODE set (a public deployment), a browser that entered the passcode sends
        it in X-Live-Passcode. Without one, the operator's .env decides."""
        expected = settings.live_passcode
        if not expected:
            return True
        given = passcode or request.headers.get("x-live-passcode") or ""
        return secrets.compare_digest(given, expected)

    def mode_for(
        request: Request, privacy: bool | None = None, passcode: str | None = None
    ) -> Mode:
        """Live and privacy mode spend credit and send media out. On a public deployment only a
        browser holding the passcode gets them; everyone else quietly gets mock mode."""
        mode = hub.requested_mode(privacy)
        if mode != Mode.MOCK and settings.live_passcode and not unlocked(request, passcode):
            return Mode.MOCK
        return mode

    async def save_upload(upload: UploadFile, dest_dir: Path, stem: str) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename or "").suffix or {
            "video/webm": ".webm",
            "video/mp4": ".mp4",
            "audio/webm": ".webm",
            "image/jpeg": ".jpg",
            "image/png": ".png",
        }.get(upload.content_type or "", ".bin")
        path = dest_dir / f"{stem}{suffix}"
        size = 0
        with path.open("wb") as f:
            while chunk := await upload.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    path.unlink(missing_ok=True)
                    raise HTTPException(413, "upload too large")
                f.write(chunk)
        return path

    # ------------------------------------------------------------------- meta
    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "mode": hub.app_mode(),
            "privacy_default": hub.privacy_default(),
            "keys": {
                "meta": bool(settings.model_api_key),
                "baseten": bool(settings.baseten_api_key),
                "modal_sam": bool(settings.modal_sam_url),
                "whatsapp": relay_channel is not None,
            },
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "budget": hub.cost.status().to_dict(),
            "live": hub.resolve(Mode.LIVE).to_dict(),
            "privacy": hub.resolve(Mode.PRIVACY).to_dict(),
        }

    @app.get("/api/config")
    async def public_config(request: Request) -> dict[str, Any]:
        e, p = settings.engine, settings.perception
        tax = load_taxonomy()
        return {
            "engine": {
                "tau_confirm": store.kv_get("tau_confirm", e.tau_confirm),
                "finalize_threshold": e.finalize_threshold,
                "max_questions": e.max_questions,
            },
            "perception": {
                "window_s": store.kv_get("window_s", p.window_s),
                "window_delay_ms": p.window_delay_ms,
                "width": p.width,
                "height": p.height,
                "fps": p.fps,
                "idle_watch_interval_s": p.idle_watch_interval_s,
            },
            "speech": settings.raw.get("speech", {}),
            "flags": hub.flags(),
            # the mode this browser gets (mock on a public deployment without the passcode)
            "mode": "mock" if mode_for(request, False) == Mode.MOCK else hub.app_mode(),
            "privacy_default": hub.privacy_default(),
            "unlocked": bool(settings.live_passcode) and unlocked(request),
            "language": store.kv_get("language", settings.raw["app"]["default_language"]),
            "keep_clips_for_evaluation": bool(
                store.kv_get(
                    "keep_clips_for_evaluation",
                    settings.raw["app"].get("keep_clips_for_evaluation"),
                )
            ),
            "budget": hub.cost.status().to_dict(),
            "passcode_required": bool(settings.live_passcode),
            "scenarios": [
                {"id": n, "title": load_scenario(n).get("title", "")} for n in scenario_names()
            ],
            "taxonomy": [
                {"id": h["id"], "en": h["en"], "id_text": h["id_text"], "domain": h["domain"]}
                for h in tax["hypotheses"]
            ],
            "event_kinds": [
                "suctioned",
                "repositioned",
                "mouth_care",
                "visitor_arrived",
                "visitor_left",
                "family_called",
                "medication_given",
                "procedure_done",
                "note",
            ],
            "models": settings.models,
        }

    @app.get("/api/settings")
    async def get_runtime_settings(request: Request) -> dict[str, Any]:
        return await public_config(request)

    @app.post("/api/unlock")
    async def unlock(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        """Check a passcode before the browser keeps it for X-Live-Passcode."""
        ok = bool(settings.live_passcode) and unlocked(request, str(body.get("passcode") or ""))
        if not ok:
            await asyncio.sleep(1.0)  # slows guessing
        return {"ok": ok}

    @app.put("/api/settings")
    async def update_settings(request: Request, body: SettingsUpdate) -> dict[str, Any]:
        if settings.live_passcode:
            # public deployment: nobody without the passcode changes modes, flags or the budget
            if not unlocked(request, body.passcode):
                raise HTTPException(403, "Settings need the passcode")
        elif body.app_mode == "live" or body.privacy_mode:
            check_passcode(body.passcode, switching=True)
        mapping = {
            "app_mode": body.app_mode,
            "privacy_mode": body.privacy_mode,
            "language": body.language,
            "window_s": body.window_s,
            "tau_confirm": body.tau_confirm,
            "budget_max_usd": body.budget_max_usd,
            "keep_clips_for_evaluation": body.keep_clips_for_evaluation,
        }
        for k, v in mapping.items():
            if v is not None:
                store.kv_set(k, v)
        for flag in ("use_sam", "use_spark_judge", "use_transcribe", "use_wonder", "idle_watch"):
            v = getattr(body, flag)
            if v is not None:
                store.kv_set(f"flag:{flag}", v)
        return await public_config(request)

    @app.get("/api/budget")
    async def budget() -> dict[str, Any]:
        return {**hub.cost.status().to_dict(), "by_model": store.spend_by_model()}

    # --------------------------------------------------------------- patients
    @app.post("/api/patients")
    async def create_patient(profile: PatientProfile) -> dict[str, Any]:
        if not profile.simulation_consent:
            raise HTTPException(
                400,
                "Development and demos use consenting participants only: tick the simulation box.",
            )
        pid = store.create_patient(profile.model_dump())
        return patient_or_404(pid)

    @app.get("/api/patients")
    async def list_patients() -> list[dict[str, Any]]:
        return store.list_patients()

    @app.get("/api/patients/{pid}")
    async def get_patient(pid: str) -> dict[str, Any]:
        p = patient_or_404(pid)
        cal = store.get_calibration(pid)
        return {
            **p,
            "calibrated": bool(cal and not cal.get("skipped")),
            "calibration": _cal_summary(cal),
            "sessions": store.list_sessions(pid),
        }

    @app.put("/api/patients/{pid}")
    async def update_patient(pid: str, profile: PatientProfile) -> dict[str, Any]:
        patient_or_404(pid)
        store.update_patient(pid, profile.model_dump())
        return patient_or_404(pid)

    @app.delete("/api/patients/{pid}")
    async def delete_patient(pid: str) -> dict[str, Any]:
        patient_or_404(pid)
        active = manager.active_for(pid)
        if active:
            await active.end()
            manager.sessions.pop(active.id, None)
        return {"deleted": True, "counts": store.delete_patient(pid)}

    # ------------------------------------------------------------- calibration
    @app.post("/api/calibration/{pid}/clip")
    async def calibration_clip(
        pid: str, label: str = Form(...), file: UploadFile = File(...)
    ) -> dict[str, Any]:
        patient_or_404(pid)
        if label not in CAL_LABELS:
            raise HTTPException(400, f"label must be one of {CAL_LABELS}")
        d = store.media_dir("calibration", pid, "raw")
        n = len(list(d.glob(f"{label}_*")))
        await save_upload(file, d, f"{label}_{n}")
        return {"label": label, "index": n, "counts": _cal_counts(d)}

    @app.post("/api/calibration/{pid}/framing")
    async def calibration_framing(
        request: Request, pid: str, file: UploadFile = File(...), privacy: bool = Form(False)
    ) -> dict[str, Any]:
        patient_or_404(pid)
        path = await save_upload(file, store.media_dir("calibration", pid), "framing")
        res = await ctx.roles.framing_check(mode_for(request, privacy), path)
        path.unlink(missing_ok=True)
        return {**res.data.model_dump(), "meta": res.meta.to_dict()}

    @app.delete("/api/calibration/{pid}/clips")
    async def calibration_reset(pid: str) -> dict[str, Any]:
        shutil.rmtree(store.media_dir("calibration", pid, "raw"), ignore_errors=True)
        return {"counts": {}}

    @app.post("/api/calibration/{pid}/finalize")
    async def calibration_finalize(
        request: Request, pid: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        patient_or_404(pid)
        body = body or {}
        mode = mode_for(request, bool(body.get("privacy")))
        if body.get("skip"):
            data = calib.default_calibration(str(mode), hint=body.get("hint"))
            store.save_calibration(pid, data)
            return _cal_summary(data) or {}
        raw = store.media_dir("calibration", pid, "raw")
        clips: dict[str, list[Path]] = {}
        for label in CAL_LABELS:
            clips[label] = sorted(raw.glob(f"{label}_*"))
        if len(clips["yes"]) < 2 or len(clips["no"]) < 2 or not clips["rest"]:
            raise HTTPException(400, "Need a rest clip and at least two YES and two NO clips.")
        data = await calib.finalize(
            pid,
            clips,
            store.media_dir("calibration", pid, "work"),
            hub=hub,
            roles=ctx.roles,
            settings=settings,
            mode=mode,
            hint=body.get("hint"),
            description_override=body.get("description"),
        )
        store.save_calibration(pid, data)
        if not store.kv_get(
            "keep_clips_for_evaluation", settings.raw["app"].get("keep_clips_for_evaluation")
        ):
            shutil.rmtree(raw, ignore_errors=True)
            shutil.rmtree(store.media_dir("calibration", pid, "work"), ignore_errors=True)
        return _cal_summary(data) or {}

    @app.get("/api/calibration/{pid}")
    async def calibration_get(pid: str) -> dict[str, Any]:
        patient_or_404(pid)
        return {
            "calibration": _cal_summary(store.get_calibration(pid)),
            "counts": _cal_counts(store.media_dir("calibration", pid, "raw")),
        }

    @app.put("/api/calibration/{pid}/description")
    async def calibration_edit(pid: str, body: dict[str, Any]) -> dict[str, Any]:
        cal = store.get_calibration(pid)
        if not cal:
            raise HTTPException(404, "not calibrated")
        desc = {**cal["description"], **body}
        cal["description"] = desc
        cal["signal_text"] = calib.signal_text(desc)
        store.save_calibration(pid, cal)
        return _cal_summary(cal) or {}

    # ---------------------------------------------------------------- sessions
    @app.post("/api/sessions")
    async def create_session(request: Request, body: SessionCreate) -> dict[str, Any]:
        patient = patient_or_404(body.patient_id)
        mode = mode_for(request, body.privacy, body.passcode)
        if mode != Mode.MOCK and not settings.live_passcode:
            check_passcode(body.passcode)
        s = await manager.create(
            patient,
            mode=mode,
            privacy=body.privacy,
            simulated_truth=body.simulated_patient,
            simulated_noise=body.simulated_noise,
            scenario_name=body.scenario,
        )
        return s.view()

    @app.post("/api/scenarios/{name}")
    async def start_scenario(
        request: Request, name: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create the scenario's fictional patient and a session in one step (mock demos)."""
        try:
            scenario = load_scenario(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        body = body or {}
        profile = PatientProfile(**scenario["profile"])
        if body.get("language") in ("en", "id"):
            profile.language = body["language"]
        pid = store.create_patient(profile.model_dump())
        s = await manager.create(
            patient_or_404(pid),
            mode=mode_for(request, bool(body.get("privacy"))),
            privacy=bool(body.get("privacy")),
            simulated_truth="scenario" if body.get("simulated") else None,
            simulated_noise=float(body.get("noise", 0.05)),
            scenario_name=name,
        )
        return s.view()

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str) -> dict[str, Any]:
        return session_or_404(sid).view()

    @app.post("/api/sessions/{sid}/start")
    async def start_session(sid: str) -> dict[str, Any]:
        s = session_or_404(sid)
        if s.message_index == 0:
            await s.start()
        return s.view()

    @app.post("/api/sessions/{sid}/spoken")
    async def spoken(sid: str, body: dict[str, Any]) -> dict[str, Any]:
        s = session_or_404(sid)
        await s.spoken(str(body.get("prompt_id")))
        return {"ok": True}

    @app.post("/api/sessions/{sid}/answer")
    async def answer(sid: str, body: AnswerCreate) -> dict[str, Any]:
        s = session_or_404(sid)
        ok = await s.answer(body.prompt_id, body.answer, body.source)
        return {"ok": ok}

    @app.post("/api/sessions/{sid}/clip")
    async def session_clip(
        sid: str, prompt_id: str = Form(...), file: UploadFile = File(...)
    ) -> dict[str, Any]:
        s = session_or_404(sid)
        path = await save_upload(
            file, store.media_dir("sessions", sid), f"{prompt_id}_{new_id('c')}"
        )
        return await s.clip(prompt_id, path)

    @app.post("/api/sessions/{sid}/idle")
    async def idle_clip(sid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        """Idle watch: a clip recorded while nobody is asking. Triple YES raises the alarm,
        a single YES starts a new message."""
        from app.perception.pipeline import perceive

        s = session_or_404(sid)
        if s.ended:
            return {"answer": "none", "ignored": "session ended"}
        path = await save_upload(file, store.media_dir("sessions", sid), f"idle_{new_id('c')}")
        perc = await perceive(
            path,
            s.calibration,
            store.media_dir("sessions", sid),
            hub=hub,
            roles=ctx.roles,
            settings=settings,
            mode=s.mode,
        )
        ans = str(perc.observation.answer)
        if ans == "emergency":
            await s.emergency("idle_watch:triple_yes")
        elif ans == "yes" and str(s.state) in ("DONE", "IDLE"):
            await s.new_message()
        return {"answer": ans, **perc.to_dict()}

    @app.post("/api/sessions/{sid}/audio")
    async def session_audio(sid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        s = session_or_404(sid)
        path = await save_upload(file, store.media_dir("sessions", sid), f"audio_{new_id('a')}")
        segs = await s.add_audio(path)
        return {"segments": segs}

    @app.post("/api/sessions/{sid}/transcript")
    async def session_transcript(sid: str, body: TranscriptLine) -> dict[str, Any]:
        return await session_or_404(sid).add_transcript(body.speaker, body.text)

    @app.post("/api/sessions/{sid}/snapshot")
    async def session_snapshot(sid: str, file: UploadFile = File(...)) -> dict[str, Any]:
        s = session_or_404(sid)
        path = await save_upload(file, store.media_dir("sessions", sid), f"snapshot_{new_id('s')}")
        return {"facts": await s.add_snapshot(path)}

    @app.post("/api/sessions/{sid}/event")
    async def session_event(sid: str, body: EventCreate) -> dict[str, Any]:
        return await session_or_404(sid).add_event(body.kind, body.label)

    @app.post("/api/sessions/{sid}/override")
    async def session_override(sid: str, body: OverrideCreate) -> dict[str, Any]:
        s = session_or_404(sid)
        result = await s.override(body.action)
        if body.action == "end":
            _schedule_curation(s)
        return {**result, "snapshot": s.view()}

    @app.post("/api/sessions/{sid}/messages/{mid}/ack")
    async def acknowledge_message(sid: str, mid: str) -> dict[str, Any]:
        """A caregiver saw the patient's message and is coming."""
        s = session_or_404(sid)
        return {"ok": await s.acknowledge(mid), "snapshot": s.view()}

    @app.post("/api/sessions/{sid}/relays/{rid}/{action}")
    async def relay_action(sid: str, rid: str, action: str) -> dict[str, Any]:
        """Caregiver steps of the family relay: approve the text, cancel, or let the phone read a
        reply that was held for review."""
        s = session_or_404(sid)
        handlers = {
            "approve": s.relay.approve,
            "cancel": s.relay.cancel,
            "read": s.relay.read_to_patient,
        }
        if action not in handlers:
            raise HTTPException(404, "unknown relay action")
        ok = await handlers[action](rid)
        await s._notify()  # noqa: SLF001
        return {"ok": ok, "snapshot": s.view()}

    @app.get("/api/relay/whatsapp")
    async def whatsapp_verify(request: Request) -> Response:
        """Webhook verification: echo hub.challenge when the verify token matches."""
        q = request.query_params
        expected = settings.whatsapp_verify_token
        if (
            expected
            and q.get("hub.mode") == "subscribe"
            and secrets.compare_digest(q.get("hub.verify_token") or "", expected)
        ):
            return PlainTextResponse(q.get("hub.challenge") or "")
        raise HTTPException(403, "verification failed")

    @app.post("/api/relay/whatsapp")
    async def whatsapp_webhook(request: Request) -> dict[str, Any]:
        """Replies and delivery receipts, signed with the app secret."""
        raw = await request.body()
        secret = settings.whatsapp_app_secret
        if not secret or not verify_signature(
            secret, raw, request.headers.get("X-Hub-Signature-256")
        ):
            raise HTTPException(403, "bad signature")
        events = parse_webhook(json.loads(raw or b"{}"))
        channel = ctx.relay_channel
        for kind, cid, phone, text in events:
            if kind == "reply" and channel is not None:
                channel.note_inbound(phone)
            await manager.relay_event(kind, cid, phone, text)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/end")
    async def end_session(sid: str) -> dict[str, Any]:
        s = session_or_404(sid)
        await s.end()
        _schedule_curation(s)
        return s.summary()

    @app.get("/api/sessions/{sid}/log")
    async def session_log(sid: str, tail: int = 200) -> list[dict[str, Any]]:
        path = store.session_log_path(sid)
        if not path.exists():
            raise HTTPException(404, "no log")
        lines = path.read_text(encoding="utf-8").splitlines()[-tail:]
        return [json.loads(x) for x in lines]

    def _schedule_curation(s: Session) -> None:
        if not hub.flag("use_wonder"):
            return

        async def run() -> None:
            try:
                await curator.curate(store, ctx.roles, s.pid, s.mode)
            except Exception:
                log.exception("memory curation failed")

        asyncio.ensure_future(run())

    # ------------------------------------------------------------------ memory
    @app.get("/api/memory/{pid}")
    async def memory_get(pid: str) -> dict[str, Any]:
        patient_or_404(pid)
        return {
            "entries": store.memory(pid, None),
            "ops": store.memory_ops(pid, "pending"),
            "learning_curve": curator.learning_curve(store, pid),
            "messages": [m for m in store.messages(pid) if not m["sensitive"]][-50:],
        }

    @app.post("/api/memory/{pid}")
    async def memory_add(pid: str, body: dict[str, Any]) -> dict[str, Any]:
        """A caregiver enters a fact directly (provenance: caregiver)."""
        patient_or_404(pid)
        text = str(body.get("text", "")).strip()
        from app.safety.advice import contains_advice
        from app.safety.sensitive import detect

        if not text or len(text) > 200:
            raise HTTPException(400, "text must be 1-200 characters")
        if detect(text).sensitive or contains_advice(text):
            raise HTTPException(400, "Sensitive or clinical facts are never stored in memory.")
        eid = store.add_memory(
            pid, text, body.get("category") or "fact", "caregiver", "caregiver:entered"
        )
        return store.get_memory(eid) or {}

    @app.post("/api/memory/{pid}/curate")
    async def memory_curate(
        request: Request, pid: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        patient_or_404(pid)
        return await curator.curate(
            store, ctx.roles, pid, mode_for(request, bool((body or {}).get("privacy")))
        )

    @app.post("/api/memory/{pid}/ops/{op_id}/approve")
    async def memory_approve(pid: str, op_id: str) -> dict[str, Any]:
        try:
            return curator.approve(store, pid, op_id)
        except KeyError as exc:
            raise HTTPException(404, "operation not found or already decided") from exc

    @app.post("/api/memory/{pid}/ops/{op_id}/reject")
    async def memory_reject(pid: str, op_id: str) -> dict[str, Any]:
        op = store.get_memory_op(op_id)
        if not op or op["patient_id"] != pid:
            raise HTTPException(404, "operation not found")
        store.decide_memory_op(op_id, "rejected")
        return {"ok": True}

    @app.delete("/api/memory/{pid}/{entry_id}")
    async def memory_delete(pid: str, entry_id: str) -> dict[str, Any]:
        if not store.delete_memory(pid, entry_id):
            raise HTTPException(404, "entry not found")
        return {"deleted": True}

    # -------------------------------------------------------------- simulation
    @app.get("/api/sim/results")
    async def sim_results() -> dict[str, Any]:
        path = ROOT / "docs" / "sim_results.json"
        if not path.exists():
            raise HTTPException(404, "run `make sim` first")
        return json.loads(path.read_text())

    @app.post("/api/sim/run")
    async def sim_run(body: dict[str, Any] | None = None) -> dict[str, Any]:
        from dataclasses import asdict

        from sim.simulate import run as run_sim

        trials = int(min(max((body or {}).get("trials", 150), 20), 500))
        seed = int((body or {}).get("seed", 7))
        results = await asyncio.to_thread(run_sim, trials, seed, 4)
        return {
            "trials": trials,
            "seed": seed,
            "label": "simulation, not clinical evidence",
            "results": [asdict(r) for r in results],
        }

    # --------------------------------------------------------------- websocket
    @app.websocket("/ws/sessions/{sid}")
    async def ws_session(ws: WebSocket, sid: str) -> None:
        s = manager.get(sid)
        await ws.accept()
        if s is None:
            await ws.send_json({"type": "error", "error": "session not found"})
            await ws.close(code=4404)
            return
        await manager.subscribe(sid, ws)
        await ws.send_json({"type": "snapshot", "snapshot": s.view()})
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "spoken":
                    await s.spoken(str(msg.get("prompt_id")))
                elif kind == "answer":
                    await s.answer(
                        str(msg.get("prompt_id")),
                        str(msg.get("answer")),
                        msg.get("source", "keyboard"),
                    )
                elif kind == "override":
                    await s.override(str(msg.get("action")))
                elif kind == "start":
                    if s.message_index == 0:
                        await s.start()
                elif kind == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("websocket error")
        finally:
            manager.unsubscribe(sid, ws)

    # Production (Dockerfile): the built web app from the same origin as the API.
    dist = os.environ.get("FRONTEND_DIST")
    if dist and (Path(dist) / "index.html").is_file():
        web_root = Path(dist).resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def web_app(path: str) -> FileResponse:
            if path.startswith(("api/", "ws/")):
                raise HTTPException(404, "not found")
            target = (web_root / path).resolve()
            if path and target.is_file() and web_root in target.parents:
                return FileResponse(target)
            return FileResponse(web_root / "index.html")  # client-side routes

    return app


def _cal_counts(d: Path) -> dict[str, int]:
    return {label: len(list(d.glob(f"{label}_*"))) for label in CAL_LABELS}


def _cal_summary(cal: dict[str, Any] | None) -> dict[str, Any] | None:
    if not cal:
        return None
    return {k: v for k, v in cal.items() if k not in ("tracker", "local")} | {
        "tracker_provider": (cal.get("tracker") or {}).get("provider"),
        "tracker_loo": (cal.get("tracker") or {}).get("loo"),
        "local_loo": (cal.get("local") or {}).get("loo"),
    }


app = create_app()
