"""Scenario fixtures for mock mode, the CLI demo and tests (fictional patients only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.storage import Store

DIR = Path(__file__).parent
TAG = "_scn_"  # in the id of every row a scenario writes; new_id() never produces it


def is_scripted(row_id: str | None) -> bool:
    """True for evidence a scenario wrote in advance, not something the camera, the microphone
    or a nurse supplied (issue #18)."""
    return bool(row_id) and TAG in row_id


def names() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.yaml"))


@lru_cache(maxsize=16)
def load(name: str) -> dict[str, Any]:
    path = DIR / f"{name}.yaml"
    if not path.exists():
        raise KeyError(f"unknown scenario {name}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def apply(store: Store, scenario: dict[str, Any], pid: str, sid: str) -> None:
    """Insert the scenario's evidence with back-dated server timestamps."""
    now = datetime.now(UTC)
    ev = scenario.get("evidence") or {}
    for i, t in enumerate(ev.get("transcript") or []):
        at = (now - timedelta(minutes=float(t.get("minutes_ago", 1)))).isoformat(
            timespec="milliseconds"
        )
        store.add_transcript(
            pid, sid, t.get("speaker", "room"), t["text"], at=at, row_id=f"tr{TAG}{sid}_{i}"
        )
    for i, f in enumerate(ev.get("scene") or []):
        store.add_scene_fact(pid, sid, f, "scenario", row_id=f"sc{TAG}{sid}_{i}")
    for e in ev.get("events") or []:
        at = (now - timedelta(minutes=float(e.get("minutes_ago", 1)))).isoformat(
            timespec="milliseconds"
        )
        store.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            (
                f"ev{TAG}{sid}_{e['kind']}_{int(e.get('minutes_ago', 0))}",
                sid,
                pid,
                e["kind"],
                e.get("label"),
                at,
            ),
        )
