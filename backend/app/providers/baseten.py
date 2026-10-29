"""Privacy mode: Muse Spark Open (open weights) on Baseten, OpenAI-compatible Chat Completions.

Facts from the Baseten docs (docs/API_NOTES.md section 10): structured output is NOT enforced, so the
JSON schema goes into the instructions and our validator repairs once; reasoning is always on
(`low` is the fastest level); video is sampled at <= 96 frames and its audio track is ignored, so
room audio is sent as a separate `audio_url` part. Synchronous Model API requests fall under
Baseten's zero-data-retention policy.

Model id: the organizer asked for `meta-models/muse-spark-open-1026`; the docs only list
`meta-models/muse-spark-open`. We use the configured id and fall back to the documented slug on 404.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.perception.media import probe_duration, run_async

from .base import (
    LLMRequest,
    Part,
    ProviderError,
    RawResponse,
    Segment,
    Transcriber,
    TranscriptResult,
    Usage,
    VisionLanguage,
)
from .meta_api import _data_url, _post_with_retries, strict_schema

DOCUMENTED_SLUG = "meta-models/muse-spark-open"

# Muse Spark Open on Baseten samples video at 2 frames per second of video time, at most 96 per
# video, and has no request field for the rate (measured 2026-10-29: a 12 s clip costs the same
# tokens at 2 and 4 fps, and a numbered 48-frame clip played at 2 fps came back complete). Where a
# role asks for a denser rate (`_video_fps`, Meta's `fps` field), the clip is slowed instead, up to
# providers.baseten.video_fps, so each sampled frame is 1/fps s of real time, and the model is told.
SAMPLED_FPS = 2.0
MAX_FRAMES = 96


async def slowed(part: Part, fps: float) -> Part:
    """The video part re-timed: frames at `fps`, played at SAMPLED_FPS, with a note on its label.
    At 2 fps three quick eyebrow raises read as one long lift, so the emergency signal was missed.
    Judge-only sweep, 13 generated clips twice each: 2 fps 17/26 right (emergency 0/4), 4 fps
    25/26 (emergency 4/4). Slower still, or with each frame's real time printed on it, the judge
    read blinks as held eye closures (docs/DETECTOR_EVAL_GENERATED_PRIVACY.md)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = part.path
        if part.data is not None:
            src = Path(tmp) / "in.mp4"
            src.write_bytes(part.data)
        if src is None:
            return part
        duration = await asyncio.to_thread(probe_duration, src)
        fps = min(fps, MAX_FRAMES / max(duration, 0.1))
        if fps <= SAMPLED_FPS:
            return part
        k = fps / SAMPLED_FPS
        out = Path(tmp) / "slow.mp4"
        await run_async(
            [
                "ffmpeg", "-y", "-v", "error", "-i", str(src),
                "-vf", f"fps={fps:.4f},setpts={k:.4f}*PTS", "-r", f"{SAMPLED_FPS:g}",
                "-frames:v", str(MAX_FRAMES), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(out),
            ]
        )  # fmt: skip
        note = f"(Played {k:.3g}x slower than real time: divide every duration you see by {k:.3g}.)"
        label = f"{part.label} {note}" if part.label else note
        return dataclasses.replace(part, path=None, data=out.read_bytes(), label=label)


