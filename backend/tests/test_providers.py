"""Contract tests for the live adapters against responses recorded from the real APIs
(backend/tests/fixtures/meta_api, see docs/API_NOTES.md). No network, no keys."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from app.providers.base import LLMRequest, Part, RawResponse, Usage, VisionLanguage
from app.providers.baseten import DOCUMENTED_SLUG, BasetenVisionLanguage
from app.providers.cost import estimate_usd
from app.providers.llm import LLMCaller
from app.providers.meta_api import (
    MetaSamTracker,
    MetaTranscriber,
    MetaVisionLanguage,
    parse_responses_output,
    parse_sam_text,
    responses_usage,
    strict_schema,
)
from app.schemas import (
    CalibrationDescription,
    Completions,
    JudgeOut,
    MemoryOps,
    PriorProposal,
    QuestionProposal,
    SceneFacts,
    Sentences,
)

FIX = Path(__file__).parent / "fixtures" / "meta_api"


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


def sam_text_from_stream(name: str) -> str:
    return "".join(
        e.get("delta", "")
        for e in fixture(name)["events"]
        if e.get("type") == "response.output_text.delta"
    )


def live_settings(ctx):
    return ctx.settings.model_copy(
        update={"model_api_key": "LLM_test_key", "baseten_api_key": "bt_test"}
    )


class Schema(BaseModel):
    answer: str


# ------------------------------------------------------------------ parsing
def test_responses_output_and_usage_from_fixture():
    body = fixture("spark_responses_json_schema")
    text = parse_responses_output(body)
    assert isinstance(json.loads(text), dict)
    u = responses_usage(body)
    assert (u.input_tokens, u.output_tokens) == (185, 267)


def test_sam_video_wire_text_parses_to_tracks():
    text = sam_text_from_stream("sam_video_stream_one_bit_eyebrows")
    frames = parse_sam_text(text, fps=15.0, prompt="eyebrows")
    assert len(frames) == 60
    tops = [f.objects[0].box[1] * 480 for f in frames]
    assert tops[0] == pytest.approx(163, abs=1)
    assert min(tops[10:20]) < 140  # the eyebrow raise around frame 15
    assert frames[15].t == pytest.approx(1.0)
    assert all(0 <= v <= 1.01 for f in frames for v in f.objects[0].box)


def test_sam_nonstream_rest_clip_is_flat():
    body = fixture("sam_video_nonstream_lossless_eyebrows")
    frames = parse_sam_text(body["output"][0]["content"][0]["text"], 15.0, "eyebrows")
    tops = [round(f.objects[0].box[1] * 480) for f in frames]
    assert max(tops) - min(tops) <= 2


def test_strict_schema_for_every_role():
    for model in (
        CalibrationDescription,
        JudgeOut,
        PriorProposal,
        QuestionProposal,
        SceneFacts,
        Completions,
        Sentences,
        MemoryOps,
    ):
        schema = strict_schema(model)
        text = json.dumps(schema)
        assert "$ref" not in text and "$defs" not in text and "maxLength" not in text

        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object" and node.get("properties"):
                    assert node["additionalProperties"] is False
                    assert set(node["required"]) == set(node["properties"])
                for v in node.values():
                    check(v)
            elif isinstance(node, list):
                for v in node:
                    check(v)

        check(schema)


# ------------------------------------------------------------ HTTP adapters
async def test_meta_vision_language_request_and_response(ctx, tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=fixture("spark_responses_json_schema"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vl = MetaVisionLanguage(live_settings(ctx), client)
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\x00\x00")
    req = LLMRequest(
        role="blind_judge",
        instructions="sys",
        parts=[Part("text", text="hi"), Part("video", path=clip)],
        schema=JudgeOut,
        context={"_video_fps": 8},
        reasoning_effort="minimal",
    )
    raw = await vl.complete(req)
    body = seen["body"]
    assert seen["url"].endswith("/v1/responses")
    assert seen["auth"] == "Bearer LLM_test_key"
    assert body["store"] is False  # never keep patient data server-side
    assert body["model"] == ctx.settings.models["spark"]
    assert body["reasoning"] == {"effort": "minimal"}
    assert (
        body["text"]["format"]["type"] == "json_schema" and body["text"]["format"]["strict"] is True
    )
    video = [c for c in body["input"][0]["content"] if c["type"] == "input_video"][0]
    assert video["video_url"].startswith("data:video/mp4;base64,") and video["fps"] == 8
    assert body["max_output_tokens"] >= 600
    assert raw.usage.input_tokens == 185 and raw.provider == "meta"
    usd = estimate_usd(ctx.settings, raw.model, raw.usage)
    assert 0.0005 < usd < 0.005


async def test_meta_retries_429_then_succeeds(ctx):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"retry-after": "0"}, json={"error": {"type": "rate_limit_error"}}
            )
        return httpx.Response(200, json=fixture("spark_responses_json_schema"))

    vl = MetaVisionLanguage(
        live_settings(ctx), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    raw = await vl.complete(
        LLMRequest(role="x", instructions="s", parts=[Part("text", text="t")], schema=Schema)
    )
    assert calls["n"] == 2 and raw.text


async def test_meta_does_not_retry_400(ctx):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json=fixture("spark_error_reasoning_none"))

    vl = MetaVisionLanguage(
        live_settings(ctx), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    from app.providers.base import ProviderError

    with pytest.raises(ProviderError):
        await vl.complete(LLMRequest(role="x", instructions="s", parts=[], schema=Schema))
    assert calls["n"] == 1


async def test_meta_sam_tracker(ctx, tmp_path):
    import cv2
    import numpy as np

    clip = tmp_path / "c.mp4"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 15, (64, 48))
    for _ in range(10):
        w.write(np.zeros((48, 64, 3), np.uint8))
    w.release()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=fixture("sam_video_nonstream_lossless_eyebrows"))

    tr = MetaSamTracker(
        live_settings(ctx), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    res = await tr.track(clip, "eyebrows")
    body = seen["body"]
    assert body["model"] == ctx.settings.models["sam"] and body["store"] is False
    assert body["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}
    content = body["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "eyebrows"}
    assert len(res.frames) == 60 and res.usage.units == 60
    assert estimate_usd(ctx.settings, res.model, res.usage, "video_frames") == pytest.approx(0.012)


async def test_meta_transcriber_sends_language_bias_and_keywords(ctx, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....WAVE")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content"] = request.content.decode(errors="ignore")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=fixture("asr_transcribe_diarization"))

    tr = MetaTranscriber(
        live_settings(ctx), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    res = await tr.transcribe(wav, "id", ["Aisyah"])
    assert seen["url"].endswith("/v1/asr/transcribe")
    assert (
        '"languageBias": ["Indonesian"]' in seen["content"]
        and '"keywords": ["Aisyah"]' in seen["content"]
    )
    assert [s.speaker for s in res.segments] == ["A", "B", "A"]
    assert res.duration_s == pytest.approx(13.12)


async def test_baseten_falls_back_to_documented_slug(ctx):
    models = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        models.append(body["model"])
        assert body["reasoning_effort"] == "low"
        assert "JSON schema" in body["messages"][0]["content"]
        if body["model"] != DOCUMENTED_SLUG:
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer": "ok"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    vl = BasetenVisionLanguage(
        live_settings(ctx), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    raw = await vl.complete(
        LLMRequest(role="x", instructions="s", parts=[Part("text", text="t")], schema=Schema)
    )
    assert models == [ctx.settings.models["spark_open"], DOCUMENTED_SLUG]
    assert json.loads(raw.text) == {"answer": "ok"} and raw.provider == "baseten"


# ------------------------------------------------------------ repair/fallback
class Scripted(VisionLanguage):
    provider = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.repairs: list[str | None] = []

    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse:
        self.repairs.append(repair)
        return RawResponse(self.replies.pop(0), "scripted", "m", 1.0, Usage())


async def test_llm_caller_repairs_once_then_falls_back():
    req = LLMRequest(role="t", instructions="s", parts=[], schema=Schema)
    ok = await LLMCaller(Scripted(["not json", '```json\n{"answer": "yes"}\n```'])).call(
        req, Schema(answer="fb")
    )
    assert ok.ok and ok.meta.repaired and ok.data.answer == "yes"
    bad = await LLMCaller(Scripted(["nope", "{}"])).call(req, Schema(answer="fallback"))
    assert not bad.ok and bad.meta.fallback and bad.data.answer == "fallback"


async def test_onprem_glimmer_text_and_routing(ctx, monkeypatch, tmp_path):
    from app.providers.mock import MockVisionLanguage
    from app.providers.onprem import OnPremVisionLanguage, RoutingVisionLanguage

    monkeypatch.setenv("LOCAL_LLM_URL", "http://gpu-box.local:8001/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "muse-glimmer-q4")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer": "ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    onprem = OnPremVisionLanguage(
        ctx.settings, httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    router = RoutingVisionLanguage(onprem, MockVisionLanguage())
    raw = await router.complete(
        LLMRequest(
            role="sentence_builder",
            instructions="s",
            parts=[Part("text", text="KUCING")],
            schema=Schema,
        )
    )
    assert seen["url"] == "http://gpu-box.local:8001/v1/chat/completions"
    assert (
        seen["body"]["model"] == "muse-glimmer-q4"
        and "JSON schema" in seen["body"]["messages"][0]["content"]
    )
    assert raw.provider == "onprem" and json.loads(raw.text) == {"answer": "ok"}
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"0")
    raw2 = await router.complete(
        LLMRequest(
            role="blind_judge", instructions="s", parts=[Part("video", path=clip)], schema=JudgeOut
        )
    )
    assert raw2.provider == "mock"  # media never reaches the text-only model


async def test_privacy_mode_resolution(ctx, monkeypatch):
    from app.providers.registry import Mode

    assert ctx.hub.resolve(Mode.PRIVACY).effective == Mode.MOCK
    monkeypatch.setenv("LOCAL_LLM_URL", "http://gpu-box.local:8001/v1")
    info = ctx.hub.resolve(Mode.PRIVACY)
    assert info.effective == Mode.PRIVACY and "Glimmer" in info.reason
    vl = ctx.hub.vision_language(Mode.PRIVACY)
    assert vl.provider == "onprem+mock"
    assert ctx.hub.tracker(Mode.PRIVACY).provider == "local"


async def test_modal_hosts_spark_open_when_no_baseten_key(ctx, monkeypatch):
    from app.providers.registry import Mode

    monkeypatch.setenv("MODAL_SPARK_URL", "https://example--muse-spark-open.modal.run/v1")
    info = ctx.hub.resolve(Mode.PRIVACY)
    assert info.effective == Mode.PRIVACY and "Modal" in info.reason
    vl = ctx.hub.vision_language(Mode.PRIVACY)
    assert vl.provider == "modal" and vl.model.startswith("meta-models/Muse-Spark-Open")
