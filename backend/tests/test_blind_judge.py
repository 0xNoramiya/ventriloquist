"""Safety rule 7: the blind judge sees the clip and the patient's calibrated signals, never the question."""

from __future__ import annotations

import inspect

from app.providers.registry import Mode
from app.roles import Roles, _instructions


class _RecordingHub:
    """Stands in for the provider hub and keeps every request a role sends."""

    def __init__(self) -> None:
        self.requests = []

    def caller(self, mode):
        requests = self.requests

        class _Caller:
            async def call(self, req, fallback, version):
                requests.append(req)
                return None

        return _Caller()


def test_the_judge_cannot_be_given_the_question():
    params = list(inspect.signature(Roles.judge).parameters)
    assert params == ["self", "mode", "clip", "signal_text", "mock_label"]


async def test_the_judge_request_holds_only_the_clip_and_the_signals(ctx, tmp_path):
    hub = _RecordingHub()
    clip = tmp_path / "answer.mp4"
    clip.write_bytes(b"\x00")
    signals = "YES: raises both eyebrows. NO: squeezes both eyes shut."

    await Roles(hub, ctx.settings).judge(Mode.LIVE, clip, signals)

    (req,) = hub.requests
    assert req.role == "blind_judge"
    assert [(p.kind, p.path, p.text) for p in req.parts] == [("video", clip, None)]
    assert set(req.context) <= {"mock_label", "_video_fps"}
    # the fixed prompt plus the calibrated signals, and nothing else: no question, no guesses
    expected, _ = _instructions("blind_judge", f"\nThe patient's calibrated signals:\n{signals}")
    assert req.instructions == expected
