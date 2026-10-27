"""Answer perception: when the tracker may decide alone, and how sources are fused."""

from __future__ import annotations

import pytest

from app.engine.types import Answer
from app.perception.fusion import SourceResult, fuse, normalise_probs
from app.perception.pipeline import early_decision_ok


def tracker(top: str, p: float, distances: dict[str, float]) -> SourceResult:
    rest = (1 - p) / 3
    probs = {k: (p if k == top else rest) for k in ("yes", "no", "none", "emergency")}
    return SourceResult("tracker", probs, True, {"distances": distances})


@pytest.mark.parametrize(
    ("res", "early"),
    [
        (tracker("yes", 0.95, {"yes": 0.10, "none": 0.30, "no": 0.50}), True),
        (tracker("no", 0.92, {"no": 0.0, "none": 0.20, "yes": 0.40}), True),
        # confident but the templates are nearly tied (seen live on a clip unlike calibration)
        (tracker("yes", 0.94, {"yes": 0.142, "none": 0.162, "no": 0.478}), False),
        # "no answer" always waits for the blind judge
        (tracker("none", 0.98, {"none": 0.05, "yes": 0.40, "no": 0.60}), False),
        (tracker("yes", 0.80, {"yes": 0.10, "none": 0.40}), False),
        (tracker("yes", 0.95, {}), False),
        (SourceResult("tracker", {}, ok=False), False),
        (None, False),
    ],
)
def test_early_decision_needs_clear_yes_or_no(res, early):
    assert early_decision_ok(res, p_min=0.90, margin_min=1.25) is early


def test_no_single_source_is_certain():
    probs = normalise_probs({"yes": 1.0, "rest": 0.0})
    assert probs["yes"] == pytest.approx(0.98)
    assert sum(probs.values()) == pytest.approx(1.0)


def test_confident_sources_that_disagree_give_unclear():
    a = tracker("yes", 0.9, {})
    b = SourceResult("spark", {"yes": 0.05, "no": 0.9, "none": 0.03, "emergency": 0.02})
    obs = fuse([a, b], {"tracker": 1.0, "spark": 1.0})
    assert obs.answer == Answer.UNCLEAR and obs.sources["reason"] == "sources_disagree"
