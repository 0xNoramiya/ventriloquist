"""In-browser demo bridge: runs the real mock-mode session in Pyodide (WebAssembly), no server.

The hosted simulation-only demo loads this module in a Web Worker. It uses the same Session, engine,
safety checks and mock providers as the server; only the transport differs (postMessage instead of a
WebSocket). No camera, no keys, nothing leaves the browser.

    demo = BrowserDemo(push)                 # push(str) receives JSON snapshot messages
    await demo.scenario("daughter", simulated=False)
    await demo.handle('{"type": "start"}')
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ.setdefault("APP_MODE", "mock")


class BrowserDemo:
    def __init__(self, push: Callable[[str], Any], data_dir: str | None = None) -> None:
        from app.config import load_settings
        from app.providers.registry import ProviderHub
        from app.roles import Roles
        from app.sessions.session import AppContext
        from app.storage import Store

        path = Path(data_dir or tempfile.mkdtemp(prefix="vent_"))
        settings = load_settings().model_copy(
            update={
                "app_mode": "mock",
                "data_dir": path,
                "model_api_key": None,
                "baseten_api_key": None,
            }
        )
        store = Store(path)
        hub = ProviderHub(settings, store)
        self.ctx = AppContext(settings, store, hub, Roles(hub, settings))
        self.push = push
        self.session: Any = None

    async def _on_change(self, session: Any, event: dict[str, Any] | None) -> None:
        payload: dict[str, Any] = {"type": "snapshot", "snapshot": session.view()}
        if event:
            payload["event"] = event
        self.push(json.dumps(payload, default=str))

    def config(self) -> str:
        from app.engine.taxonomy import load_taxonomy
        from app.scenarios import load, names

        s = self.ctx.settings
        return json.dumps(
            {
                "engine": {
                    "tau_confirm": s.engine.tau_confirm,
                    "finalize_threshold": s.engine.finalize_threshold,
                    "max_questions": s.engine.max_questions,
                },
                "perception": {
                    "window_s": s.perception.window_s,
                    "window_delay_ms": s.perception.window_delay_ms,
                },
                "speech": s.raw.get("speech", {}),
                "flags": self.ctx.hub.flags(),
                "mode": "mock",
                "privacy_default": False,
                "language": s.raw["app"]["default_language"],
                "budget": self.ctx.hub.cost.status().to_dict(),
                "passcode_required": False,
                "scenarios": [{"id": n, "title": load(n).get("title", "")} for n in names()],
                "taxonomy": [
                    {"id": h["id"], "en": h["en"], "id_text": h["id_text"], "domain": h["domain"]}
                    for h in load_taxonomy()["hypotheses"]
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
                "models": s.models,
                "browser_demo": True,
            }
        )

    async def scenario(
        self, name: str, simulated: bool = False, noise: float = 0.05, language: str | None = None
    ) -> str:
        from app.perception.signals import default_calibration
        from app.providers.registry import Mode
        from app.scenarios import apply, load
        from app.sessions.session import Session
        from app.sessions.simulated import SimulatedPatient
        from app.storage import new_id

        if self.session is not None and not self.session.ended:
            await self.session.end()
        sc = load(name)
        profile = dict(sc["profile"])
        if language in ("en", "id"):
            profile["language"] = language
        store = self.ctx.store
        pid = store.create_patient(profile)
        sid = new_id("ses")
        store.create_session(sid, pid, "mock")
        apply(store, sc, pid, sid)
        sp = sc.get("patient") or {}
        sim = (
            SimulatedPatient(
                truth=sp.get("truth"),
                spell=sp.get("spell"),
                sentence_en=sp.get("sentence_en"),
                noise=noise,
            )
            if simulated
            else None
        )
        self.session = Session(
            sid,
            store.get_patient(pid),
            default_calibration("mock"),
            self.ctx,
            mode=Mode.MOCK,
            simulated=sim,
            scenario=sc,
            on_change=self._on_change,
            sim_delay_s=1.0 if sim else 0.0,
        )
        return json.dumps(self.session.view(), default=str)

    def snapshot(self) -> str:
        return json.dumps(self.session.view() if self.session else None, default=str)

    async def handle(self, raw: str) -> str:
        """The same client messages the WebSocket accepts, plus a few REST equivalents."""
        msg = json.loads(raw)
        s = self.session
        if s is None:
            return json.dumps({"ok": False, "reason": "no session"})
        kind = msg.get("type")
        if kind == "start" and s.message_index == 0:
            await s.start()
        elif kind == "spoken":
            await s.spoken(str(msg.get("prompt_id")))
        elif kind == "answer":
            await s.answer(str(msg.get("prompt_id")), str(msg.get("answer")), "keyboard")
        elif kind == "override":
            await s.override(str(msg.get("action")))
        elif kind == "ack":
            await s.acknowledge(str(msg.get("message_id")))
        elif kind == "relay":
            action = {
                "approve": s.relay.approve,
                "cancel": s.relay.cancel,
                "read": s.relay.read_to_patient,
            }.get(str(msg.get("action")))
            if action is not None:
                await action(str(msg.get("relay_id")))
                await s._notify()  # noqa: SLF001
        elif kind == "event":
            await s.add_event(str(msg.get("kind")), msg.get("label"))
        elif kind == "transcript":
            await s.add_transcript(str(msg.get("speaker") or "room"), str(msg.get("text") or ""))
        elif kind == "end":
            await s.end()
        return json.dumps({"ok": True})
