"""Every model role in one place: prompt + inputs + schema + safe fallback.

Each role is a thin function over `LLMCaller`, so live, privacy and mock modes share the same code.
The structured `context` is what the mock provider reads; real models read the prompt and parts.
Blind judging: `judge()` receives only the clip and the calibrated signal description.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.providers.base import LLMRequest, Part
from app.providers.llm import RoleResult, load_prompt
from app.providers.registry import Mode, ProviderHub
from app.schemas import (
    CalibrationDescription,
    Completions,
    FramingCheck,
    JudgeOut,
    MemoryOps,
    MemorySelection,
    PriorProposal,
    QuestionProposal,
    SceneFacts,
    SensitiveOut,
    Sentences,
    SignalSpec,
)


def _instructions(role: str, extra: str = "") -> tuple[str, str]:
    common, _ = load_prompt("_common")
    text, version = load_prompt(role)
    return f"{common}\n\n{text}\n{extra}".strip(), version


def format_evidence(evidence: list[dict[str, Any]]) -> str:
    lines = []
    for e in evidence:
        when = f", {e['minutes_ago']:.0f} min ago" if e.get("minutes_ago") is not None else ""
        lines.append(f"{e['id']} [{e.get('kind', '')}{when}]: {e.get('text', '')}")
    return "\n".join(lines) or "(no evidence)"


class Roles:
    def __init__(self, hub: ProviderHub, settings: Settings) -> None:
        self.hub = hub
        self.settings = settings

    async def _call(
        self,
        mode: Mode,
        role: str,
        parts: list[Part],
        schema: Any,
        fallback: Any,
        context: dict[str, Any],
        *,
        extra: str = "",
        effort: str | None = None,
        model_key: str = "spark",
        timeout_s: float = 30.0,
        max_tokens: int = 1500,
    ) -> RoleResult:
        instructions, version = _instructions(role, extra)
        req = LLMRequest(
            role=role,
            instructions=instructions,
            parts=parts,
            schema=schema,
            context=context,
            reasoning_effort=effort,
            model_key=model_key,
            timeout_s=timeout_s,
            max_output_tokens=max_tokens,
        )
        return await self.hub.caller(mode).call(req, fallback, version)

    # ------------------------------------------------------------- perception
    async def framing_check(self, mode: Mode, image: Path) -> RoleResult[FramingCheck]:
        return await self._call(
            mode,
            "framing_check",
            [Part("image", path=image, mime="image/jpeg")],
            FramingCheck,
            FramingCheck(
                face_visible=True,
                upper_body_visible=True,
                lighting_ok=True,
                advice="Could not check framing automatically.",
            ),
            {},
        )

    async def describe_calibration(
        self, mode: Mode, clips: dict[str, list[Path]], hint: str | None = None
    ) -> RoleResult[CalibrationDescription]:
        parts: list[Part] = []
        # Muse Spark accepts at most 5 videos per request (observed 400), so: 1 rest, 2 YES, 2 NO.
        for label, n in (("rest", 1), ("yes", 2), ("no", 2)):
            for i, clip in enumerate(clips.get(label, [])[:n]):
                parts.append(Part("video", path=clip, label=f"{label.upper()} clip {i + 1}"))
        fallback = CalibrationDescription(
            yes=SignalSpec(
                body_part="unknown",
                motion="unknown",
                sam_prompt="face",
                description="Could not describe automatically; caregiver should describe the signal.",
            ),
            no=SignalSpec(
                body_part="unknown",
                motion="unknown",
                sam_prompt="face",
                description="Could not describe automatically; caregiver should describe the signal.",
            ),
            distinct=False,
            notes="fallback",
        )
        extra = f"Caregiver hint about the chosen movement: {hint}" if hint else ""
        return await self._call(
            mode,
            "calibration_describer",
            parts,
            CalibrationDescription,
            fallback,
            {"hint": hint, "_video_fps": 8},
            extra=extra,
            effort="low",
            timeout_s=60,
            max_tokens=3000,
        )

    async def judge(
        self, mode: Mode, clip: Path, signal_text: str, *, mock_label: str | None = None
    ) -> RoleResult[JudgeOut]:
        """Blind judge: the clip and the patient's calibrated signals only. Never the question or hypotheses."""
        fallback = JudgeOut(
            classification="none", confidence=0.0, observed_movement="judge unavailable"
        )
        return await self._call(
            mode,
            "blind_judge",
            [Part("video", path=clip)],
            JudgeOut,
            fallback,
            {"mock_label": mock_label, "_video_fps": 8},
            extra=f"\nThe patient's calibrated signals:\n{signal_text}",
            effort=self.settings.perception.judge_reasoning_effort,
            timeout_s=self.settings.perception.judge_timeout_s,
            max_tokens=1500,
        )

    # ---------------------------------------------------------------- context
    async def read_scene(
        self, mode: Mode, image: Path | None, hint: list[str] | None = None
    ) -> RoleResult[SceneFacts]:
        parts = (
            [Part("image", path=image, mime="image/jpeg")]
            if image
            else [Part("text", text="(no image)")]
        )
        return await self._call(
            mode,
            "scene_reader",
            parts,
            SceneFacts,
            SceneFacts(facts=[]),
            {"scene_hint": hint},
            max_tokens=1500,
        )

    async def build_prior(
        self,
        mode: Mode,
        evidence: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        persons: list[dict[str, str]],
    ) -> RoleResult[PriorProposal]:
        payload = {
            "evidence": format_evidence(evidence),
            "candidate_messages": [{"id": h["id"], "text": h["text_en"]} for h in hypotheses],
            "profile_people": persons,
        }
        return await self._call(
            mode,
            "prior_builder",
            [Part("text", text=json.dumps(payload, ensure_ascii=False))],
            PriorProposal,
            PriorProposal(),
            {"evidence": evidence, "hypotheses": hypotheses, "persons": persons},
            effort="low",
            max_tokens=4000,
        )

    async def propose_questions(
        self,
        mode: Mode,
        evidence: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        top: list[dict[str, Any]],
    ) -> RoleResult[QuestionProposal]:
        payload = {
            "evidence": format_evidence(evidence),
            "candidate_messages": [{"id": h["id"], "text": h["text_en"]} for h in hypotheses],
            "current_top": top,
        }
        return await self._call(
            mode,
            "question_proposer",
            [Part("text", text=json.dumps(payload, ensure_ascii=False))],
            QuestionProposal,
            QuestionProposal(),
            {"evidence": evidence, "hypotheses": hypotheses, "top": top},
            max_tokens=3000,
        )

    async def complete_word(
        self, mode: Mode, prefix: str, text: str, lang: str, evidence: list[dict[str, Any]]
    ) -> RoleResult[Completions]:
        payload = {
            "prefix": prefix,
            "spelled_so_far": text,
            "language": lang,
            "evidence": format_evidence(evidence),
        }
        return await self._call(
            mode,
            "spelling_completer",
            [Part("text", text=json.dumps(payload, ensure_ascii=False))],
            Completions,
            Completions(),
            {"prefix": prefix, "text": text, "lang": lang},
            timeout_s=8,
            max_tokens=1500,
        )

    async def build_sentences(
        self,
        mode: Mode,
        text: str,
        lang: str,
        evidence: list[dict[str, Any]],
        persons: list[dict[str, str]],
    ) -> RoleResult[Sentences]:
        payload = {"spelled": text, "language": lang, "evidence": format_evidence(evidence)}
        return await self._call(
            mode,
            "sentence_builder",
            [Part("text", text=json.dumps(payload, ensure_ascii=False))],
            Sentences,
            Sentences(),
            {"text": text, "lang": lang, "persons": persons},
            timeout_s=10,
            max_tokens=1500,
        )

    async def classify_sensitive(self, mode: Mode, text: str) -> RoleResult[SensitiveOut]:
        return await self._call(
            mode,
            "sensitive_classifier",
            [Part("text", text=text)],
            SensitiveOut,
            SensitiveOut(sensitive=False),
            {"text": text},
            timeout_s=8,
            max_tokens=1200,
        )

    # ----------------------------------------------------------------- memory
    async def curate_memory(self, mode: Mode, payload: dict[str, Any]) -> RoleResult[MemoryOps]:
        return await self._call(
            mode,
            "memory_curator",
            [Part("text", text=json.dumps(payload, ensure_ascii=False))],
            MemoryOps,
            MemoryOps(),
            payload,
            model_key="wonder",
            effort="low",
            timeout_s=60,
            max_tokens=4000,
        )

    async def select_memory(
        self, mode: Mode, memory: list[dict[str, Any]], evidence: list[dict[str, Any]]
    ) -> RoleResult[MemorySelection]:
        payload = {
            "memory": [{"id": m["id"], "text": m["text"]} for m in memory],
            "evidence": format_evidence(evidence),
        }
        return await self._call(
            mode,
            "memory_selector",
            [Part("text", text=json.dumps(payload, ensure_ascii=False))],
            MemorySelection,
            MemorySelection(entry_ids=[m["id"] for m in memory[-10:]]),
            {"memory": memory, "evidence": evidence},
            model_key="wonder",
            max_tokens=1200,
        )
