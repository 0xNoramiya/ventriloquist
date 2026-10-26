"""Structured LLM calls: validate, repair once, then fall back safely (brief Section 7 and 15)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMRequest, ProviderError, RawResponse, Usage, VisionLanguage

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> tuple[str, str]:
    """Return (prompt text, version). Prompts are versioned .md files, one per role."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)", text, re.M)
    return text, (m.group(1) if m else "0")


def extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


@dataclass
class CallMeta:
    role: str
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    usage: Usage = field(default_factory=Usage)
    usd: float = 0.0
    repaired: bool = False
    fallback: bool = False
    error: str | None = None
    prompt_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "usd": round(self.usd, 6),
            "repaired": self.repaired,
            "fallback": self.fallback,
            "error": self.error,
            "prompt_version": self.prompt_version,
        }


@dataclass
class RoleResult(Generic[T]):
    data: T
    meta: CallMeta

    @property
    def ok(self) -> bool:
        return not self.meta.fallback


class LLMCaller:
    """Wraps a VisionLanguage provider with validation, one repair retry, fallback and cost logging."""

    def __init__(self, provider: VisionLanguage, cost_hook: Any = None) -> None:
        self.provider = provider
        self.cost_hook = cost_hook  # callable(raw: RawResponse, role: str) -> float

    async def call(self, req: LLMRequest, fallback: T, prompt_version: str = "") -> RoleResult[T]:
        meta = CallMeta(role=req.role, prompt_version=prompt_version)
        repair: str | None = None
        for attempt in range(2):
            try:
                raw = await self.provider.complete(req, repair=repair)
            except ProviderError as exc:
                meta.error = f"provider: {exc}"
                log.warning("role %s provider error: %s", req.role, exc)
                break
            except Exception as exc:  # network stack errors, timeouts
                meta.error = f"{type(exc).__name__}: {exc}"
                log.warning("role %s failed: %s", req.role, meta.error)
                break
            self._account(meta, raw, req.role)
            try:
                data = req.schema.model_validate(extract_json(raw.text))
                meta.repaired = attempt > 0
                return RoleResult(data, meta)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                meta.error = f"invalid output: {str(exc)[:300]}"
                repair = (
                    "Your previous reply was not valid. Reply again with ONLY a JSON object that "
                    f"matches the schema. Problem: {str(exc)[:400]}"
                )
        meta.fallback = True
        return RoleResult(fallback, meta)

    def _account(self, meta: CallMeta, raw: RawResponse, role: str) -> None:
        meta.provider = raw.provider
        meta.model = raw.model
        meta.latency_ms += raw.latency_ms
        meta.usage = Usage(
            meta.usage.input_tokens + raw.usage.input_tokens,
            meta.usage.output_tokens + raw.usage.output_tokens,
            meta.usage.cached_tokens + raw.usage.cached_tokens,
        )
        if self.cost_hook is not None:
            meta.usd += float(self.cost_hook(raw, role))
