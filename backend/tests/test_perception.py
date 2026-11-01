"""Answer perception: when the tracker may decide alone, and how sources are fused."""

from __future__ import annotations

import numpy as np
import pytest

from app.engine.types import Answer
from app.perception.calibration import signal_roi
from app.perception.features import LEGACY_SAM_FEATURES, sam_feature_seq
from app.perception.fusion import SourceResult, fuse, judge_probs, normalise_probs
from app.perception.media import roi_crop_px
from app.perception.pipeline import _template_source, early_decision_ok, yes_repetitions
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


def _clip(path, frames):
    import cv2

    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 15, (320, 240))
    for f in frames:
        out.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
    out.release()
    return path


def test_sam_tracks_every_part_the_signals_name():
    """Issue #4: both prompts were `eyebrows` for a NO made with the eyes."""
    from app.perception.calibration import sam_prompts
    from app.schemas import CalibrationDescription

    def desc(yes: tuple[str, str, str], no: tuple[str, str, str]) -> CalibrationDescription:
        spec = lambda part, motion, prompt: {  # noqa: E731
            "body_part": part,
            "motion": motion,
            "sam_prompt": prompt,
            "description": motion,
        }
        return CalibrationDescription.model_validate(
            {"yes": spec(*yes), "no": spec(*no), "distinct": True, "notes": ""}
        )

    real_face = desc(
        ("eyebrows", "raises eyebrows and opens eyes wide", "eyebrows"),
        ("eyebrows", "lowers eyebrows and holds eyes closed", "eyebrows"),
    )
    assert sam_prompts(real_face) == ["eyebrows", "eyes"]
    nod = desc(("head", "small nod", "head"), ("head", "turns head to the side", "head"))
    assert sam_prompts(nod) == ["head"]
    many = desc(
        ("eyebrows", "eyebrows up, mouth open, eyes wide", "eyebrows"),
        ("hand", "lifts a finger", "hand"),
    )
    assert len(sam_prompts(many)) == 3


def test_motion_roi_finds_where_the_signal_clips_move(tmp_path):
    """Without SAM (privacy mode) the judge's crop comes from where YES and NO move."""
    from app.perception.calibration import motion_roi

    still = np.full((240, 320), 120, np.uint8)
    moving = []
    for i in range(30):  # a bright bar bobbing up and down at (160, 70): an eyebrow raise
        f = still.copy()
        f[60 + 6 * (i % 2) : 70 + 6 * (i % 2), 130:190] = 230
        moving.append(f)
    yes = _clip(tmp_path / "yes.mp4", moving)
    rest = _clip(tmp_path / "rest.mp4", [still] * 30)
    roi = motion_roi([yes], [rest])
    assert roi is not None
    x0, y0, x1, y1 = roi
    assert x0 < 130 / 320 and x1 > 190 / 320 and y0 < 60 / 240 and y1 > 76 / 240
    assert x1 - x0 < 0.6  # a crop, not the whole frame
    assert motion_roi([rest], [rest]) is None


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


FPS = 8.0
EYEBROWS, EYES = slice(0, 6), slice(6, 12)  # sam_prompts puts the YES prompt (eyebrows) first


def movement(frames: int, part: slice, starts: list[int], size: float = 2.0) -> np.ndarray:
    seq = np.zeros((frames, 12))
    for s in starts:
        seq[s : s + 2, part] = size
    return seq


def test_blinks_on_the_eye_columns_are_not_repeated_yes():
    """Issue #14: tracking the eyes for NO made every blink count toward the triple-YES alarm."""
    raise_once = movement(32, EYEBROWS, [12]) + movement(32, EYES, [12], size=1.0)
    tmpl = {
        "baseline": {"mean": [0.0] * 12, "scale": [1.0] * 12},
        "templates": {
            "none": [np.zeros((32, 12)).tolist()],
            "yes": [raise_once.tolist()],
            "no": [movement(32, EYES, list(range(10, 22, 2))).tolist()],
            "emergency": [movement(32, EYEBROWS, [4, 12, 20]).tolist()],
        },
        "temperature": 1.0,
        "yes_amplitude": float(np.linalg.norm(raise_once, axis=1).max()),
    }
    templates = {k: [np.asarray(t) for t in v] for k, v in tmpl["templates"].items()}
    blinks = movement(40, EYES, [4, 14, 24, 34], size=3.0)
    amp = tmpl["yes_amplitude"]

    assert yes_repetitions(blinks, templates, amp, FPS) == 4  # every column: the old count
    assert yes_repetitions(blinks, templates, amp, FPS, yes_cols=6) == 0
    triple = movement(40, EYEBROWS, [4, 14, 24])
    assert yes_repetitions(triple, templates, amp, FPS, yes_cols=6) == 3

    calm = _template_source("tracker", blinks, tmpl, FPS, 3, yes_cols=6)
    assert calm.detail["repetitions"] == 0 and calm.probs["emergency"] < 0.5


def test_a_repetition_must_clear_the_rest_level():
    """A calibration whose YES clips missed the movement sets the YES bar below resting jitter."""
    templates = {
        "none": [movement(32, EYEBROWS, [6, 20], size=0.6)],
        "yes": [movement(32, EYEBROWS, [12], size=0.8)],
    }
    amp = float(np.linalg.norm(templates["yes"][0], axis=1).max())
    jitter = movement(40, EYEBROWS, [4, 14, 24, 34], size=0.5)

    assert yes_repetitions(jitter, {"yes": templates["yes"]}, amp, FPS) == 4
    assert yes_repetitions(jitter, templates, amp, FPS) == 0
    assert yes_repetitions(movement(40, EYEBROWS, [4, 14, 24]), templates, amp, FPS) == 3
