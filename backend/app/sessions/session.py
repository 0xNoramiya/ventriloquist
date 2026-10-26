"""Session orchestrator: one patient, one conversation, many messages (brief 8.7, Section 12).

Owns the state machine, the evidence store, the engine deciders (main, spelling, sentence choice,
pain refinement) and all side effects: prompts to speak, perception, caregiver overrides,
emergency, memory hand-off and JSONL logging. Every change is pushed to the patient and caregiver
views through `on_change` as a full snapshot.

Safety-critical behaviour lives here and is tested in tests/test_session.py:
confirm-before-speak, post-speak check and retraction, sensitive messages held for a caregiver,
emergency from any state, human override everywhere.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.context.evidence import EvidenceStore, minutes_between
from app.engine.instantiation import TemplateProposal, validate_instantiations
from app.engine.personal import ConfirmedMessage, personal_multipliers
from app.engine.policy import QUESTION_ACTIONS, Action, ActionKind, MessageDecider
from app.engine.priors import ContextMultiplier, PriorTerm, build_prior
from app.engine.questions import LLMQuestionProposal, validate_llm_questions
from app.engine.refine import location_stage, offer_question, worse_message, worse_question
from app.engine.spelling import KEEP_ID, SpellEvent, SpellingDecider, SpellPrompt, sentence_stage
from app.engine.taxonomy import Person, attribute_questions, build_hypotheses, post_check_question
from app.engine.types import (
    Answer,
    Hypothesis,
    HypothesisSource,
    Observation,
    Question,
    render,
)
from app.providers.registry import Mode, ProviderHub
from app.roles import Roles
from app.safety.sensitive import detect
from app.storage import Store, new_id, now_iso

from .log import SessionLog
from .simulated import SimulatedPatient
from .state_machine import InvalidTransition, State, StateMachine

log = logging.getLogger(__name__)

EMERGENCY_TEXT = {"en": "The patient needs help now.", "id": "Pasien butuh bantuan sekarang."}
PAUSE_TEXT = {
    "en": "Responses unclear. Please check with the patient in person.",
    "id": "Jawaban kurang jelas. Mohon periksa pasien secara langsung.",
}
CAREGIVER_REASONS = {
    "question_cap": "Ten questions reached. Please help the patient in person.",
    "unclear": PAUSE_TEXT["en"],
    "inconsistent": PAUSE_TEXT["en"],
    "tap_answer": "The answer was unclear twice. Please tap the patient's answer.",
    "no_match": "The message did not match the list. Please help in person or start spelling.",
    "no_questions_left": "No more useful questions. Please help in person or start spelling.",
    "sensitive_verify": "Verify in person with the patient.",
    "spelling_stuck": "Spelling is stuck. Please help the patient in person.",
    "internal_error": "Something went wrong. Please continue with the patient in person.",
}


@dataclass
class Prompt:
    id: str
    kind: (
        str  # ask | confirm | offer_spell | spelling | post_check | refine_offer | worse | message
    )
    stage: str  # main | sentence | refine | spelling | post_check | refine_offer | worse | speak
    text: str
    text_en: str
    question: Question | None = None
    group: list[str] = field(default_factory=list)
    word: str | None = None
    rephrased: bool = False
    sub: str | None = None  # spelling: letter | checkpoint | word
    asked_at: str = field(default_factory=now_iso)

    def to_dict(self, lang: str, honorific: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "stage": self.stage,
            "sub": self.sub,
            "text": self.text,
            "text_en": self.text_en,
            "question": self.question.to_dict(lang, honorific) if self.question else None,
            "group": self.group,
            "word": self.word,
            "rephrased": self.rephrased,
            "asked_at": self.asked_at,
        }


@dataclass
class Message:
    id: str
    hypothesis_id: str | None
    text_en: str
    text_id: str
    source: str
    status: str  # speaking | needs_verification | confirmed | retracted
    urgent: bool = False
    sensitive: bool = False
    categories: list[str] = field(default_factory=list)
    questions: int = 0
    at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class AppContext:
    settings: Settings
    store: Store
    hub: ProviderHub
    roles: Roles


Notifier = Callable[["Session", dict[str, Any] | None], Awaitable[None]]


class Session:
    def __init__(
        self,
        sid: str,
        patient: dict[str, Any],
        calibration: dict[str, Any],
        ctx: AppContext,
        *,
        mode: Mode,
        simulated: SimulatedPatient | None = None,
        auto_speak: bool = False,
        scenario: dict[str, Any] | None = None,
        on_change: Notifier | None = None,
        strict: bool = False,
        sim_delay_s: float = 0.0,
    ) -> None:
        self.id = sid
        self.patient = patient
        self.pid = patient["id"]
        self.lang = patient.get("language", "en")
        self.honorific = patient.get("honorific", "Anda")
        self.persons = [Person(f["name"], f["relation"]) for f in patient.get("family", [])]
        self.calibration = calibration
        self.ctx = ctx
        self.cfg = ctx.settings.engine
        self.mode = mode
        self.sim = simulated
        self.auto_speak = auto_speak or simulated is not None
        self.scenario = scenario or {}
        self.on_change = on_change
        self.strict = strict
        self.sim_delay_s = sim_delay_s
        self.sm = StateMachine()
        self.lock = asyncio.Lock()
        names = {f["name"]: f["relation"] for f in patient.get("family", [])}
        names[patient.get("display_name", "")] = "patient"
        self.log = SessionLog(ctx.store.session_log_path(sid), names)
        self.started_at = now_iso()
        self.ended = False

        rates = calibration.get("error_rates") or self.cfg.default_error_rates
        self.a, self.b = float(rates["a"]), float(rates["b"])

        self.evidence = EvidenceStore()
        self.prior_terms: dict[str, PriorTerm] = {}
        self.decider: MessageDecider | None = None
        self.sentence: MessageDecider | None = None
        self.refine: MessageDecider | None = None
        self.spelling: SpellingDecider | None = None
        self.stage = "main"
        self.prompt: Prompt | None = None
        self.prompt_seq = 0
        self.reasked: set[str] = set()
        self.unclear_streak = 0
        self.message: Message | None = None
        self.messages: list[Message] = []
        self.trail: list[dict[str, Any]] = []
        self.caregiver_reason: str | None = None
        self.alerts: list[dict[str, Any]] = []
        self.emergency_active = False
        self.overlay: dict[str, Any] | None = None
        self.llm_calls: list[dict[str, Any]] = []
        self.message_index = 0
        self.message_started_at: str | None = None
        self.questions_this_message = 0
        self.refined = False
        self.retractions = 0
        self.sentence_rounds = 0
        self.pain_parent: Message | None = None
        self.rejected: list[dict[str, Any]] = []
        self._tasks: set[asyncio.Task[Any]] = set()

    # ================================================================ helpers
    @property
    def state(self) -> State:
        return self.sm.state

    def _to(self, dst: State, reason: str = "") -> None:
        if self.sm.state == dst:
            return
        try:
            self.sm.to(dst, reason)
        except InvalidTransition:
            if self.strict:
                raise
            log.error("forcing invalid transition %s -> %s (%s)", self.sm.state, dst, reason)
            self.sm.history.append((self.sm.state, dst, f"FORCED {reason}"))
            self.sm.state = dst
        self.log.write("state", state=str(dst), reason=reason)

    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(self._guard(coro))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _guard(self, coro: Awaitable[Any]) -> Any:
        """Fail safe: any internal error hands the conversation to the caregiver instead of hanging."""
        try:
            return await coro
        except Exception as exc:
            if self.strict:
                raise
            await self._fail(exc)
            return None

    async def _fail(self, exc: BaseException) -> None:
        log.exception("session %s internal error", self.id, exc_info=exc)
        self.log.write("error", error=repr(exc)[:500])
        self.caregiver_reason = "internal_error"
        self.prompt = None
        self._to(State.CAREGIVER_NEEDED, "internal error")
        await self._notify(
            {
                "type": "error",
                "text": "Something went wrong. Please continue with the patient in person.",
            }
        )

    async def _notify(self, event: dict[str, Any] | None = None) -> None:
        if self.on_change is not None:
            await self.on_change(self, event)

    def _t(self, en: str, idn: str) -> str:
        return render(idn if self.lang == "id" else en, self.honorific)

    def _record_call(self, meta: dict[str, Any]) -> None:
        self.llm_calls.append(meta)
        self.log.write("llm_call", **meta)

    # ================================================================ lifecycle
    async def start(self) -> None:
        async with self.lock:
            self.log.write(
                "session_start",
                patient_id=self.pid,
                mode=str(self.mode),
                effective=self.ctx.hub.resolve(self.mode).to_dict(),
                language=self.lang,
                error_rates={"a": self.a, "b": self.b},
                simulated=bool(self.sim),
            )
            await self._begin_message()
        await self._notify()

    async def new_message(self) -> None:
        async with self.lock:
            if self.state in (
                State.DONE,
                State.PAUSED,
                State.IDLE,
                State.CAREGIVER_NEEDED,
                State.EMERGENCY,
            ):
                await self._begin_message()
        await self._notify()

    async def _begin_message(self) -> None:
        self._to(State.CONTEXT_REFRESH, "new message")
        self.message_index += 1
        self.message_started_at = now_iso()
        self.questions_this_message = 0
        self.retractions = 0
        self.sentence_rounds = 0
        self.stage = "main"
        self.message = None
        self.sentence = self.refine = None
        self.spelling = None
        self.refined = False
        self.reasked.clear()
        self.unclear_streak = 0
        self.caregiver_reason = None
        self.trail = []
        await self._refresh_context()
        await self._build_decider()
        assert self.decider is not None
        await self._apply_main(self.decider.next_action())

    async def _refresh_context(self) -> None:
        store, roles = self.ctx.store, self.ctx.roles
        now = datetime.now(UTC)
        ev = EvidenceStore()
        for f in store.scene_facts(self.pid, self.id):
            ev.add("scene", f["text"], f["created_at"], f["id"])
        window = (
            now - timedelta(minutes=self.ctx.settings.raw["context"]["transcript_window_min"])
        ).isoformat()
        for t in store.transcript(self.pid, window):
            ev.add(
                "transcript",
                f"{t['speaker']}: {t['text']}",
                t["created_at"],
                t["id"],
                speaker=t["speaker"],
            )
        since_events = (now - timedelta(hours=12)).isoformat()
        for e in store.events(self.pid, since_events):
            label = e["label"] or e["kind"].replace("_", " ")
            mins = minutes_between(e["created_at"], now)
            ev.add(
                "event", f"{label} ({_ago(mins)})", e["created_at"], e["id"], event_kind=e["kind"]
            )
        since_hist = (now - timedelta(hours=48)).isoformat()
        for m in store.messages(self.pid, "confirmed")[-10:]:
            if m["created_at"] >= since_hist and not m["sensitive"]:
                ev.add(
                    "history",
                    f"Patient said: {m['text_en']}",
                    m["created_at"],
                    m["id"],
                    hypothesis_id=m["hypothesis_id"],
                )
        memory = store.memory(self.pid, "approved")
        if memory:
            chosen = memory
            if len(memory) > self.ctx.settings.raw["context"][
                "memory_select_max"
            ] and self.ctx.hub.flag("use_wonder"):
                res = await roles.select_memory(self.mode, memory, ev.to_list(now))
                self._record_call(res.meta.to_dict())
                keep = set(res.data.entry_ids)
                chosen = [m for m in memory if m["id"] in keep] or memory[-10:]
            for m in chosen[: self.ctx.settings.raw["context"]["memory_select_max"]]:
                ev.add("memory", m["text"], m["created_at"], m["id"], source_type=m["source_type"])
                store.update_memory(m["id"], last_used_at=now_iso())
        self.evidence = ev
        self.log.write("context", evidence=ev.to_list(now))

    async def _build_decider(self) -> None:
        settings, roles, cfg = self.ctx.settings, self.ctx.roles, self.cfg
        hyps = build_hypotheses(
            settings.base_rates, self.persons, self.patient.get("spiritual_preference")
        )
        ev_list = self.evidence.to_list()
        hyp_dicts = [{"id": h.id, "text_en": h.text_en, "category": h.category} for h in hyps]
        persons = [{"name": p.name, "relation": p.relation} for p in self.persons]
        prior_res, q_res = await asyncio.gather(
            roles.build_prior(self.mode, ev_list, hyp_dicts, persons),
            roles.propose_questions(self.mode, ev_list, hyp_dicts, []),
        )
        self._record_call(prior_res.meta.to_dict())
        self._record_call(q_res.meta.to_dict())
        new_hyps, rejected = validate_instantiations(
            [
                TemplateProposal(
                    n.template,
                    {k: v for k, v in n.slots.model_dump().items() if v},
                    n.evidence_ids,
                )
                for n in prior_res.data.new_hypotheses
            ],
            persons=self.persons,
            evidence=self.evidence.texts(),
            existing_ids={h.id for h in hyps},
            max_new=cfg.max_llm_hypotheses,
            base_rate=settings.llm_template_base_rate,
        )
        hyps += new_hyps
        history = [
            ConfirmedMessage(m["hypothesis_id"], datetime.fromisoformat(m["created_at"]))
            for m in self.ctx.store.messages(self.pid, "confirmed")
            if m["hypothesis_id"] and not m["sensitive"]
        ]
        personal = (
            personal_multipliers(
                history,
                {h.id: h.base_rate for h in hyps},
                datetime.now(UTC),
                half_life_days=cfg.personal_half_life_days,
                prior_strength=cfg.personal_prior_strength,
                clip=tuple(cfg.personal_clip),
            )
            if history
            else {}
        )
        mults = [
            ContextMultiplier(m.hypothesis_id, m.factor, tuple(m.evidence_ids), m.reason)
            for m in prior_res.data.multipliers
        ]
        prior, terms = build_prior(
            hyps,
            personal=personal,
            multipliers=mults,
            valid_evidence=self.evidence.ids(),
            cap=cfg.prior_cap,
            floor=cfg.prior_floor,
            other_min=cfg.other_min,
            allowed=list(cfg.context_multipliers),
            context_clip=tuple(cfg.context_clip),
            personal_clip=tuple(cfg.personal_clip),
        )
        questions = attribute_questions(hyps, self.persons)
        llm_qs, q_rejected = validate_llm_questions(
            [
                LLMQuestionProposal(q.text_en, q.text_id, q.yes_ids, q.evidence_ids)
                for q in q_res.data.questions
            ],
            {h.id for h in hyps},
            questions,
            cfg.max_llm_questions,
            cfg.max_question_words,
        )
        self.prior_terms = terms
        self.rejected = rejected + q_rejected
        self.decider = MessageDecider(hyps, prior, questions + llm_qs, cfg, self.a, self.b)
        self.log.write(
            "prior",
            terms={k: v.to_dict() for k, v in terms.items()},
            new_hypotheses=[h.to_dict() for h in new_hyps],
            llm_questions=[q.text_en for q in llm_qs],
            rejected=self.rejected,
        )

    # ================================================================ prompts
    async def _prompt(
        self,
        kind: str,
        stage: str,
        question: Question | None,
        *,
        text: str | None = None,
        text_en: str | None = None,
        rephrased: bool = False,
        group: list[str] | None = None,
        word: str | None = None,
        state: State = State.ASKING,
        sub: str | None = None,
    ) -> None:
        self.prompt_seq += 1
        if question is not None:
            text = question.text(self.lang, self.honorific, rephrased)
            text_en = render(
                question.rephrase_en if rephrased and question.rephrase_en else question.text_en,
                self.honorific,
            )
        if kind in ("ask", "confirm", "offer_spell", "spelling", "refine_offer", "worse"):
            self.questions_this_message += 1
        self.prompt = Prompt(
            f"p{self.prompt_seq}",
            kind,
            stage,
            text or "",
            text_en or text or "",
            question,
            group or [],
            word,
            rephrased,
            sub,
        )
        self._to(state, f"{kind}:{stage}")
        self.log.write(
            "prompt",
            prompt=self.prompt.to_dict(self.lang, self.honorific),
            posterior=self._top_posterior(10),
        )
        if self.auto_speak:
            self._spawn(self._auto_spoken(self.prompt.id))

    async def _auto_spoken(self, prompt_id: str) -> None:
        if self.sim_delay_s:
            await asyncio.sleep(self.sim_delay_s)
        await self.spoken(prompt_id)

    async def spoken(self, prompt_id: str) -> None:
        """The patient phone finished speaking the prompt (or the message)."""
        sim_answer = None
        async with self.lock:
            if not self.prompt or self.prompt.id != prompt_id:
                return
            if self.state == State.SPEAKING and self.prompt.kind == "message":
                await self._post_check()
            elif self.state in (State.ASKING, State.CONFIRMING, State.SPELLING, State.POST_CHECK):
                self._to(State.LISTENING, "prompt spoken")
                if self.sim is not None:
                    sim_answer = self.sim.answer(
                        self.prompt.to_dict(self.lang, self.honorific), self.view()
                    )
                    pid = self.prompt.id
        await self._notify()
        if sim_answer is not None:
            if self.sim_delay_s:
                await asyncio.sleep(self.sim_delay_s)
            await self.answer(pid, sim_answer, source="simulated")

    # ================================================================ answers
    async def answer(self, prompt_id: str, answer: Answer | str, source: str = "keyboard") -> bool:
        ans = Answer(answer)
        conf = {"keyboard": 0.95, "simulated": 1.0 - (self.sim.noise if self.sim else 0.05)}.get(
            source, 0.9
        )
        obs = Observation(ans, conf, {"sources": {source: {"answer": str(ans)}}})
        return await self.observe(prompt_id, obs, source)

    async def clip(self, prompt_id: str, path: Path) -> dict[str, Any]:
        async with self.lock:
            if not self.prompt or self.prompt.id != prompt_id or self.state != State.LISTENING:
                path.unlink(missing_ok=True)
                return {"accepted": False, "reason": "stale prompt"}
            self._to(State.PROCESSING, "clip received")
        await self._notify()
        from app.perception.pipeline import perceive

        workdir = self.ctx.store.media_dir("sessions", self.id)
        perc = await perceive(
            path,
            self.calibration,
            workdir,
            hub=self.ctx.hub,
            roles=self.ctx.roles,
            settings=self.ctx.settings,
            mode=self.mode,
        )
        if perc.overlay:
            self.overlay = {**perc.overlay, "prompt_id": prompt_id}
        self.log.write("perception", prompt_id=prompt_id, **perc.to_dict())
        await self.observe(prompt_id, perc.observation, "camera", already_processing=True)
        return {"accepted": True, **perc.to_dict()}

    async def observe(
        self, prompt_id: str, obs: Observation, source: str, already_processing: bool = False
    ) -> bool:
        if obs.answer == Answer.EMERGENCY:
            await self.emergency(f"{source}:triple_yes")
            return True
        async with self.lock:
            if not self.prompt or self.prompt.id != prompt_id:
                return False
            if not already_processing:
                if self.state in (State.ASKING, State.CONFIRMING, State.SPELLING, State.POST_CHECK):
                    self._to(State.LISTENING, "answer before speech end")
                if self.state not in (State.LISTENING, State.CAREGIVER_NEEDED):
                    return False
                self._to(State.PROCESSING, f"answer from {source}")
            self.caregiver_reason = None
            try:
                await self._handle(obs, source)
            except Exception as exc:
                if self.strict:
                    raise
                failure: BaseException | None = exc
            else:
                failure = None
        if failure is not None:
            await self._fail(failure)
            return True
        await self._notify()
        return True

    async def _handle(self, obs: Observation, source: str) -> None:
        assert self.prompt is not None
        p = self.prompt
        self.trail.append(
            {
                "n": len(self.trail) + 1,
                "prompt_id": p.id,
                "kind": p.kind,
                "stage": p.stage,
                "text": p.text,
                "text_en": p.text_en,
                "answer": str(obs.answer),
                "confidence": round(obs.confidence, 3),
                "overridden": obs.overridden,
                "source": source,
                "rephrased": p.rephrased,
                "sources": obs.sources.get("sources", {}),
                "group": p.group,
                "at": now_iso(),
            }
        )
        self.log.write("observation", prompt_id=p.id, observation=obs.to_dict(), source=source)
        if obs.answer in (Answer.YES, Answer.NO):
            self.unclear_streak = 0

        if p.stage == "main":
            assert self.decider is not None
            await self._apply_main(self.decider.observe(obs))
        elif p.stage == "sentence":
            assert self.sentence is not None
            await self._apply_sentence(self.sentence.observe(obs))
        elif p.stage == "refine":
            assert self.refine is not None
            await self._apply_refine(self.refine.observe(obs))
        elif p.stage == "spelling":
            await self._handle_spelling(obs)
        else:
            await self._handle_simple(obs)
        if self.trail:
            self.trail[-1]["top_after"] = self._top_posterior(3)

    async def _unclear_simple(self) -> bool:
        """Shared UNCLEAR rule for prompts outside the main decider: re-ask once, then the caregiver."""
        assert self.prompt is not None
        self.unclear_streak += 1
        if self.unclear_streak >= self.cfg.unclear_pause_after:
            await self._caregiver("unclear", keep_prompt=True)
            return True
        if self.prompt.id not in self.reasked:
            self.reasked.add(self.prompt.id)
            p = self.prompt
            state = (
                State.POST_CHECK
                if p.kind == "post_check"
                else (State.SPELLING if p.stage == "spelling" else State.ASKING)
            )
            self.prompt_seq += 1
            self.prompt = Prompt(
                f"p{self.prompt_seq}",
                p.kind,
                p.stage,
                p.text,
                p.text_en,
                p.question,
                p.group,
                p.word,
                True,
                p.sub,
            )
            self.reasked.add(self.prompt.id)
            self.questions_this_message += 1
            self._to(state, "re-ask after unclear")
            self.log.write(
                "prompt", prompt=self.prompt.to_dict(self.lang, self.honorific), reask=True
            )
            if self.auto_speak:
                self._spawn(self._auto_spoken(self.prompt.id))
            return True
        await self._caregiver("tap_answer", keep_prompt=True)
        return True

    async def _handle_simple(self, obs: Observation) -> None:
        assert self.prompt is not None
        if obs.answer not in (Answer.YES, Answer.NO):
            await self._unclear_simple()
            return
        yes = obs.answer == Answer.YES
        kind = self.prompt.kind
        if kind == "post_check":
            if yes:
                await self._message_confirmed()
            else:
                await self._message_retracted()
        elif kind == "refine_offer":
            if yes:
                hyps, prior, questions = location_stage()
                self.refine = MessageDecider(hyps, prior, questions, self.cfg, self.a, self.b)
                self.stage = "refine"
                await self._apply_refine(self.refine.next_action())
            else:
                await self._done()
        elif kind == "worse":
            if yes:
                en, idn = worse_message()
                await self._finalize_text(None, en, idn, "refinement")
            else:
                await self._done()

    # ================================================================ main stage
    async def _apply_main(self, act: Action) -> None:
        self.stage = "main"
        await self._apply_decider_action(act, "main")

    async def _apply_decider_action(self, act: Action, stage: str) -> None:
        if act.kind in QUESTION_ACTIONS:
            assert act.question is not None
            kind = {
                ActionKind.ASK: "ask",
                ActionKind.CONFIRM: "confirm",
                ActionKind.OFFER_SPELL: "offer_spell",
            }[act.kind]
            state = State.CONFIRMING if act.kind == ActionKind.CONFIRM else State.ASKING
            await self._prompt(kind, stage, act.question, rephrased=act.rephrased, state=state)
            if act.candidates:
                self.log.write(
                    "candidates", stage=stage, candidates=[c.to_dict() for c in act.candidates]
                )
        elif act.kind == ActionKind.FINALIZE:
            assert act.hypothesis is not None
            await self._finalize(act.hypothesis, stage)
        elif act.kind == ActionKind.ENTER_SPELLING:
            await self._enter_spelling()
        elif act.kind == ActionKind.PAUSE:
            await self._pause("patient asked to stop")
        elif act.kind == ActionKind.CAREGIVER:
            await self._caregiver(act.reason or "unclear", keep_prompt=act.question is not None)
        elif act.kind == ActionKind.EMERGENCY:
            await self._emergency_locked("engine")

    async def _apply_sentence(self, act: Action) -> None:
        self.stage = "sentence"
        if act.kind == ActionKind.FINALIZE and act.hypothesis and act.hypothesis.id == KEEP_ID:
            await self._resume_spelling()
            return
        if act.kind in (ActionKind.OFFER_SPELL, ActionKind.ENTER_SPELLING):
            await self._resume_spelling()
            return
        await self._apply_decider_action(act, "sentence")

    async def _apply_refine(self, act: Action) -> None:
        self.stage = "refine"
        if act.kind in (ActionKind.OFFER_SPELL, ActionKind.ENTER_SPELLING):
            await self._done()
            return
        await self._apply_decider_action(act, "refine")

    # ================================================================ spelling
    async def _enter_spelling(self) -> None:
        self.stage = "spelling"
        self.spelling = SpellingDecider(self.lang, self.cfg, self.a, self.b)
        self.log.write("spelling_start")
        await self._next_spell_prompt()

    async def _resume_spelling(self) -> None:
        self.stage = "spelling"
        if self.spelling is None:
            await self._enter_spelling()
            return
        if self.spelling.text and not self.spelling.text.endswith(" "):
            self.spelling.text += " "
        self.spelling.done = False
        self.spelling.set_completions([])
        await self._next_spell_prompt()

    async def _next_spell_prompt(self) -> None:
        assert self.spelling is not None
        if self.spelling.n_questions >= self.cfg.spelling_max_prompts:
            await self._caregiver("spelling_stuck")
            return
        sp: SpellPrompt = self.spelling.next_prompt()
        await self._prompt(
            "spelling",
            "spelling",
            sp.question,
            rephrased=sp.rephrased,
            group=sp.group,
            word=sp.word,
            state=State.SPELLING,
            sub=sp.stage,
        )

    async def _handle_spelling(self, obs: Observation) -> None:
        assert self.spelling is not None
        if obs.answer not in (Answer.YES, Answer.NO):
            await self._unclear_simple()
            return
        out = self.spelling.observe(obs)
        self.log.write("spelling", event=str(out.event), text=_redact_if_sensitive(out.text))
        if out.event == SpellEvent.SENSITIVE:
            await self._finalize_text(
                None, out.text, out.text, "spelling", sensitive=out.sensitive.to_dict()
            )
            return
        if out.event == SpellEvent.STUCK:
            await self._caregiver("spelling_stuck")
            return
        if out.event in (SpellEvent.WORD, SpellEvent.END):
            await self._offer_sentences(out.text.strip())
            return
        cur = self.spelling.current_word
        if len(cur) >= 2 and out.event in (
            SpellEvent.LETTER,
            SpellEvent.UNDO,
            SpellEvent.REJECTED_WORD,
            SpellEvent.CHECKPOINT_FIX,
        ):
            res = await self.ctx.roles.complete_word(
                self.mode, cur, self.spelling.text, self.lang, self.evidence.to_list()
            )
            self._record_call(res.meta.to_dict())
            self.spelling.set_completions(
                [
                    (w.word.upper(), w.p)
                    for w in res.data.words
                    if re.fullmatch(r"[A-Za-z]+", w.word)
                ]
            )
        await self._next_spell_prompt()

    async def _offer_sentences(self, text: str) -> None:
        if await self._sensitive_check(text):
            return
        self.sentence_rounds += 1
        if self.sentence_rounds > self.cfg.sentence_max_rounds:
            await self._caregiver("spelling_stuck")
            return
        res = await self.ctx.roles.build_sentences(
            self.mode,
            text,
            self.lang,
            self.evidence.to_list(),
            [{"name": p.name, "relation": p.relation} for p in self.persons],
        )
        self._record_call(res.meta.to_dict())
        sentences = []
        for s in res.data.sentences[:3]:
            if detect(s.text_en).sensitive or detect(s.text_id).sensitive:
                continue
            from app.safety.advice import message_problems

            if message_problems(s.text_en) or message_problems(s.text_id):
                continue
            sentences.append((s.text_en, s.text_id, s.p))
        hyps, prior, questions = sentence_stage(text, sentences)
        self.sentence = MessageDecider(hyps, prior, questions, self.cfg, self.a, self.b)
        self.stage = "sentence"
        self.log.write("sentence_options", options=[h.to_dict() for h in hyps])
        await self._apply_sentence(self.sentence.next_action())

    async def _sensitive_check(self, text: str) -> bool:
        res = detect(text)
        cats = list(res.categories)
        if not res.sensitive and self.ctx.hub.resolve(self.mode).effective != Mode.MOCK:
            llm = await self.ctx.roles.classify_sensitive(self.mode, text)
            self._record_call(llm.meta.to_dict())
            if llm.data.sensitive:
                cats = llm.data.categories or ["unspecified"]
        if cats:
            await self._finalize_text(
                None,
                text,
                text,
                "spelling",
                sensitive={"sensitive": True, "categories": cats, "method": "keywords+llm"},
            )
            return True
        return False

    # ================================================================ messages
    async def _finalize(self, h: Hypothesis, stage: str) -> None:
        source = (
            "spelling"
            if h.source == HypothesisSource.SPELLING
            else ("refinement" if stage == "refine" else "engine")
        )
        if source == "spelling" and await self._sensitive_check(h.text_en):
            return
        await self._finalize_text(h.id, h.text_en, h.text_id, source, urgent=h.urgent)

    async def _finalize_text(
        self,
        hid: str | None,
        text_en: str,
        text_id: str,
        source: str,
        *,
        urgent: bool = False,
        sensitive: dict[str, Any] | None = None,
    ) -> None:
        msg = Message(
            new_id("msg"),
            hid,
            text_en,
            text_id,
            source,
            "speaking",
            urgent,
            bool(sensitive),
            list((sensitive or {}).get("categories", [])),
            self.questions_this_message,
        )
        self.message = msg
        if sensitive:
            msg.status = "needs_verification"
            self.alerts.append(
                {
                    "kind": "sensitive",
                    "at": now_iso(),
                    "message_id": msg.id,
                    "categories": msg.categories,
                    "text": "Verify in person with the patient.",
                }
            )
            self.log.write(
                "message",
                status=msg.status,
                categories=msg.categories,
                text="[sensitive, redacted]",
            )
            self.prompt = None
            await self._caregiver("sensitive_verify")
            await self._notify({"type": "sensitive", "message_id": msg.id})
            return
        if urgent:
            self.alerts.append(
                {"kind": "urgent", "at": now_iso(), "message_id": msg.id, "text": msg.text_en}
            )
            await self._notify({"type": "alert", "text": msg.text_en})
        self.log.write(
            "message",
            status="speaking",
            hypothesis_id=hid,
            text_en=text_en,
            source=source,
            questions=msg.questions,
        )
        await self._speak_message()

    async def _speak_message(self) -> None:
        assert self.message is not None
        self.prompt_seq += 1
        text = self.message.text_id if self.lang == "id" else self.message.text_en
        self.prompt = Prompt(f"p{self.prompt_seq}", "message", "speak", text, self.message.text_en)
        self._to(State.SPEAKING, "speak confirmed message")
        if self.auto_speak:
            self._spawn(self._auto_spoken(self.prompt.id))

    async def _post_check(self) -> None:
        self.stage = "post_check"
        await self._prompt(
            "post_check", "post_check", post_check_question(), state=State.POST_CHECK
        )

    async def _message_confirmed(self) -> None:
        msg = self.message
        assert msg is not None
        msg.status = "confirmed"
        self.messages.append(msg)
        self.ctx.store.add_message(
            id=msg.id,
            session_id=self.id,
            patient_id=self.pid,
            hypothesis_id=msg.hypothesis_id,
            text_en=None if msg.sensitive else msg.text_en,
            text_id=None if msg.sensitive else msg.text_id,
            source=msg.source,
            status="confirmed",
            questions=msg.questions,
            sensitive=msg.sensitive,
        )
        self.log.write(
            "message",
            status="confirmed",
            hypothesis_id=msg.hypothesis_id,
            text_en="[sensitive, redacted]" if msg.sensitive else msg.text_en,
            questions=msg.questions,
        )
        if msg.hypothesis_id == "pain" and not self.refined:
            self.refined = True
            self.pain_parent = msg
            self.stage = "refine_offer"
            await self._prompt("refine_offer", "refine_offer", offer_question())
            return
        if (
            msg.source == "refinement"
            and msg.hypothesis_id
            and msg.hypothesis_id.startswith("pain_loc:")
        ):
            self.stage = "worse"
            await self._prompt("worse", "worse", worse_question())
            return
        await self._done()

    async def _message_retracted(self) -> None:
        msg = self.message
        assert msg is not None
        msg.status = "retracted"
        self.messages.append(msg)
        self.ctx.store.add_message(
            id=msg.id,
            session_id=self.id,
            patient_id=self.pid,
            hypothesis_id=msg.hypothesis_id,
            text_en=msg.text_en,
            text_id=msg.text_id,
            source=msg.source,
            status="retracted",
            questions=msg.questions,
            sensitive=msg.sensitive,
        )
        self.log.write(
            "message", status="retracted", hypothesis_id=msg.hypothesis_id, text_en=msg.text_en
        )
        self.message = None
        hid = msg.hypothesis_id
        self.retractions += 1
        if self.retractions >= 2:
            # Safety rule 9: repeated "No, that's not what I said" means the answers are not reliable.
            await self._caregiver("inconsistent")
            return
        if msg.source == "refinement" and self.refine is not None and hid:
            await self._apply_refine(self.refine.retract(hid))
        elif msg.source == "spelling" and self.sentence is not None:
            await self._apply_sentence(self.sentence.retract(hid or ""))
        elif self.decider is not None and hid and hid in self.decider.index:
            await self._apply_main(self.decider.retract(hid))
        else:
            await self._done()

    async def _done(self) -> None:
        self.prompt = None
        self.stage = "done"
        self._to(State.DONE, "message complete")
        self.log.write(
            "message_done", index=self.message_index, questions=self.questions_this_message
        )

    # ================================================================ side states
    async def _caregiver(self, reason: str, keep_prompt: bool = False) -> None:
        self.caregiver_reason = reason
        if not keep_prompt and reason != "sensitive_verify":
            self.prompt = None
        self._to(State.CAREGIVER_NEEDED, reason)
        self.log.write("caregiver_needed", reason=reason)

    async def _pause(self, reason: str) -> None:
        self.prompt = None
        self._to(State.PAUSED, reason)
        self.log.write("paused", reason=reason)

    async def emergency(self, source: str) -> None:
        async with self.lock:
            await self._emergency_locked(source)
        await self._notify(
            {"type": "alarm", "text": EMERGENCY_TEXT[self.lang], "text_en": EMERGENCY_TEXT["en"]}
        )

    async def _emergency_locked(self, source: str) -> None:
        self.emergency_active = True
        self.prompt = None
        self._to(State.EMERGENCY, source)
        self.alerts.append(
            {"kind": "emergency", "at": now_iso(), "source": source, "text": EMERGENCY_TEXT["en"]}
        )
        self.ctx.store.add_event(self.pid, self.id, "emergency", source)
        self.log.write("emergency", source=source)

    # ================================================================ caregiver
    async def override(self, action: str) -> dict[str, Any]:
        """Human override everywhere (Safety rule 10). Logged and shown with a badge."""
        self.log.write("override", action=action, state=str(self.state))
        if action in ("yes", "no", "unclear"):
            if not self.prompt:
                return {"ok": False, "reason": "no pending question"}
            obs = Observation(
                Answer(action),
                0.97,
                {"sources": {"caregiver": {"answer": action}}},
                overridden=True,
            )
            ok = await self.observe(self.prompt.id, obs, "caregiver")
            return {"ok": ok}
        if action == "emergency":
            await self.emergency("caregiver_button")
            return {"ok": True}
        async with self.lock:
            result = await self._override_locked(action)
        await self._notify()
        return result

    async def _override_locked(self, action: str) -> dict[str, Any]:
        if action == "skip":
            if self.state == State.LISTENING:
                self._to(State.PROCESSING, "caregiver skip")
            if self.stage == "main" and self.decider is not None:
                await self._apply_main(self.decider.skip())
            elif self.stage == "spelling" and self.spelling is not None:
                await self._next_spell_prompt()
            elif self.stage == "sentence" and self.sentence is not None:
                await self._apply_sentence(self.sentence.skip())
            else:
                await self._done()
        elif action == "spell":
            await self._enter_spelling()
        elif action == "pause":
            await self._pause("caregiver")
        elif action == "resume":
            if self.state in (State.PAUSED, State.CAREGIVER_NEEDED, State.EMERGENCY):
                self.emergency_active = False
                await self._resume()
        elif action == "ack_emergency":
            self.emergency_active = False
            self.alerts = [a for a in self.alerts if a["kind"] != "emergency"]
            await self._pause("emergency acknowledged")
        elif action in ("ack_sensitive", "ack_sensitive_silent"):
            if self.message and self.message.status == "needs_verification":
                self.alerts = [a for a in self.alerts if a.get("message_id") != self.message.id]
                if action == "ack_sensitive":
                    self.message.status = "speaking"
                    await self._speak_message()
                else:
                    self.message.status = "confirmed"
                    await self._message_confirmed()
        elif action == "new_message":
            await self._begin_message()
        elif action == "refresh_context":
            await self._refresh_context()
        elif action == "end":
            await self._end_locked()
        else:
            return {"ok": False, "reason": f"unknown action {action}"}
        return {"ok": True}

    async def _resume(self) -> None:
        """Continue the current message if there is one, otherwise start a new one."""
        if (
            self.stage == "main"
            and self.decider is not None
            and self.decider.finalized is None
            and self.trail
        ):
            self.decider.n_questions = min(self.decider.n_questions, self.cfg.max_questions - 2)
            self._to(State.CONTEXT_REFRESH, "resume")
            await self._apply_main(self.decider.next_action())
        elif self.stage == "spelling" and self.spelling is not None:
            self._to(State.SPELLING, "resume spelling")
            self.spelling.n_letter_q = 0
            await self._next_spell_prompt()
        else:
            await self._begin_message()

    async def end(self) -> None:
        async with self.lock:
            await self._end_locked()
        await self._notify()

    async def _end_locked(self) -> None:
        if self.ended:
            return
        self.ended = True
        self.prompt = None
        self._to(State.DONE, "session ended")
        summary = self.summary()
        self.ctx.store.update_session(self.id, str(self.state), summary, ended=True)
        self.log.write("session_end", summary=summary)

    # ================================================================ context inputs
    async def add_event(self, kind: str, label: str | None) -> dict[str, Any]:
        e = self.ctx.store.add_event(self.pid, self.id, kind, label)
        self.log.write("caregiver_event", kind=kind, label=label)
        await self._notify()
        return e

    async def add_transcript(self, speaker: str, text: str) -> dict[str, Any]:
        t = self.ctx.store.add_transcript(self.pid, self.id, speaker, text)
        self.log.write("transcript", speaker=speaker, chars=len(text))
        await self._notify()
        return t

    async def add_audio(self, path: Path) -> list[dict[str, Any]]:
        from app.perception.media import to_wav

        wav = await to_wav(path, path.with_suffix(".wav"), 16000)
        keywords = [p.name for p in self.persons]
        tr = self.ctx.hub.transcriber(self.mode)
        result = await tr.transcribe(wav, self.lang, keywords)
        self.ctx.hub.record_transcript(result)
        added = [
            self.ctx.store.add_transcript(self.pid, self.id, s.speaker, s.text, s.start, s.end)
            for s in result.segments
        ]
        for p in (path, wav):
            p.unlink(missing_ok=True)
        self.log.write(
            "transcribe",
            provider=result.provider,
            segments=len(added),
            latency_ms=result.latency_ms,
        )
        await self._notify()
        return added

    async def add_snapshot(self, path: Path) -> list[str]:
        from app.perception.media import file_hash

        h = file_hash(path)
        cached = [
            f["text"]
            for f in self.ctx.store.scene_facts(self.pid, self.id)
            if f["snapshot_hash"] == h
        ]
        if cached:  # deterministic result for an identical snapshot: don't pay twice
            path.unlink(missing_ok=True)
            return cached
        res = await self.ctx.roles.read_scene(self.mode, path, self.scenario.get("scene_hint"))
        self._record_call(res.meta.to_dict())
        facts = [f for f in res.data.facts if f][:8]
        for f in facts:
            self.ctx.store.add_scene_fact(self.pid, self.id, f, h)
        if not self.ctx.settings.raw["app"].get("keep_clips_for_evaluation"):
            path.unlink(missing_ok=True)
        await self._notify()
        return facts

    # ================================================================ views
    def _top_posterior(self, k: int = 8) -> list[dict[str, Any]]:
        d = {"main": self.decider, "sentence": self.sentence, "refine": self.refine}.get(
            self.stage
        ) or self.decider
        if d is None:
            return []
        out = []
        for h, p in d.top(k):
            term = self.prior_terms.get(h.id) if d is self.decider else None
            out.append(
                {
                    "id": h.id,
                    "text_en": h.text_en,
                    "text_id": h.text_id,
                    "p": round(p, 4),
                    "prior": round(term.final, 4) if term else None,
                    "chips": [c.__dict__ for c in term.chips] if term else [],
                    "bounded": term.bounded if term else None,
                    "personal": round(term.personal, 3) if term else None,
                    "source": str(h.source),
                    "urgent": h.urgent,
                }
            )
        return out

    def view(self) -> dict[str, Any]:
        """Snapshot pushed to both screens. The patient screen never shows probabilities."""
        info = self.ctx.hub.resolve(self.mode)
        d = self.decider
        other_p = d.posterior().get("other") if d else None
        prompt = self.prompt.to_dict(self.lang, self.honorific) if self.prompt else None
        sp = self.spelling
        return {
            "session_id": self.id,
            "patient": {
                "id": self.pid,
                "display_name": self.patient.get("display_name"),
                "language": self.lang,
                "honorific": self.honorific,
            },
            "mode": info.to_dict(),
            "state": str(self.state),
            "stage": self.stage,
            "prompt": prompt,
            "listening": self.state == State.LISTENING,
            "posterior": self._top_posterior(8),
            "other_p": round(other_p, 4) if other_p is not None else None,
            "questions": self.questions_this_message,
            "max_questions": self.cfg.max_questions,
            "trail": self.trail[-20:],
            "spelling": {
                "text": sp.text,
                "top": sp.top_symbols(5),
                "completions": sp.completions[:5],
            }
            if sp
            else None,
            "sentence_options": [h.to_dict() for h in self.sentence.hyps]
            if self.sentence
            else None,
            "message": self.message.to_dict() if self.message else None,
            "messages": [m.to_dict() for m in self.messages[-10:]],
            "evidence": self.evidence.to_list(),
            "caregiver_reason": self.caregiver_reason,
            "caregiver_text": CAREGIVER_REASONS.get(self.caregiver_reason or ""),
            "alerts": self.alerts[-5:],
            "emergency": self.emergency_active,
            "signals": (self.calibration.get("description") or {}),
            "calibration": {
                "skipped": self.calibration.get("skipped", False),
                "error_rates": {"a": self.a, "b": self.b},
                "accuracy": self.calibration.get("accuracy", {}),
            },
            "overlay": self.overlay,
            "llm_calls": self.llm_calls[-12:],
            "rejected": self.rejected[-10:],
            "message_index": self.message_index,
            "ended": self.ended,
            "budget": self.ctx.hub.cost.status().to_dict(),
        }

    def summary(self) -> dict[str, Any]:
        confirmed = [m for m in self.messages if m.status == "confirmed"]
        return {
            "messages": len(self.messages),
            "confirmed": len(confirmed),
            "retracted": sum(m.status == "retracted" for m in self.messages),
            "questions_per_confirmed": [m.questions for m in confirmed],
            "started_at": self.started_at,
            "ended_at": now_iso(),
            "mode": str(self.mode),
        }


def _ago(minutes: float) -> str:
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    return f"{minutes / 60:.1f} h ago"


def _redact_if_sensitive(text: str) -> str:
    return "[sensitive, redacted]" if detect(text).sensitive else text
