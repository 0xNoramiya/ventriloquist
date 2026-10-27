"""Answer perception: when the tracker may decide alone, and how sources are fused."""

from __future__ import annotations

import numpy as np
import pytest

from app.engine.types import Answer
from app.perception.calibration import signal_roi
from app.perception.features import LEGACY_SAM_FEATURES, sam_feature_seq
from app.perception.fusion import SourceResult, fuse, judge_probs, normalise_probs
from app.perception.media import roi_crop_px
from app.perception.pipeline import early_decision_ok
from app.providers.base import FrameTracks, TrackedObject, TrackResult


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


def test_roi_maps_back_to_source_pixels():
    # 4:3 source: plain scaling
    assert roi_crop_px(640, 480, [0.25, 0.25, 0.75, 0.75], 320, 240) == (320, 240, 160, 120)
    # portrait 3:4 phone: the normalised frame is padded left and right
    w, h, x, y = roi_crop_px(480, 640, [0.0, 0.0, 1.0, 1.0], 320, 240)
    assert (w, h, x, y) == (480, 640, 0, 0)
    w, h, x, y = roi_crop_px(480, 640, [0.5, 0.25, 0.75, 0.5], 320, 240)
    # scale 0.375, 70 px padding: x = (0.5 * 320 - 70) / 0.375 = 240
    assert (w, h, x, y) == (212, 160, 240, 160)


def track(boxes: list[tuple[float, float, float, float]]) -> TrackResult:
    frames = [FrameTracks(i / 8, [TrackedObject(0, b)]) for i, b in enumerate(boxes)]
    return TrackResult(frames, "meta", "sam-3.1", "eyebrows")


def test_signal_roi_is_a_padded_square_around_the_signal():
    brows = track([(0.40, 0.30, 0.60, 0.35)] * 10)
    eyes = track([(0.41, 0.36, 0.59, 0.42)] * 10)
    roi = signal_roi([brows, eyes])
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert x1 - x0 == pytest.approx(y1 - y0)  # square in fractions = 4:3 in pixels
    assert x0 < 0.40 and x1 > 0.60 and y0 < 0.30 and y1 > 0.42
    # near the edge the region shifts inside the frame instead of shrinking
    edge = signal_roi([track([(0.0, 0.0, 0.1, 0.05)] * 5)])
    assert edge is not None and edge[0] == 0.0 and edge[1] == 0.0 and edge[2] >= 0.35
    assert signal_roi([track([])]) is None


def test_seen_feature_marks_frames_where_the_part_vanished():
    eyes = (0.4, 0.36, 0.6, 0.42)
    frames = [FrameTracks(i / 8, [] if 3 <= i <= 5 else [TrackedObject(0, eyes)]) for i in range(8)]
    seq = sam_feature_seq(TrackResult(frames, "meta", "sam-3.1", "eyes"), fps=8)
    assert seq.names[-1] == "seen"
    assert seq.values[:, -1].tolist() == [1, 1, 1, 0, 0, 0, 1, 1]
    assert not np.isnan(seq.values).any()  # geometry is interpolated across the gap
    legacy = sam_feature_seq(
        TrackResult(frames, "meta", "sam-3.1", "eyes"), fps=8, names=LEGACY_SAM_FEATURES
    )
    assert legacy.values.shape == (8, 5)


def test_agreeing_sources_reinforce_and_a_missed_movement_is_outvoted():
    """Readings from the live run on the generated clips (rest_eval_1, no_eval_0). When one
    source sees nothing and the other a clear NO, the more reliable reading wins with lower
    confidence; a YES-against-NO split stays UNCLEAR (test above)."""
    weights = {"tracker": 0.875**2, "spark": 1.0}
    calm = fuse(
        [tracker("none", 0.835, {}), SourceResult("spark", judge_probs("none", 0.45))], weights
    )
    assert calm.answer == Answer.NONE and calm.confidence > 0.85
    split = fuse(
        [tracker("none", 0.85, {}), SourceResult("spark", judge_probs("no", 0.9))], weights
    )
    assert split.answer == Answer.NO and 0.65 <= split.confidence < 0.9


def test_a_single_source_keeps_its_own_reading():
    only = tracker("yes", 0.8, {})
    obs = fuse([only], {"tracker": 0.3})
    assert obs.answer == Answer.YES and obs.confidence == pytest.approx(0.8)
