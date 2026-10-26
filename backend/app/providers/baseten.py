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

import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

from .base import (
    LLMRequest,
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


class BasetenVisionLanguage(VisionLanguage):
    provider = "baseten"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        import os

        cfg = settings.providers.get("baseten", {})
        self.settings = settings
        self.max_retries = int(cfg.get("max_retries", 2))
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
            elif p.kind == "image":
                if p.label:
                    content.append({"type": "text", "text": p.label})
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
