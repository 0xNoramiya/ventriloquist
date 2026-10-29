"""Cost estimation and the budget guard.

Spend is estimated from usage fields and the prices in config.yaml. At 70% of budget.max_usd the UI
shows a warning; at 90% every provider switches to mock and the UI says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.storage import Store

from .base import Usage


def estimate_usd(settings: Settings, model: str, usage: Usage, kind: str = "tokens") -> float:
    price = settings.pricing.get(model)
    if not price:
        return 0.0
    if kind == "tokens":
        uncached = max(usage.input_tokens - usage.cached_tokens, 0)
        return (
            uncached * price.get("input_per_m", 0.0)
            + usage.cached_tokens * price.get("cached_input_per_m", price.get("input_per_m", 0.0))
            + usage.output_tokens * price.get("output_per_m", 0.0)
        ) / 1_000_000
    if kind == "video_frames":
        frames = max(usage.units, price.get("min_video_frames", 0))
        return frames * price.get("per_video_frame", 0.0)
    if kind == "images":
        return usage.units * price.get("per_image", 0.0)
    if kind == "audio_minutes":
        return usage.units * price.get("per_audio_minute", 0.0)
    return 0.0


@dataclass
class BudgetStatus:
    spent_usd: float
    max_usd: float
    level: str  # ok | warn | mock

    @property
    def fraction(self) -> float:
        return self.spent_usd / self.max_usd if self.max_usd else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "spent_usd": round(self.spent_usd, 4),
            "max_usd": self.max_usd,
            "fraction": round(self.fraction, 4),
            "level": self.level,
        }


class CostMeter:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    def record(
        self,
        provider: str,
        model: str,
        role: str,
        usd: float,
        usage: Usage,
        latency_ms: float,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.store.add_spend(
            provider, model, role, usd, usage.input_tokens, usage.output_tokens, latency_ms, detail
        )

    def max_usd(self) -> float:
        override = self.store.kv_get("budget_max_usd")
        return float(override) if override else self.settings.budget.max_usd

    def status(self) -> BudgetStatus:
        spent = self.store.total_spend()
        cap = self.max_usd()
        frac = spent / cap if cap else 0.0
        level = (
            "mock"
            if frac >= self.settings.budget.mock_fraction
            else ("warn" if frac >= self.settings.budget.warn_fraction else "ok")
        )
        return BudgetStatus(spent, cap, level)

    def allows_live(self) -> bool:
        return self.status().level != "mock"
