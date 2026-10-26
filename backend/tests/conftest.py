from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

os.environ["APP_MODE"] = "mock"

from app.config import load_settings  # noqa: E402
from app.perception.signals import default_calibration  # noqa: E402
from app.providers.registry import Mode, ProviderHub  # noqa: E402
from app.roles import Roles  # noqa: E402
from app.scenarios import apply as apply_scenario  # noqa: E402
from app.scenarios import load as load_scenario  # noqa: E402
from app.sessions.session import AppContext, Session  # noqa: E402
from app.sessions.simulated import SimulatedPatient  # noqa: E402
from app.sessions.state_machine import State  # noqa: E402
from app.storage import Store, new_id  # noqa: E402

TERMINAL = {State.DONE, State.CAREGIVER_NEEDED, State.PAUSED, State.EMERGENCY}


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    settings = load_settings()
    settings = settings.model_copy(
        update={
            "app_mode": "mock",
            "data_dir": tmp_path,
            "model_api_key": None,
            "baseten_api_key": None,
        }
    )
    store = Store(tmp_path)
    hub = ProviderHub(settings, store)
    return AppContext(settings, store, hub, Roles(hub, settings))


def make_session(
    ctx: AppContext,
    scenario: str = "daughter",
    sim: SimulatedPatient | None = None,
    language: str | None = None,
    events: list[dict[str, Any]] | None = None,
    strict: bool = True,
) -> Session:
    sc = load_scenario(scenario)
    profile = dict(sc["profile"])
    if language:
        profile["language"] = language
    pid = ctx.store.create_patient(profile)
    patient = ctx.store.get_patient(pid)
    sid = new_id("ses")
    ctx.store.create_session(sid, pid, "mock")
    apply_scenario(ctx.store, sc, pid, sid)

    async def on_change(s: Session, event: dict[str, Any] | None) -> None:
        if events is not None and event:
            events.append(event)

    return Session(
        sid,
        patient,
        default_calibration("mock"),
        ctx,
        mode=Mode.MOCK,
        simulated=sim,
        scenario=sc,
        on_change=on_change,
        strict=strict,
    )


async def run_until(session: Session, states: set[State] = TERMINAL, timeout: float = 20.0) -> None:
    async def wait() -> None:
        while session.state not in states:
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), timeout)
    await asyncio.sleep(0.02)
