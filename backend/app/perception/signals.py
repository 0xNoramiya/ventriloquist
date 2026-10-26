"""Calibration helpers with no heavy imports (usable without OpenCV, e.g. in mock mode)."""

from __future__ import annotations

from typing import Any


def signal_text(desc: dict[str, Any]) -> str:
    y, n = desc["yes"], desc["no"]
    return (
        f"YES = {y['body_part']}: {y['motion']}. {y.get('description', '')}\n"
        f"NO = {n['body_part']}: {n['motion']}. {n.get('description', '')}\n"
        f"EMERGENCY = the YES movement three times in quick succession."
    )


def default_calibration(
    mode: str, a: float = 0.10, b: float = 0.10, hint: str | None = None
) -> dict[str, Any]:
    from app.providers.mock import mock_calibration

    desc = mock_calibration({"hint": hint})
    return {
        "mode": mode,
        "skipped": True,
        "description": desc,
        "signal_text": signal_text(desc),
        "prompts": [],
        "tracker": None,
        "local": None,
        "accuracy": {},
        "weights": {"keyboard": 1.0},
        "error_rates": {"a": a, "b": b},
        "ok": True,
        "suggestion": None,
    }
