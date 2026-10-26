"""Fusion of per-source class probabilities into one observation (brief 9.5, 9.6).

Sources: the tracker path (SAM 3.1 boxes + DTW, or the local optical-flow baseline) and the blind
Muse Spark judge. Weighted average with calibration weights; UNCLEAR when the top class is below
0.65 or two confident sources disagree; EMERGENCY as soon as any source is fairly sure (sensitivity
is preferred to specificity: a false alarm costs a nurse a few seconds).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.engine.types import Answer, Observation

CLASSES = ("yes", "no", "none", "emergency")


@dataclass
class SourceResult:
    name: str
    probs: dict[str, float]
    ok: bool = True
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def top(self) -> tuple[str, float]:
        if not self.probs:
            return "none", 0.0
        k = max(self.probs, key=self.probs.get)
        return k, self.probs[k]

    def to_dict(self) -> dict[str, Any]:
        top, p = self.top
        return {
            "ok": self.ok,
            "top": top,
            "p": round(p, 3),
            "probs": {k: round(v, 3) for k, v in self.probs.items()},
            **self.detail,
        }


def judge_probs(classification: str, confidence: float) -> dict[str, float]:
    c = min(max(confidence, 0.0), 1.0)
    rest = (1 - c) / (len(CLASSES) - 1)
    return {k: (c if k == classification else rest) for k in CLASSES}


def normalise_probs(probs: dict[str, float]) -> dict[str, float]:
    full = {
        k: max(probs.get("rest" if k == "none" else k, probs.get(k, 0.0)), 0.0) for k in CLASSES
    }
    total = sum(full.values())
    return {k: v / total for k, v in full.items()} if total > 0 else {k: 0.25 for k in CLASSES}


def fuse(
    sources: list[SourceResult],
    weights: dict[str, float],
    unclear_threshold: float = 0.65,
    emergency_threshold: float = 0.5,
) -> Observation:
    usable = [s for s in sources if s.ok and s.probs]
    detail = {s.name: s.to_dict() for s in sources}
    if not usable:
        return Observation(Answer.UNCLEAR, 0.0, {"sources": detail, "reason": "no_source"})
    for s in usable:
        if s.probs.get("emergency", 0.0) >= emergency_threshold:
            return Observation(
                Answer.EMERGENCY,
                s.probs["emergency"],
                {"sources": detail, "reason": f"emergency:{s.name}"},
            )
    total_w = sum(max(weights.get(s.name, 0.5), 1e-3) for s in usable)
    combined = {k: 0.0 for k in CLASSES}
    for s in usable:
        w = max(weights.get(s.name, 0.5), 1e-3) / total_w
        for k in CLASSES:
            combined[k] += w * s.probs.get(k, 0.0)
    top = max(combined, key=combined.get)
    p = combined[top]
    degraded = len(usable) < len(sources)
    if degraded:
        p *= 0.85
    confident = [
        (s.top[0], s.name) for s in usable if s.top[1] >= 0.7 and s.top[0] in ("yes", "no")
    ]
    reason = "fused"
    if len({c for c, _ in confident}) > 1:
        answer, reason = Answer.UNCLEAR, "sources_disagree"
    elif p < unclear_threshold:
        answer, reason = Answer.UNCLEAR, "low_confidence"
    elif top == "none":
        answer = Answer.NONE
    else:
        answer = Answer(top)
    return Observation(
        answer,
        float(p),
        {
            "sources": detail,
            "combined": {k: round(v, 3) for k, v in combined.items()},
            "reason": reason,
            "degraded": degraded,
        },
    )
