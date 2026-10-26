"""Optional: SAM 3.1 open weights (`facebook/sam3.1`) self-hosted on Modal for privacy mode.

Modal hosts no SAM 3.1 endpoint (docs/API_NOTES.md section 11), so this client talks to our own
Modal app (`scripts/modal_sam_app.py`). Contract: POST {MODAL_SAM_URL}/track, multipart with
`video` (MP4) and `prompt`; the reply is the same SAM wire text the Meta API returns
(`{"text": "<0f>0<|box;...|>...", "fps": 15}`), so parsing is shared. Weights are never committed.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from app.config import Settings

from .base import ProviderError, Tracker, TrackResult, Usage
from .meta_api import _post_with_retries, parse_sam_text


class ModalSamTracker(Tracker):
    provider = "modal"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.modal_sam_url:
            raise ProviderError("MODAL_SAM_URL is not set")
        self.url = settings.modal_sam_url.rstrip("/")
        self.model = settings.models.get("sam_open", "facebook/sam3.1")
        self.client = client or httpx.AsyncClient()

    async def track(self, video: Path, prompt: str) -> TrackResult:
        t0 = time.perf_counter()
        resp = await _post_with_retries(
            self.client,
            f"{self.url}/track",
            max_retries=1,
            timeout=60,
            files={"video": (video.name, video.read_bytes(), "video/mp4")},
            data={"prompt": prompt},
        )
        data = resp.json()
        fps = float(data.get("fps") or 15.0)
        frames = parse_sam_text(data.get("text", ""), fps, prompt)
        return TrackResult(
            frames,
            self.provider,
            self.model,
            prompt,
            (time.perf_counter() - t0) * 1000,
            Usage(units=len(frames)),
        )
