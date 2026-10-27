"""Mock providers: deterministic, rule-based stand-ins for every model role.

They make the whole product run end to end without API keys (APP_MODE=mock) and they are what the
simulator and tests use. They read the structured `context` of a request, never the prompt.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from app.engine.spelling import mock_completions
from app.engine.taxonomy import slugify
from app.safety.sensitive import detect

from .base import (
    LLMRequest,
    RawResponse,
    Segment,
    Transcriber,
    TranscriptResult,
    Usage,
    VisionLanguage,
)


def _mins(e: dict[str, Any]) -> float:
    v = e.get("minutes_ago")
    return float(v) if v is not None else 1e9


# (pattern, hypothesis ids, factor, reason)
KEYWORD_RULES: list[tuple[str, list[str], float, str]] = [
    (
        r"suction|secretion|mucus|gurgl|rattl|lendir|dahak|riak|grok",
        ["suction"],
        4,
        "secretions mentioned",
    ),
    (
        r"\bcold\b|chilly|shiver|freez|air[- ]?con|\bA/?C\b|\bAC\b|dingin|menggigil",
        ["cold"],
        2,
        "cold or air conditioning",
    ),
    (
        r"blanket (has )?slipped|without (a )?blanket|selimut(nya)? (jatuh|melorot)",
        ["cold"],
        2,
        "blanket off",
    ),
    (r"\bhot\b|sweat|panas|gerah|keringat", ["hot"], 2, "heat mentioned"),
    (r"bright|glare|silau|lampu terang", ["light"], 2, "bright light mentioned"),
    (r"noisy|noise|loud|alarm|berisik|bising", ["noise"], 2, "noise mentioned"),
    (
        r"thirst|dry (mouth|lips)|\bhaus\b|bibir kering|mulut kering",
        ["thirst"],
        2,
        "dry mouth mentioned",
    ),
    (
        r"\b(pray|prayer|praying|adzan|azan|sholat|shalat|maghrib|subuh|isya|church|doa|berdoa|mengaji)\b",
        ["pray"],
        2,
        "prayer time mentioned",
    ),
    (
        r"glasses|kacamata|hearing aid|alat bantu dengar",
        ["glasses_hearing"],
        2,
        "glasses or hearing aid mentioned",
    ),
    (r"\bphone\b|\bHP\b|ponsel|music|musik|lagu", ["phone_music"], 2, "phone or music mentioned"),
    (r"\bnight\b|malam|lights? (dimmed|off)", ["tired"], 2, "night time"),
    (
        r"(gaz|star|look)\w* (at|toward|towards) (the )?(window|door)",
        ["where", "what_happened"],
        2,
        "patient looking around",
    ),
]

PHOTO = re.compile(r"photo|picture|foto|potret", re.I)
GAZE = re.compile(r"gaz|star|look|melihat|menatap", re.I)
AWAY = re.compile(
    r"went home|gone home|back at|will be back|coming back|pulang|kembali|nanti", re.I
)


def mock_prior_builder(ctx: dict[str, Any]) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = ctx.get("evidence", [])
    hyp_ids = {h["id"] for h in ctx.get("hypotheses", [])}
    persons: list[dict[str, str]] = ctx.get("persons", [])
    person_hyps = [f"see_person:{slugify(p['name'])}" for p in persons]
    mults: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []

    def add(hids: list[str], factor: float, eid: str, reason: str) -> None:
        for h in hids:
            if h in hyp_ids:
                mults.append(
                    {"hypothesis_id": h, "factor": factor, "evidence_ids": [eid], "reason": reason}
                )

    for e in evidence:
        text, eid, kind = e.get("text", ""), e["id"], e.get("kind", "")
        if kind in ("scene", "transcript", "memory"):
            for pattern, hids, factor, reason in KEYWORD_RULES:
                if re.search(pattern, text, re.I):
                    add(hids, factor, eid, reason)
        for p in persons:
            if re.search(rf"\b{re.escape(p['name'])}\b", text, re.I):
                add([f"see_person:{slugify(p['name'])}"], 4, eid, f"{p['name']} mentioned")
                if kind == "transcript" and AWAY.search(text):
                    new.append(
                        {
                            "template": "where_person",
                            "slots": {"name": p["name"], "relation": p["relation"]},
                            "evidence_ids": [eid],
                        }
                    )
                    add([f"where_person:{slugify(p['name'])}"], 2, eid, f"{p['name']} is away")
        if kind == "scene" and PHOTO.search(text):
            add(
                person_hyps,
                2,
                eid,
                "family photo in view"
                + (" and patient looking at it" if GAZE.search(text) else ""),
            )
        if kind == "event":
            label, mins = e.get("event_kind", ""), _mins(e)
            if label == "suctioned":
                if mins <= 30:
                    add(["suction"], 0.5, eid, "suctioned recently")
                elif mins >= 120:
                    add(["suction"], 2, eid, f"last suction {mins / 60:.0f} h ago")
            elif label == "repositioned":
                if mins >= 120:
                    add(["position"], 2, eid, f"last repositioned {mins / 60:.0f} h ago")
                elif mins <= 30:
                    add(["position"], 0.5, eid, "repositioned recently")
            elif label == "mouth_care":
                add(
                    ["thirst"],
                    0.5 if mins <= 30 else (2 if mins >= 180 else 1),
                    eid,
                    "mouth care timing",
                )
            elif label == "visitor_left" and mins <= 60:
                add(person_hyps + ["company"], 2, eid, "a visitor just left")
            elif label == "visitor_arrived" and mins <= 30:
                add(["company"], 0.5, eid, "a visitor is here")
            elif label == "family_called" and mins <= 120:
                add(["tell_family_ok"], 2, eid, "family called")
            elif label == "procedure_done" and mins <= 180:
                add(["pain", "what_happened"], 2, eid, "after a procedure")
        if kind == "history":
            hid = e.get("hypothesis_id")
            if hid and _mins(e) <= 24 * 60:
                add([hid], 2, eid, "said recently")
    return {"multipliers": mults, "new_hypotheses": new[:3]}


def mock_question_proposer(ctx: dict[str, Any]) -> dict[str, Any]:
    evidence = ctx.get("evidence", [])
    hyp_ids = {h["id"] for h in ctx.get("hypotheses", [])}
    family = [h for h in hyp_ids if h.startswith("see_person:")]
    out: list[dict[str, Any]] = []
    for e in evidence:
        if e.get("kind") == "scene" and PHOTO.search(e.get("text", "")) and family:
            out.append(
                {
                    "text_en": "Is it about the photo by your bed?",
                    "text_id": "Apakah ini tentang foto di samping tempat tidur?",
                    "yes_ids": sorted(family),
                    "evidence_ids": [e["id"]],
                }
            )
            break
    for e in evidence:
        if re.search(r"air[- ]?con|\bAC\b", e.get("text", ""), re.I) and {"cold", "hot"} & hyp_ids:
            out.append(
                {
                    "text_en": "Is it about the air conditioning?",
                    "text_id": "Apakah ini tentang AC?",
                    "yes_ids": sorted({"cold", "hot"} & hyp_ids),
                    "evidence_ids": [e["id"]],
                }
            )
            break
    return {"questions": out[:5]}


def mock_calibration(ctx: dict[str, Any]) -> dict[str, Any]:
    hint = (ctx.get("hint") or "eyebrows").lower()
    presets = {
        "eyebrows": (
            {
                "body_part": "eyebrows",
                "motion": "raises both eyebrows",
                "sam_prompt": "eyebrows",
                "description": "Both eyebrows lift clearly for about one second.",
            },
            {
                "body_part": "eyes",
                "motion": "closes both eyes tightly",
                "sam_prompt": "eyes",
                "description": "Eyes squeeze shut for about one second.",
            },
        ),
        "blink": (
            {
                "body_part": "eyes",
                "motion": "one long blink",
                "sam_prompt": "eyes",
                "description": "Eyes close slowly and stay closed about one second.",
            },
            {
                "body_part": "eyes",
                "motion": "two quick blinks",
                "sam_prompt": "eyes",
                "description": "Two short blinks in a row.",
            },
        ),
        "finger": (
            {
                "body_part": "right index finger",
                "motion": "lifts the finger off the sheet",
                "sam_prompt": "finger",
                "description": "Index finger lifts and lowers once.",
            },
            {
                "body_part": "hand",
                "motion": "keeps the hand still and closes it",
                "sam_prompt": "hand",
                "description": "Hand closes into a loose fist.",
            },
        ),
        "nod": (
            {
                "body_part": "head",
                "motion": "small nod down and up",
                "sam_prompt": "head",
                "description": "Head tips down and back up once.",
            },
            {
                "body_part": "head",
                "motion": "small turn side to side",
                "sam_prompt": "head",
                "description": "Head turns slightly left and right.",
            },
        ),
    }
    yes, no = presets.get(hint, presets["eyebrows"])
    return {
        "yes": yes,
        "no": no,
        "distinct": True,
        "notes": "Mock description (no model was called).",
    }


SENTENCE_TABLE = {
    "KUCING": [
        ("Who is feeding my cat?", "Siapa yang memberi makan kucing saya?", 0.5),
        ("I miss my cat.", "Saya rindu kucing saya.", 0.3),
        ("Please bring a photo of my cat.", "Tolong bawakan foto kucing saya.", 0.2),
    ],
    "CAT": [
        ("Who is feeding my cat?", "Siapa yang memberi makan kucing saya?", 0.5),
        ("I miss my cat.", "Saya rindu kucing saya.", 0.3),
        ("Please bring a photo of my cat.", "Tolong bawakan foto kucing saya.", 0.2),
    ],
    "RUMAH": [
        ("I want to go home.", "Saya ingin pulang.", 0.5),
        ("Is everything okay at home?", "Apakah di rumah baik-baik saja?", 0.3),
    ],
    "HOME": [
        ("I want to go home.", "Saya ingin pulang.", 0.5),
        ("Is everything okay at home?", "Apakah di rumah baik-baik saja?", 0.3),
    ],
    "KERJA": [
        (
            "Please tell my work I am in hospital.",
            "Tolong kabari kantor saya bahwa saya dirawat.",
            0.6,
        )
    ],
    "WORK": [
        (
            "Please tell my work I am in hospital.",
            "Tolong kabari kantor saya bahwa saya dirawat.",
            0.6,
        )
    ],
}


def mock_sentences(ctx: dict[str, Any]) -> dict[str, Any]:
    words = [w for w in re.split(r"\s+", ctx.get("text", "").upper()) if w]
    for w in reversed(words):
        if w in SENTENCE_TABLE:
            return {
                "sentences": [{"text_en": e, "text_id": i, "p": p} for e, i, p in SENTENCE_TABLE[w]]
            }
    if not words:
        return {"sentences": []}
    phrase = " ".join(words).lower()
    for p in ctx.get("persons", []):
        if p["name"].lower() == phrase:
            return {
                "sentences": [
                    {
                        "text_en": f"I want to see {p['name']}.",
                        "text_id": f"Saya ingin bertemu {p['name']}.",
                        "p": 0.6,
                    }
                ]
            }
    return {
        "sentences": [
            {
                "text_en": f"I want to talk about: {phrase}.",
                "text_id": f"Saya ingin membicarakan: {phrase}.",
                "p": 0.4,
            }
        ]
    }


def mock_completer(ctx: dict[str, Any]) -> dict[str, Any]:
    words = mock_completions(ctx.get("prefix", ""), ctx.get("lang", "en"))
    return {"words": [{"word": w, "p": round(p, 4)} for w, p in words]}


def mock_scene(ctx: dict[str, Any]) -> dict[str, Any]:
    hint = ctx.get("scene_hint")
    if hint:
        return {"facts": list(hint)}
    return {
        "facts": [
            "A hospital bed with the patient lying semi-upright.",
            "Monitors and an infusion pole beside the bed.",
        ]
    }


def mock_judge(ctx: dict[str, Any]) -> dict[str, Any]:
    label = ctx.get("mock_label")
    if label in ("yes", "no", "emergency", "none"):
        return {
            "classification": label,
            "confidence": 0.85,
            "observed_movement": f"mock {label}",
            "frame_times": [],
        }
    return {
        "classification": "none",
        "confidence": 0.0,
        "observed_movement": "mock judge cannot see",
        "frame_times": [],
    }


def mock_curator(ctx: dict[str, Any]) -> dict[str, Any]:
    ops: list[dict[str, Any]] = []
    existing = {m["text"].lower() for m in ctx.get("memory", [])}
    counts = Counter(h["hypothesis_id"] for h in ctx.get("history", []) if h.get("hypothesis_id"))
    refs: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    for h in ctx.get("history", []):
        refs.setdefault(h.get("hypothesis_id", ""), []).append(h["id"])
        texts[h.get("hypothesis_id", "")] = h.get("text_en", "")
    for hid, n in counts.most_common(5):
        if n >= 2:
            text = f"Often says: “{texts[hid]}” ({n} confirmed times)."
            if text.lower() not in existing:
                ops.append(
                    {
                        "op": "add",
                        "text": text,
                        "category": "habit",
                        "source_refs": refs[hid][-3:],
                        "reason": "repeated confirmed message",
                    }
                )
    habit = re.compile(
        r"\b(always|usually|likes?|loves?|every (day|night|morning)|suka|biasanya|selalu|setiap)\b",
        re.I,
    )
    for t in ctx.get("transcript", []):
        if habit.search(t.get("text", "")) and not detect(t["text"]).sensitive:
            text = t["text"].strip()
            if text.lower() not in existing:
                ops.append(
                    {
                        "op": "add",
                        "text": text[:200],
                        "category": "said_in_room",
                        "source_refs": [t["id"]],
                        "reason": "habit or preference said in the room",
                    }
                )
    return {"ops": ops[:8]}


def mock_selector(ctx: dict[str, Any]) -> dict[str, Any]:
    memory = ctx.get("memory", [])
    blob = " ".join(e.get("text", "") for e in ctx.get("evidence", [])).lower()
    scored = []
    for m in memory:
        words = {w for w in re.findall(r"[a-z]{4,}", m.get("text", "").lower())}
        scored.append((sum(w in blob for w in words), m.get("created_at", ""), m["id"]))
    scored.sort(reverse=True)
    return {"entry_ids": [s[2] for s in scored[:10]]}


def mock_sensitive(ctx: dict[str, Any]) -> dict[str, Any]:
    res = detect(ctx.get("text", ""))
    return {"sensitive": res.sensitive, "categories": res.categories}


REVIEW_WORDS = (
    "sakit",
    "dokter",
    "obat",
    "operasi",
    "meninggal",
    "kecelakaan",
    "rumah sakit",
    "hutang",
    "doctor",
    "medicine",
    "surgery",
    "died",
    "passed away",
    "accident",
    "hospital",
    "debt",
)


def mock_relay_reply(ctx: dict[str, Any]) -> dict[str, Any]:
    reply = str(ctx.get("reply", "")).strip()
    lead = (
        "Balasan dari" if ctx.get("patient_language") == "id" else f"{ctx.get('from', '')} replied:"
    )
    spoken = (
        f"{lead} {ctx.get('from', '')}: {reply}"
        if ctx.get("patient_language") == "id"
        else f"{lead} {reply}"
    )
    flagged = detect(reply).sensitive or any(w in reply.lower() for w in REVIEW_WORDS)
    return {
        "spoken": spoken[:300],
        "needs_review": flagged,
        "reason": "mentions health or bad news" if flagged else "",
    }


def mock_framing(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "face_visible": True,
        "upper_body_visible": True,
        "lighting_ok": True,
        "advice": "Mock check: keep the face and shoulders in the frame.",
    }


MOCK_ROLES = {
    "prior_builder": mock_prior_builder,
    "question_proposer": mock_question_proposer,
    "calibration_describer": mock_calibration,
    "framing_check": mock_framing,
    "scene_reader": mock_scene,
    "blind_judge": mock_judge,
    "spelling_completer": mock_completer,
    "sentence_builder": mock_sentences,
    "sensitive_classifier": mock_sensitive,
    "relay_reply": mock_relay_reply,
    "memory_curator": mock_curator,
    "memory_selector": mock_selector,
}


class MockVisionLanguage(VisionLanguage):
    provider = "mock"

    async def complete(self, req: LLMRequest, repair: str | None = None) -> RawResponse:
        t0 = time.perf_counter()
        fn = MOCK_ROLES.get(req.role)
        payload = fn(req.context) if fn else {}
        return RawResponse(
            json.dumps(payload),
            "mock",
            f"mock-{req.model_key}",
            (time.perf_counter() - t0) * 1000,
            Usage(),
        )


class MockTranscriber(Transcriber):
    """Reads a sidecar `<audio>.txt` (one 'speaker: text' per line) if present; otherwise silence."""

    provider = "mock"

    async def transcribe(
        self, audio: Path, language: str | None, keywords: list[str]
    ) -> TranscriptResult:
        sidecar = audio.with_suffix(audio.suffix + ".txt")
        segments: list[Segment] = []
        if sidecar.exists():
            for line in sidecar.read_text(encoding="utf-8").splitlines():
                if ":" in line:
                    spk, text = line.split(":", 1)
                    segments.append(Segment(spk.strip(), text.strip()))
        return TranscriptResult(segments, "mock", "mock-transcribe", language)
