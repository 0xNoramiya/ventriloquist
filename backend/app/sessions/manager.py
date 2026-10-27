"""Active sessions and their WebSocket subscribers (one active session per patient)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import WebSocket

from app.engine.taxonomy import taxonomy_ids
from app.perception.signals import default_calibration
from app.scenarios import apply as apply_scenario
from app.scenarios import load as load_scenario
from app.storage import new_id

from .session import AppContext, Session
from .simulated import SimulatedPatient

log = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.sessions: dict[str, Session] = {}
        self.subscribers: dict[str, set[WebSocket]] = {}

    async def relay_event(
        self, kind: str, channel_id: str | None, phone: str, text: str | None
    ) -> bool:
        """A WhatsApp receipt or reply: hand it to the session whose relay it belongs to."""
        for s in self.sessions.values():
            if not s.ended and s.relay.owns(channel_id, phone):
                await s.relay.on_event(kind, channel_id, phone, text)
                return True
        return False

    def active_for(self, pid: str) -> Session | None:
        for s in self.sessions.values():
            if s.pid == pid and not s.ended:
                return s
        return None

    async def create(
        self,
        patient: dict[str, Any],
        *,
        privacy: bool = False,
        simulated_truth: str | None = None,
        simulated_noise: float = 0.05,
        scenario_name: str | None = None,
    ) -> Session:
        existing = self.active_for(patient["id"])
        if existing is not None:
            await existing.end()
        mode = self.ctx.hub.requested_mode(privacy)
        calibration = self.ctx.store.get_calibration(patient["id"]) or default_calibration(
            str(mode)
        )
        sid = new_id("ses")
        self.ctx.store.create_session(sid, patient["id"], str(mode))
        scenario = load_scenario(scenario_name) if scenario_name else None
        if scenario:
            apply_scenario(self.ctx.store, scenario, patient["id"], sid)
        sim = None
        if simulated_truth:
            sim = self._simulated(simulated_truth, simulated_noise, scenario)
        session = Session(
            sid,
            patient,
            calibration,
            self.ctx,
            mode=mode,
            simulated=sim,
            scenario=scenario,
            on_change=self.broadcast,
            sim_delay_s=1.2 if sim else 0.0,
        )
        self.sessions[sid] = session
        return session

    def _simulated(
        self, truth: str, noise: float, scenario: dict[str, Any] | None
    ) -> SimulatedPatient:
        sp = (scenario or {}).get("patient") or {}
        if truth == "scenario":
            return SimulatedPatient(
                truth=sp.get("truth"),
                spell=sp.get("spell"),
                sentence_en=sp.get("sentence_en"),
                noise=noise,
            )
        if truth.startswith("spell:"):
            return SimulatedPatient(truth=None, spell=truth.split(":", 1)[1], noise=noise)
        if truth not in taxonomy_ids() and not truth.startswith(("see_person:", "where_person:")):
            truth = "other"
        return SimulatedPatient(truth=truth, noise=noise)

    def get(self, sid: str) -> Session | None:
        return self.sessions.get(sid)

    # ----------------------------------------------------------------- sockets
    async def subscribe(self, sid: str, ws: WebSocket) -> None:
        self.subscribers.setdefault(sid, set()).add(ws)

    def unsubscribe(self, sid: str, ws: WebSocket) -> None:
        self.subscribers.get(sid, set()).discard(ws)

    async def broadcast(self, session: Session, event: dict[str, Any] | None = None) -> None:
        subs = list(self.subscribers.get(session.id, set()))
        if not subs:
            return
        payload: dict[str, Any] = {"type": "snapshot", "snapshot": session.view()}
        if event:
            payload["event"] = event
        dead = []
        for ws in subs:
            try:
                await asyncio.wait_for(ws.send_json(payload), timeout=5)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unsubscribe(session.id, ws)

    async def shutdown(self) -> None:
        for s in self.sessions.values():
            with contextlib.suppress(Exception):
                await s.end()
