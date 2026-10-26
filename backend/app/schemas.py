"""Pydantic schemas: API payloads and every LLM role's output.

Every model output is validated against one of these schemas, with one repair retry and then a
safe fallback (see providers/llm.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Lang = Literal["en", "id"]


# ============================================================== API payloads
class FamilyMember(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    relation: str = Field(min_length=1, max_length=40)


class PatientProfile(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    language: Lang = "en"
    honorific: Literal["Bapak", "Ibu", "Anda"] = "Anda"
    family: list[FamilyMember] = Field(default_factory=list, max_length=12)
    notes: list[str] = Field(default_factory=list, max_length=20)
    spiritual_preference: str | None = Field(default=None, max_length=60)
    simulation_consent: bool = False


class SessionCreate(BaseModel):
    patient_id: str
    privacy: bool = False
    simulated_patient: str | None = None  # true hypothesis id for the auto-answering simulator
    simulated_noise: float = Field(default=0.05, ge=0.0, le=0.45)
    scenario: str | None = None
    passcode: str | None = None


class EventCreate(BaseModel):
    kind: Literal[
        "suctioned",
        "repositioned",
        "mouth_care",
        "visitor_arrived",
        "visitor_left",
        "family_called",
        "medication_given",
        "procedure_done",
        "note",
    ]
    label: str | None = Field(default=None, max_length=120)


class OverrideCreate(BaseModel):
    action: Literal[
        "yes",
        "no",
        "unclear",
        "skip",
        "spell",
        "end",
        "pause",
        "resume",
        "emergency",
        "ack_emergency",
        "ack_sensitive",
        "ack_sensitive_silent",
        "new_message",
        "refresh_context",
    ]


class AnswerCreate(BaseModel):
    prompt_id: str
    answer: Literal["yes", "no", "unclear", "emergency", "none"]
    source: Literal["keyboard", "simulated"] = "keyboard"


class TranscriptLine(BaseModel):
    speaker: str = Field(default="room", max_length=40)
    text: str = Field(min_length=1, max_length=1000)


class SettingsUpdate(BaseModel):
    app_mode: Literal["mock", "live"] | None = None
    privacy_mode: bool | None = None
    language: Lang | None = None
    window_s: float | None = Field(default=None, ge=2.0, le=8.0)
    tau_confirm: float | None = Field(default=None, ge=0.5, le=0.9)
    budget_max_usd: float | None = Field(default=None, ge=1, le=1000)
    keep_clips_for_evaluation: bool | None = None
    use_sam: bool | None = None
    use_spark_judge: bool | None = None
    use_transcribe: bool | None = None
    use_wonder: bool | None = None
    idle_watch: bool | None = None
    passcode: str | None = None


# ========================================================== LLM role outputs
class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SignalSpec(_Out):
    body_part: str = Field(max_length=60)
    motion: str = Field(max_length=120)
    sam_prompt: str = Field(
        max_length=40, description="short noun phrase for SAM 3.1, e.g. 'eyebrows'"
    )
    description: str = Field(max_length=240)


class CalibrationDescription(_Out):
    yes: SignalSpec
    no: SignalSpec
    distinct: bool
    notes: str = Field(default="", max_length=400)


class FramingCheck(_Out):
    face_visible: bool
    upper_body_visible: bool
    lighting_ok: bool
    advice: str = Field(
        default="", max_length=200, description="camera placement tip, never clinical"
    )


class SceneFacts(_Out):
    facts: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("facts")
    @classmethod
    def _short(cls, v: list[str]) -> list[str]:
        return [f.strip()[:160] for f in v if f.strip()]


class MultiplierOut(_Out):
    hypothesis_id: str
    factor: float
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=160)


class SlotsOut(_Out):
    """Template slots. Explicit fields (not a free-form map) so strict structured output accepts it."""

    name: str | None = None
    relation: str | None = None
    item: str | None = None
    item_id: str | None = None


class InstantiationOut(_Out):
    template: str
    slots: SlotsOut
    evidence_ids: list[str] = Field(default_factory=list)


class PriorProposal(_Out):
    multipliers: list[MultiplierOut] = Field(default_factory=list, max_length=40)
    new_hypotheses: list[InstantiationOut] = Field(default_factory=list, max_length=6)


class QuestionOut(_Out):
    text_en: str = Field(max_length=120)
    text_id: str = Field(default="", max_length=160)
    yes_ids: list[str]
    evidence_ids: list[str] = Field(default_factory=list)


class QuestionProposal(_Out):
    questions: list[QuestionOut] = Field(default_factory=list, max_length=8)


class JudgeOut(_Out):
    classification: Literal["yes", "no", "none", "emergency"]
    confidence: float = Field(ge=0.0, le=1.0)
    observed_movement: str = Field(default="", max_length=200)
    frame_times: list[float] = Field(default_factory=list, max_length=32)


class WordOut(_Out):
    word: str = Field(max_length=30)
    p: float = Field(ge=0.0, le=1.0)


class Completions(_Out):
    words: list[WordOut] = Field(default_factory=list, max_length=8)


class SentenceOut(_Out):
    text_en: str = Field(max_length=140)
    text_id: str = Field(max_length=160)
    p: float = Field(ge=0.0, le=1.0)


class Sentences(_Out):
    sentences: list[SentenceOut] = Field(default_factory=list, max_length=5)


class SensitiveOut(_Out):
    sensitive: bool
    categories: list[str] = Field(default_factory=list)


class MemoryOpOut(_Out):
    op: Literal["add", "update", "retire"]
    entry_id: str | None = None
    text: str = Field(default="", max_length=200)
    category: str = Field(default="fact", max_length=40)
    source_refs: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=200)


class MemoryOps(_Out):
    ops: list[MemoryOpOut] = Field(default_factory=list, max_length=12)


class MemorySelection(_Out):
    entry_ids: list[str] = Field(default_factory=list, max_length=10)
