"""On-premises privacy tier: Muse Glimmer (open weights, Apache 2.0, 30B dense) on hospital hardware.

Any OpenAI-compatible server works (vLLM, llama.cpp server, Ollama). Set LOCAL_LLM_URL (and
LOCAL_LLM_MODEL if the server names the model differently). Muse Glimmer takes the text-only roles
(prior builder, question proposer, spelling completer, sentence builder, sensitive classifier,
memory curator and selector). Roles with images or video go to Muse Spark Open on Baseten when a key
is set; otherwise they stay on-device (mock describer/judge, local optical-flow tracker), so in that
configuration nothing leaves the building.

UNTESTED against a real Glimmer server (none available while building); covered by contract tests
against a mock OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from app.config import Settings

from .base import LLMRequest, ProviderError, RawResponse, Usage, VisionLanguage
from .meta_api import _post_with_retries, strict_schema


class OnPremVisionLanguage(VisionLanguage):
    provider = "onprem"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        url = os.environ.get("LOCAL_LLM_URL", "").strip() or settings.providers.get(
            "local_llm", {}
        ).get("base_url", "")
        if not url:
            raise ProviderError("LOCAL_LLM_URL is not set")
        self.base_url = url.rstrip("/")
        self.model = os.environ.get("LOCAL_LLM_MODEL", "").strip() or settings.models.get(
            "glimmer", "muse-glimmer"
        )
        key = os.environ.get("LOCAL_LLM_KEY", "").strip()
        self.headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.client = client or httpx.AsyncClient()

    def model_for(self, req: LLMRequest) -> str:
        return self.model

    def build_body(self, req: LLMRequest, repair: str | None = None) -> dict[str, Any]:
        if any(p.kind != "text" for p in req.parts):
            raise ProviderError("the on-prem text model only takes text parts")
        schema = json.dumps(strict_schema(req.schema), separators=(",", ":"))
        user = "\n\n".join(p.text or "" for p in req.parts)
        if repair:
            user += f"\n\n{repair}"
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": f"{req.instructions}\n\nReply with ONLY a JSON object matching this JSON schema:\n{schema}",
                },
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": max(req.max_output_tokens, 800),
        }

    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse:
        body = self.build_body(req, repair)
        t0 = time.perf_counter()
        resp = await _post_with_retries(
            self.client,
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            json=body,
            max_retries=1,
            timeout=req.timeout_s + 30,
        )
        data = resp.json()
        u = data.get("usage") or {}
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return RawResponse(
            text,
            self.provider,
            self.model,
            (time.perf_counter() - t0) * 1000,
            Usage(int(u.get("prompt_tokens", 0) or 0), int(u.get("completion_tokens", 0) or 0)),
        )


class RoutingVisionLanguage(VisionLanguage):
    """Text-only requests to one provider, requests with media to another."""

    def __init__(self, text: VisionLanguage, media: VisionLanguage) -> None:
        self.text = text
        self.media = media
        self.provider = f"{text.provider}+{media.provider}"
        self.max_videos = media.max_videos

    def _pick(self, req: LLMRequest) -> VisionLanguage:
        return self.media if any(p.kind != "text" for p in req.parts) else self.text

    def model_for(self, req: LLMRequest) -> str:
        return self._pick(req).model_for(req)

    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse:
        return await self._pick(req).complete(req, repair)
