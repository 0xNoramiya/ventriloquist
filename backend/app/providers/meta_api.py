"""Meta Model API adapters (verified shapes in docs/API_NOTES.md).

* Muse Spark / Muse Wonder: POST /v1/responses with json_schema structured output, `store: false`
  (the default `true` would keep patient data server-side), reasoning effort `minimal` by default.
* SAM 3.1: POST /v1/responses with a noun-phrase prompt and an inline MP4; the reply is SAM's
  special-token text grammar, one line per frame: `<Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..;c=..|>...`
* Muse Voice Transcribe: POST /v1/asr/transcribe, multipart (request JSON + WAV, mono s16 16/24 kHz),
  always with `languageBias` (Indonesian returns an empty transcript without it) and name keywords.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import Settings

from .base import (
    FrameTracks,
    LLMRequest,
    ProviderError,
    RawResponse,
    Segment,
    TrackedObject,
    Tracker,
    TrackResult,
    Transcriber,
    TranscriptResult,
    Usage,
    VisionLanguage,
)

RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 529}
_DROP_KEYS = {
    "title",
    "default",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "maxItems",
    "minItems",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "format",
    "pattern",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema → the strict subset: refs inlined, every key required, no extra keys.
    Optional fields become nullable types; length/range limits are enforced by pydantic afterwards."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            if "anyOf" in node:
                variants = [walk(v) for v in node["anyOf"]]
                non_null = [v for v in variants if v.get("type") != "null"]
                if len(non_null) == 1 and len(variants) == 2:
                    v = dict(non_null[0])
                    t = v.get("type")
                    if isinstance(t, str):
                        v["type"] = [t, "null"]
                    return v
                return {"anyOf": variants}
            out = {k: walk(v) for k, v in node.items() if k not in _DROP_KEYS and k != "$defs"}
            if out.get("type") == "object":
                props = out.get("properties", {})
                out["required"] = list(props)
                out["additionalProperties"] = (
                    False if props else out.get("additionalProperties", False)
                )
                if not props and isinstance(node.get("additionalProperties"), dict):
                    # free-form string maps: keep as an object of strings
                    out["additionalProperties"] = walk(node["additionalProperties"])
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(raw)


def _data_url(path: Path | None, data: bytes | None, mime: str) -> str:
    blob = data if data is not None else (path.read_bytes() if path else b"")
    return f"data:{mime};base64,{base64.b64encode(blob).decode()}"


async def _post_with_retries(
    client: httpx.AsyncClient, url: str, *, max_retries: int, timeout: float, **kwargs: Any
) -> httpx.Response:
    delay = 0.75
    for attempt in range(max_retries + 1):
        try:
            resp = await client.post(url, timeout=timeout, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= max_retries:
                raise ProviderError(f"{type(exc).__name__}: {exc}", retryable=True) from exc
        else:
            if resp.status_code < 400:
                return resp
            if resp.status_code not in RETRYABLE or attempt >= max_retries:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:400]}",
                    status=resp.status_code,
                    retryable=resp.status_code in RETRYABLE,
                )
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 8.0)
        await asyncio.sleep(delay + random.uniform(0, 0.25))
        delay *= 2
    raise ProviderError("unreachable")


class _MetaBase:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        cfg = settings.providers.get("meta_api", {})
        self.settings = settings
        self.base_url = cfg.get("base_url", "https://api.meta.ai/v1").rstrip("/")
        self.max_retries = int(cfg.get("max_retries", 2))
        self.timeout = float(cfg.get("timeout_s", 30))
        if not settings.model_api_key:
            raise ProviderError("MODEL_API_KEY is not set")
        self.headers = {"Authorization": f"Bearer {settings.model_api_key}"}
        self.client = client or httpx.AsyncClient()


def parse_responses_output(body: dict[str, Any]) -> str:
    for item in body.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return part.get("text", "")
    return ""


def responses_usage(body: dict[str, Any]) -> Usage:
    u = body.get("usage") or {}
    return Usage(
        input_tokens=int(u.get("input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
        cached_tokens=int((u.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0),
        units=float(u.get("video_frames_processed", 0) or u.get("images_processed", 0) or 0),
    )


class MetaVisionLanguage(_MetaBase, VisionLanguage):
    """Muse Spark and Muse Wonder through the Responses API."""

    provider = "meta"

    def model_for(self, req: LLMRequest) -> str:
        return self.settings.models[req.model_key]

    def build_body(self, req: LLMRequest, repair: str | None = None) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for p in req.parts:
            if p.kind == "text":
                content.append({"type": "input_text", "text": p.text or ""})
            elif p.kind == "image":
                if p.label:
                    content.append({"type": "input_text", "text": p.label})
                content.append(
                    {
                        "type": "input_image",
                        "image_url": _data_url(p.path, p.data, p.mime or "image/jpeg"),
                    }
                )
            elif p.kind == "video":
                part: dict[str, Any] = {
                    "type": "input_video",
                    "video_url": _data_url(p.path, p.data, "video/mp4"),
                }
                fps = req.context.get("_video_fps")
                if fps:
                    part["fps"] = fps
                if p.label:
                    content.append({"type": "input_text", "text": p.label})
                content.append(part)
        if repair:
            content.append({"type": "input_text", "text": repair})
        return {
            "model": self.model_for(req),
            "store": False,
            "instructions": req.instructions,
            "input": [{"role": "user", "content": content}],
            "reasoning": {"effort": req.reasoning_effort or "minimal"},
            "max_output_tokens": max(req.max_output_tokens, 600),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": req.role,
                    "schema": strict_schema(req.schema),
                    "strict": True,
                }
            },
        }

    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse:
        body = self.build_body(req, repair)
        t0 = time.perf_counter()
        resp = await _post_with_retries(
            self.client,
            f"{self.base_url}/responses",
            headers=self.headers,
            json=body,
            max_retries=self.max_retries,
            timeout=req.timeout_s,
        )
        data = resp.json()
        latency = (time.perf_counter() - t0) * 1000
        return RawResponse(
            parse_responses_output(data),
            self.provider,
            body["model"],
            latency,
            responses_usage(data),
            {
                "id": data.get("id"),
                "status": data.get("status"),
                "incomplete": (data.get("incomplete_details") or {}).get("reason"),
            },
        )


_SAM_FRAME = re.compile(r"<(\d+)f>")
_SAM_BOX = re.compile(r"(\d+)<\|box;([^|]*)\|>")


def parse_sam_text(text: str, fps: float, prompt: str) -> list[FrameTracks]:
    frames: list[FrameTracks] = []
    for line in text.splitlines():
        line = line.strip()
        fm = _SAM_FRAME.match(line)
        if not fm:
            continue
        idx = int(fm.group(1))
        objs = []
        for m in _SAM_BOX.finditer(line, fm.end()):
            kv = dict(item.split("=", 1) for item in m.group(2).split(";") if "=" in item)
            w, h = float(kv.get("w", 1)), float(kv.get("h", 1))
            x1, y1, x2, y2 = (float(kv[k]) for k in ("x1", "y1", "x2", "y2"))
            objs.append(
                TrackedObject(
                    int(m.group(1)),
                    (x1 / w, y1 / h, (x2 + 1) / w, (y2 + 1) / h),
                    float(kv.get("c", 1.0)),
                )
            )
        frames.append(FrameTracks(idx / fps, objs))
    return frames


class MetaSamTracker(_MetaBase, Tracker):
    provider = "meta"

    async def track(self, video: Path, prompt: str) -> TrackResult:
        from app.perception.media import read_frames

        fps = read_frames(video, max_frames=2).fps or 15.0
        model = self.settings.models["sam"]
        body = {
            "model": model,
            "store": False,
            "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_video", "video_url": _data_url(video, None, "video/mp4")},
                    ],
                }
            ],
        }
        t0 = time.perf_counter()
        resp = await _post_with_retries(
            self.client,
            f"{self.base_url}/responses",
            headers=self.headers,
            json=body,
            max_retries=self.max_retries,
            timeout=self.timeout,
        )
        data = resp.json()
        text = ""
        for item in data.get("output", []):
            for part in item.get("content", []) or []:
                text += part.get("text", "") or ""
        usage = responses_usage(data)
        return TrackResult(
            parse_sam_text(text, fps, prompt),
            self.provider,
            model,
            prompt,
            (time.perf_counter() - t0) * 1000,
            usage,
            raw={"id": data.get("id")},
        )


LANGUAGE_NAMES = {"id": "Indonesian", "en": "English", "ms": "Malay"}


class MetaTranscriber(_MetaBase, Transcriber):
    provider = "meta"

    async def transcribe(
        self, audio: Path, language: str | None, keywords: list[str]
    ) -> TranscriptResult:
        model = self.settings.models["transcribe"]
        request = {"model": model, "audioEncoding": "WAV", "mode": "DIARIZATION"}
        if language:
            request["languageBias"] = [LANGUAGE_NAMES.get(language, language)]
        if keywords:
            request["keywords"] = keywords[:20]
        files = {
            "request": (None, json.dumps(request), "application/json"),
            "audio": (audio.name, audio.read_bytes(), "audio/wav"),
        }
        t0 = time.perf_counter()
        resp = await _post_with_retries(
            self.client,
            f"{self.base_url}/asr/transcribe",
            headers=self.headers,
            files=files,
            max_retries=self.max_retries,
            timeout=self.timeout,
        )
        data = resp.json()
        turns = data.get("turns") or []
        segments = [
            Segment(
                str(t.get("speaker") or "room"),
                (t.get("transcript") or "").strip(),
                (t.get("startMs") or 0) / 1000,
                (t.get("endMs") or 0) / 1000,
            )
            for t in turns
            if (t.get("transcript") or "").strip()
        ]
        if not segments and (data.get("transcript") or "").strip():
            segments = [Segment("room", data["transcript"].strip())]
        duration = float(data.get("audioDurationMs") or 0) / 1000
        return TranscriptResult(
            segments,
            self.provider,
            model,
            language,
            duration,
            (time.perf_counter() - t0) * 1000,
            Usage(units=duration / 60),
        )
