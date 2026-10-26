"""Provider selection by mode (mock | live | privacy), feature flags and the budget guard."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.config import Settings
from app.storage import Store

from .base import (
    ProviderError,
    RawResponse,
    Tracker,
    TrackResult,
    Transcriber,
    TranscriptResult,
    VisionLanguage,
)
from .cost import CostMeter, estimate_usd
from .llm import LLMCaller
from .mock import MockTranscriber, MockVisionLanguage

log = logging.getLogger(__name__)


class Mode(StrEnum):
    MOCK = "mock"
    LIVE = "live"
    PRIVACY = "privacy"


FLAG_NAMES = ("use_sam", "use_spark_judge", "use_transcribe", "use_wonder", "idle_watch")


@dataclass
class ModeInfo:
    requested: Mode
    effective: Mode
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": str(self.requested),
            "effective": str(self.effective),
            "reason": self.reason,
        }


class ProviderHub:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.cost = CostMeter(settings, store)
        self._http: Any = None
        self._mock_vl = MockVisionLanguage()
        self._mock_tr = MockTranscriber()
        self._cache: dict[str, Any] = {}

    @property
    def http(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.AsyncClient()
        return self._http

    @property
    def _local_tracker(self) -> Tracker:
        from .local import LocalFlowTracker

        return self._get("local_tracker", LocalFlowTracker)

    # --------------------------------------------------------------- settings
    def app_mode(self) -> str:
        return self.store.kv_get("app_mode", self.settings.app_mode)

    def privacy_default(self) -> bool:
        return bool(self.store.kv_get("privacy_mode", self.settings.features.privacy_mode))

    def flag(self, name: str) -> bool:
        default = getattr(self.settings.features, name)
        if name == "idle_watch" and self.app_mode() == "mock":
            default = self.settings.features.idle_watch_mock
        return bool(self.store.kv_get(f"flag:{name}", default))

    def flags(self) -> dict[str, bool]:
        return {n: self.flag(n) for n in FLAG_NAMES}

    def requested_mode(self, privacy: bool | None = None) -> Mode:
        if privacy if privacy is not None else self.privacy_default():
            return Mode.PRIVACY
        return Mode.LIVE if self.app_mode() == "live" else Mode.MOCK

    def resolve(self, requested: Mode) -> ModeInfo:
        if requested == Mode.MOCK:
            return ModeInfo(requested, Mode.MOCK, "mock mode")
        if not self.cost.allows_live():
            return ModeInfo(
                requested, Mode.MOCK, "budget guard: 90% of budget spent, switched to mock"
            )
        if requested == Mode.LIVE and not self.settings.model_api_key:
            return ModeInfo(requested, Mode.MOCK, "MODEL_API_KEY missing")
        if requested == Mode.PRIVACY:
            if self.partner_open():
                partner = "Baseten" if self.settings.baseten_api_key else "Modal"
                if self.onprem_url():
                    return ModeInfo(
                        requested,
                        requested,
                        f"Muse Glimmer on-prem for text, Muse Spark Open on {partner} for media",
                    )
                return ModeInfo(requested, requested, f"Muse Spark Open on {partner}")
            if self.settings.baseten_api_key and self.onprem_url():
                return ModeInfo(
                    requested,
                    requested,
                    "Muse Glimmer on-prem for text, Muse Spark Open on Baseten for media",
                )
            if self.settings.baseten_api_key:
                return ModeInfo(requested, requested, "Muse Spark Open on Baseten")
            if self.onprem_url():
                return ModeInfo(requested, requested, "Muse Glimmer on-prem; media stays on-device")
            return ModeInfo(
                requested,
                Mode.MOCK,
                "no BASETEN_API_KEY or LOCAL_LLM_URL: privacy mode stays on-device (mock models, local motion tracker)",
            )
        return ModeInfo(requested, requested, "ok")

    def partner_open(self) -> bool:
        import os

        return bool(self.settings.baseten_api_key or os.environ.get("MODAL_SPARK_URL", "").strip())

    def onprem_url(self) -> str:
        import os

        return os.environ.get("LOCAL_LLM_URL", "").strip() or str(
            self.settings.providers.get("local_llm", {}).get("base_url", "") or ""
        )

    # -------------------------------------------------------------- providers
    def _get(self, key: str, factory: Any) -> Any:
        if key not in self._cache:
            self._cache[key] = factory()
        return self._cache[key]

    def vision_language(self, mode: Mode) -> VisionLanguage:
        info = self.resolve(mode)
        try:
            if info.effective == Mode.LIVE:
                from .meta_api import MetaVisionLanguage

                return self._get("meta_vl", lambda: MetaVisionLanguage(self.settings, self.http))
            if info.effective == Mode.PRIVACY:
                return self._privacy_vl()
        except ProviderError as exc:
            log.warning("falling back to mock VL: %s", exc)
        return self._mock_vl

    def _privacy_vl(self) -> VisionLanguage:
        """Media to Muse Spark Open (Baseten) or nowhere; text to Muse Glimmer on-prem if configured."""
        media: VisionLanguage = self._mock_vl
        if self.partner_open():
            from .baseten import BasetenVisionLanguage

            media = self._get("baseten_vl", lambda: BasetenVisionLanguage(self.settings, self.http))
        if not self.onprem_url():
            return media
        from .onprem import OnPremVisionLanguage, RoutingVisionLanguage

        text = self._get("onprem_vl", lambda: OnPremVisionLanguage(self.settings, self.http))
        return self._get("privacy_router", lambda: RoutingVisionLanguage(text, media))

    def tracker(self, mode: Mode) -> Tracker:
        info = self.resolve(mode)
        if not self.flag("use_sam"):
            return self._local_tracker
        try:
            if info.effective == Mode.LIVE:
                from .meta_api import MetaSamTracker

                return self._get("meta_sam", lambda: MetaSamTracker(self.settings, self.http))
            if info.requested == Mode.PRIVACY and self.settings.modal_sam_url:
                from .modal_sam import ModalSamTracker

                return self._get("modal_sam", lambda: ModalSamTracker(self.settings, self.http))
        except ProviderError as exc:
            log.warning("falling back to local tracker: %s", exc)
        return self._local_tracker

    def transcriber(self, mode: Mode) -> Transcriber:
        info = self.resolve(mode)
        try:
            if info.effective == Mode.LIVE and self.flag("use_transcribe"):
                from .meta_api import MetaTranscriber

                return self._get("meta_tr", lambda: MetaTranscriber(self.settings, self.http))
            if (
                info.effective == Mode.PRIVACY
                and self.flag("use_transcribe")
                and self.partner_open()
            ):
                from .baseten import BasetenTranscriber, BasetenVisionLanguage

                vl = self._get(
                    "baseten_vl", lambda: BasetenVisionLanguage(self.settings, self.http)
                )
                return self._get("baseten_tr", lambda: BasetenTranscriber(vl))
        except ProviderError as exc:
            log.warning("falling back to mock transcriber: %s", exc)
        return self._mock_tr

    def caller(self, mode: Mode) -> LLMCaller:
        return LLMCaller(self.vision_language(mode), cost_hook=self._llm_cost)

    # ------------------------------------------------------------------ cost
    def _llm_cost(self, raw: RawResponse, role: str) -> float:
        if raw.provider == "mock":
            return 0.0
        usd = estimate_usd(self.settings, raw.model, raw.usage, "tokens")
        self.cost.record(raw.provider, raw.model, role, usd, raw.usage, raw.latency_ms, raw.raw)
        return usd

    def record_track(self, result: TrackResult, role: str = "tracker") -> float:
        if result.provider in ("local", "mock"):
            return 0.0
        kind = "video_frames"
        usd = (
            estimate_usd(self.settings, result.model, result.usage, kind)
            if result.provider == "meta"
            else 0.0
        )
        self.cost.record(result.provider, result.model, role, usd, result.usage, result.latency_ms)
        return usd

    def record_transcript(self, result: TranscriptResult) -> float:
        if result.provider == "mock":
            return 0.0
        usd = estimate_usd(
            self.settings,
            result.model,
            result.usage,
            "audio_minutes" if result.provider == "meta" else "tokens",
        )
        self.cost.record(
            result.provider, result.model, "transcribe", usd, result.usage, result.latency_ms
        )
        return usd
