"""Provider interfaces: VisionLanguage, Tracker, Transcriber, MemoryModel.

Implementations: meta_api (Meta Model API), baseten (Muse Spark Open, privacy mode),
modal_sam (optional SAM 3.1 open weights), local (on-device optical flow, no model) and mock.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class Part:
    kind: Literal["text", "image", "video", "audio"]
    text: str | None = None
    path: Path | None = None
    data: bytes | None = None
    mime: str | None = None
    label: str | None = None  # e.g. "t=1.25s" for a frame


@dataclass
class LLMRequest:
    role: str
    instructions: str
    parts: list[Part]
    schema: type[BaseModel]
    # Structured input for the mock; never sent.
    context: dict[str, Any] = field(default_factory=dict)
    reasoning_effort: str | None = None
    max_output_tokens: int = 900
    timeout_s: float = 30.0
    model_key: str = "spark"  # config.yaml models.<key>


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    units: float = 0.0  # frames, images, audio minutes...


@dataclass
class RawResponse:
    text: str
    provider: str
    model: str
    latency_ms: float
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)


class VisionLanguage(ABC):
    provider: str = "abstract"
    max_videos: int = 5  # per request; Muse Spark answers 400 above 5 (docs/API_NOTES.md)

    @abstractmethod
    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse: ...

    def model_for(self, req: LLMRequest) -> str:
        return ""


# Muse Wonder uses the same text-in/JSON-out contract.
MemoryModel = VisionLanguage


@dataclass
class TrackedObject:
    track_id: int
    box: tuple[float, float, float, float]  # normalised x0, y0, x1, y1
    score: float = 1.0
    mask_area: float | None = None  # fraction of the frame, when masks are available


@dataclass
class FrameTracks:
    t: float
    objects: list[TrackedObject] = field(default_factory=list)


@dataclass
class TrackResult:
    frames: list[FrameTracks]
    provider: str
    model: str
    prompt: str
    latency_ms: float = 0.0
    usage: Usage = field(default_factory=Usage)
    features: list[list[float]] | None = None  # set by trackers that compute features directly
    feature_names: list[str] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_overlay(self, max_frames: int = 60) -> dict[str, Any]:
        step = max(1, len(self.frames) // max_frames)
        return {
            "provider": self.provider,
            "prompt": self.prompt,
            "frames": [
                {
                    "t": round(f.t, 3),
                    "objects": [
                        {
                            "id": o.track_id,
                            "box": [round(v, 4) for v in o.box],
                            "score": round(o.score, 3),
                        }
                        for o in f.objects
                    ],
                }
                for f in self.frames[::step]
            ],
        }


class Tracker(ABC):
    provider: str = "abstract"

    @abstractmethod
    async def track(self, video: Path, prompt: str) -> TrackResult: ...


@dataclass
class Segment:
    speaker: str
    text: str
    start: float | None = None
    end: float | None = None


@dataclass
class TranscriptResult:
    segments: list[Segment]
    provider: str
    model: str
    language: str | None = None
    duration_s: float = 0.0
    latency_ms: float = 0.0
    usage: Usage = field(default_factory=Usage)


class Transcriber(ABC):
    provider: str = "abstract"

    @abstractmethod
    async def transcribe(
        self, audio: Path, language: str | None, keywords: list[str]
    ) -> TranscriptResult: ...