class BasetenVisionLanguage(VisionLanguage):
    provider = "baseten"
    # Muse Spark Open: 400 "Too many videos: 5 (max 2)" (observed; also in Baseten's docs)
    max_videos = 2

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        import os

        cfg = settings.providers.get("baseten", {})
        self.settings = settings
        self.max_retries = int(cfg.get("max_retries", 2))
        self.video_fps = float(cfg.get("video_fps", 4))
        self.timeout = float(cfg.get("timeout_s", 45))
        self.client = client or httpx.AsyncClient()
        modal_url = os.environ.get("MODAL_SPARK_URL", "").strip()
        if settings.baseten_api_key:
            self.base_url = cfg.get("base_url", "https://inference.baseten.co/v1").rstrip("/")
            self.headers = {"Authorization": f"Bearer {settings.baseten_api_key}"}
            self.model = settings.models["spark_open"]
        elif modal_url:
            # Modal also serves Muse Spark Open on an OpenAI-compatible endpoint (docs/API_NOTES.md section 11).
            self.provider = "modal"
            self.base_url = modal_url.rstrip("/")
            key = os.environ.get("MODAL_SPARK_KEY", "").strip()
            self.headers = {"Authorization": f"Bearer {key}"} if key else {}
            self.model = settings.models.get(
                "spark_open_modal", "meta-models/Muse-Spark-Open-816B-A42B"
            )
        else:
            raise ProviderError("BASETEN_API_KEY (or MODAL_SPARK_URL) is not set")

    def model_for(self, req: LLMRequest) -> str:
        return self.model

    def build_body(self, req: LLMRequest, repair: str | None = None) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for p in req.parts:
            if p.kind == "text":
                content.append({"type": "text", "text": p.text or ""})
                continue
            if p.label:  # e.g. "YES clip 1": the describer must know which clip shows what
                content.append({"type": "text", "text": p.label})
            if p.kind == "image":
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(p.path, p.data, p.mime or "image/jpeg")},
                    }
                )
            elif p.kind == "video":
                content.append(
                    {
                        "type": "video_url",
                        "video_url": {"url": _data_url(p.path, p.data, "video/mp4")},
                    }
                )
            elif p.kind == "audio":
                content.append(
                    {
                        "type": "audio_url",
                        "audio_url": {"url": _data_url(p.path, p.data, p.mime or "audio/wav")},
                    }
                )
        schema = json.dumps(strict_schema(req.schema), separators=(",", ":"))
        system = f"{req.instructions}\n\nReply with ONLY a JSON object matching this JSON schema:\n{schema}"
        if repair:
            content.append({"type": "text", "text": repair})
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "reasoning_effort": "low",
            "max_tokens": max(req.max_output_tokens, 1500),
        }

    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse:
        fps = min(req.context.get("_video_fps") or 0, self.video_fps)
        if fps > SAMPLED_FPS:
            parts = [await slowed(p, fps) if p.kind == "video" else p for p in req.parts]
            req = dataclasses.replace(req, parts=parts)
        body = self.build_body(req, repair)
        t0 = time.perf_counter()
        try:
            resp = await _post_with_retries(
                self.client,
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=body,
                max_retries=self.max_retries,
                timeout=req.timeout_s + 15,
            )
        except ProviderError as exc:
            if exc.status == 404 and self.provider == "baseten" and self.model != DOCUMENTED_SLUG:
                self.model = DOCUMENTED_SLUG
                body["model"] = DOCUMENTED_SLUG
                resp = await _post_with_retries(
                    self.client,
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json=body,
                    max_retries=self.max_retries,
                    timeout=req.timeout_s + 15,
                )
            else:
                raise
        data = resp.json()
        u = data.get("usage") or {}
        usage = Usage(
            int(u.get("prompt_tokens", 0) or 0),
            int(u.get("completion_tokens", 0) or 0),
            int((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0),
        )
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return RawResponse(
            text,
            self.provider,
            body["model"],
            (time.perf_counter() - t0) * 1000,
            usage,
            {"id": data.get("id")},
        )


class BasetenTranscriber(Transcriber):
    """Room audio through Muse Spark Open's audio input (privacy mode has no hosted open ASR)."""

    provider = "baseten"

    def __init__(self, vl: BasetenVisionLanguage) -> None:
        self.vl = vl

    async def transcribe(
        self, audio: Path, language: str | None, keywords: list[str]
    ) -> TranscriptResult:
        from pydantic import BaseModel, Field

        class Seg(BaseModel):
            speaker: str
            text: str

        class Out(BaseModel):
            segments: list[Seg] = Field(default_factory=list)

        from .base import Part
        from .llm import extract_json

        lang = {"id": "Indonesian", "en": "English"}.get(language or "", "the spoken language")
        req = LLMRequest(
            role="room_transcriber",
            instructions=(
                f"Transcribe this hospital-room audio verbatim in {lang}. Label speakers A, B, C in order of "
                f"first appearance. Names that may occur: {', '.join(keywords) or 'none'}. Do not summarise."
            ),
            parts=[Part("audio", path=audio, mime="audio/wav")],
            schema=Out,
            max_output_tokens=2000,
        )
        raw = await self.vl.complete(req)
        out = Out.model_validate(extract_json(raw.text))
        return TranscriptResult(
            [Segment(s.speaker, s.text) for s in out.segments if s.text.strip()],
            self.provider,
            raw.model,
            language,
            0.0,
            raw.latency_ms,
            raw.usage,
        )
