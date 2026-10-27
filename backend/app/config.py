"""Configuration: `config.yaml` (models, thresholds, prices) plus `.env` (secrets, mode).

No model id string may appear anywhere else in the code base; read it from `settings.models`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(os.environ.get("VENT_CONFIG", ROOT / "config.yaml"))

AppMode = Literal["mock", "live"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="allow")


class EngineConfig(_Section):
    tau_confirm: float = 0.70
    finalize_threshold: float = 0.95
    max_questions: int = 10
    offer_spell_other: float = 0.50
    offer_spell_after: int = 8
    lambda_words: float = 0.01
    prior_cap: float = 0.40
    prior_floor: float = 0.005
    other_min: float = 0.08
    context_multipliers: list[float] = Field(default_factory=lambda: [0.25, 0.5, 1, 2, 4])
    context_clip: tuple[float, float] = (0.1, 8.0)
    personal_clip: tuple[float, float] = (0.5, 3.0)
    personal_half_life_days: float = 3.0
    personal_prior_strength: float = 10.0
    confirm_no_factor: float = 0.05
    default_error_rates: dict[str, float] = Field(default_factory=lambda: {"a": 0.10, "b": 0.10})
    eps_clip: tuple[float, float] = (0.03, 0.45)
    max_llm_hypotheses: int = 3
    max_llm_questions: int = 5
    max_question_words: int = 10
    unclear_pause_after: int = 3
    confirm_no_pause_after: int = 2
    confirm_no_pause_min_p: float = 0.90
    spelling_checkpoint_every: int = 3
    spelling_letter_accept: float = 0.90
    spelling_max_questions_per_letter: int = 14
    spelling_word_suggest_min: float = 0.35
    spelling_max_prompts: int = 80
    sentence_max_rounds: int = 3


class PerceptionConfig(_Section):
    width: int = 640
    height: int = 480
    fps: int = 15
    tracker_fps: int = 8
    window_s: float = 4.0
    window_delay_ms: int = 300
    unclear_threshold: float = 0.65
    disagreement_threshold: float = 0.5
    judge_timeout_s: float = 9.0
    judge_reasoning_effort: str = "minimal"
    judge_frames: int = 8
    emergency_yes_count: int = 3
    emergency_window_s: float = 4.0
    idle_watch_interval_s: float = 20.0
    calibration_min_accuracy: float = 0.80
    early_decision_p: float = 0.90
    early_decision_margin: float = 1.25
    early_grace_s: float = 0.2


class FeatureFlags(_Section):
    use_sam: bool = True
    use_spark_judge: bool = True
    use_transcribe: bool = True
    use_wonder: bool = True
    privacy_mode: bool = False
    idle_watch: bool = False
    idle_watch_mock: bool = True


class MessagesConfig(_Section):
    # A spoken message nobody acknowledges is repeated (the room may be empty and the patient
    # cannot press the call bell), then escalated on the caregiver screen.
    ack_repeat_s: float = 60.0
    ack_max_repeats: int = 2


class BudgetConfig(_Section):
    max_usd: float = 120.0
    warn_fraction: float = 0.70
    mock_fraction: float = 0.90


class Settings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw: dict[str, Any]
    app_mode: AppMode
    model_api_key: str | None
    baseten_api_key: str | None
    modal_sam_url: str | None
    live_passcode: str | None
    whatsapp_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None
    data_dir: Path
    engine: EngineConfig
    perception: PerceptionConfig
    features: FeatureFlags
    budget: BudgetConfig
    messages: MessagesConfig = MessagesConfig()

    @property
    def models(self) -> dict[str, str]:
        return self.raw["models"]

    @property
    def pricing(self) -> dict[str, dict[str, float]]:
        return self.raw.get("pricing", {})

    @property
    def providers(self) -> dict[str, dict[str, Any]]:
        return self.raw.get("providers", {})

    @property
    def base_rates(self) -> dict[str, float]:
        return self.raw["taxonomy"]["base_rates"]

    @property
    def llm_template_base_rate(self) -> float:
        return float(self.raw["taxonomy"].get("llm_template_base_rate", 0.02))

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})


def _env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def load_settings(config_path: Path | None = None, env_file: Path | None = None) -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file or ROOT / ".env", override=False)
    except ImportError:  # optional outside the server (e.g. the in-browser demo)
        pass
    raw = yaml.safe_load((config_path or CONFIG_PATH).read_text())
    mode = (_env("APP_MODE") or "mock").lower()
    if mode not in ("mock", "live"):
        mode = "mock"
    data_dir = Path(_env("VENT_DATA_DIR") or (ROOT / raw["app"].get("data_dir", "./data")))
    if not data_dir.is_absolute():
        data_dir = (ROOT / data_dir).resolve()
    return Settings(
        raw=raw,
        app_mode=mode,  # type: ignore[arg-type]
        model_api_key=_env("MODEL_API_KEY"),
        baseten_api_key=_env("BASETEN_API_KEY"),
        modal_sam_url=_env("MODAL_SAM_URL"),
        live_passcode=_env("LIVE_PASSCODE"),
        whatsapp_token=_env("WHATSAPP_TOKEN"),
        whatsapp_phone_number_id=_env("WHATSAPP_PHONE_NUMBER_ID"),
        whatsapp_app_secret=_env("WHATSAPP_APP_SECRET"),
        whatsapp_verify_token=_env("WHATSAPP_VERIFY_TOKEN"),
        data_dir=data_dir,
        engine=EngineConfig(**raw.get("engine", {})),
        perception=PerceptionConfig(**raw.get("perception", {})),
        features=FeatureFlags(**raw.get("features", {})),
        budget=BudgetConfig(**raw.get("budget", {})),
        messages=MessagesConfig(**raw.get("messages", {})),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
