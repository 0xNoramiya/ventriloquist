"""Memory that compounds (brief 10.3-10.5, Safety rule 13).

After each session Muse Wonder reads the whole stay history (approved memory, confirmed messages,
room transcript, caregiver notes) and proposes add/update/retire operations. Validators enforce
provenance and hygiene; a caregiver approves or rejects every operation on /memory. Our SQLite store
stays the source of truth (auditable, deletable); nothing persists inside the model.
"""

from __future__ import annotations

from typing import Any

from app.providers.registry import Mode
from app.roles import Roles
from app.safety.advice import contains_advice
from app.safety.sensitive import detect
from app.storage import Store

SOURCE_TYPES = {"H": "patient_confirmed", "T": "transcript", "N": "caregiver"}


def build_payload(store: Store, pid: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Short ids for the model (H1, T1, N1, and memory ids as-is) mapped back to database refs."""
    refs: dict[str, str] = {}
    memory = store.memory(pid, "approved")
    for m in memory:
        refs[m["id"]] = f"memory:{m['id']}"
    history = []
    for i, m in enumerate([m for m in store.messages(pid, "confirmed") if not m["sensitive"]], 1):
        hid = f"H{i}"
        refs[hid] = f"message:{m['id']}"
        history.append(
            {
                "id": hid,
                "hypothesis_id": m["hypothesis_id"],
                "text_en": m["text_en"],
                "at": m["created_at"],
            }
        )
    transcript = []
    for i, t in enumerate(store.transcript(pid)[-200:], 1):
        if detect(t["text"]).sensitive:
            continue
        tid = f"T{i}"
        refs[tid] = f"transcript:{t['id']}"
        transcript.append(
            {"id": tid, "speaker": t["speaker"], "text": t["text"], "at": t["created_at"]}
        )
    notes = []
    for i, e in enumerate([e for e in store.events(pid) if e["kind"] == "note" and e["label"]], 1):
        nid = f"N{i}"
        refs[nid] = f"caregiver:{e['id']}"
        notes.append({"id": nid, "text": e["label"], "at": e["created_at"]})
    payload = {
        "memory": [
            {
                "id": m["id"],
                "text": m["text"],
                "category": m["category"],
                "source_type": m["source_type"],
            }
            for m in memory
        ],
        "history": history,
        "transcript": transcript,
        "caregiver_notes": notes,
    }
    return payload, refs


def validate_op(op: dict[str, Any], refs: dict[str, str], memory_ids: set[str]) -> list[str]:
    problems: list[str] = []
    kind = op.get("op")
    text = (op.get("text") or "").strip()
    cited = [r for r in op.get("source_refs", []) if r in refs]
    if kind in ("add", "update"):
        if not text:
            problems.append("empty_text")
        if detect(text).sensitive:
            problems.append("sensitive")
        if contains_advice(text):
            problems.append("clinical_or_advice")
        if not any(r[:1] in ("H", "T", "N") for r in cited):
            problems.append("no_provenance")
    if kind in ("update", "retire") and op.get("entry_id") not in memory_ids:
        problems.append("unknown_entry")
    if kind not in ("add", "update", "retire"):
        problems.append("bad_op")
    return problems


def source_type_for(refs: list[str]) -> str:
    for prefix in ("N", "H", "T"):
        if any(r.startswith(prefix) for r in refs):
            return SOURCE_TYPES[prefix]
    return "transcript"


async def curate(store: Store, roles: Roles, pid: str, mode: Mode) -> dict[str, Any]:
    payload, refs = build_payload(store, pid)
    if not payload["history"] and not payload["transcript"] and not payload["caregiver_notes"]:
        return {"proposed": 0, "rejected": [], "meta": None}
    res = await roles.curate_memory(mode, payload)
    memory_ids = {m["id"] for m in payload["memory"]}
    pending_texts = {o["text"].lower() for o in store.memory_ops(pid, "pending") if o.get("text")}
    proposed, rejected = 0, []
    for op in res.data.ops:
        d = op.model_dump()
        problems = validate_op(d, refs, memory_ids)
        if d.get("text", "").lower() in pending_texts:
            problems.append("duplicate_pending")
        if problems:
            rejected.append({"op": d, "problems": problems})
            continue
        cited = [r for r in d["source_refs"] if r in refs]
        store.add_memory_op(
            pid,
            {
                "op": d["op"],
                "entry_id": d.get("entry_id"),
                "text": d["text"].strip(),
                "category": d["category"],
                "source_refs": [{"id": r, "ref": refs[r]} for r in cited],
                "reason": d["reason"],
            },
        )
        proposed += 1
    return {"proposed": proposed, "rejected": rejected, "meta": res.meta.to_dict()}


def approve(store: Store, pid: str, op_id: str) -> dict[str, Any]:
    op = store.get_memory_op(op_id)
    if not op or op["patient_id"] != pid or op["status"] != "pending":
        raise KeyError(op_id)
    short_refs = [r["id"] for r in op["source_refs"]]
    source_ref = ",".join(r["ref"] for r in op["source_refs"])
    if op["op"] == "add":
        entry = store.add_memory(
            pid, op["text"], op["category"], source_type_for(short_refs), source_ref
        )
    elif op["op"] == "update":
        store.update_memory(op["entry_id"], text=op["text"], source_ref=source_ref)
        entry = op["entry_id"]
    else:
        store.update_memory(op["entry_id"], status="retired")
        entry = op["entry_id"]
    store.decide_memory_op(op_id, "approved")
    return {"entry_id": entry, "op": op["op"]}


def learning_curve(store: Store, pid: str) -> list[dict[str, Any]]:
    """Questions per confirmed message, per session, in order (brief 10.5)."""
    by_session: dict[str, list[int]] = {}
    started: dict[str, str] = {}
    for s in store.list_sessions(pid):
        started[s["id"]] = s["started_at"]
    for m in store.messages(pid, "confirmed"):
        if m["questions"] is None or m["source"] not in ("engine",):
            continue
        by_session.setdefault(m["session_id"], []).append(int(m["questions"]))
    out = []
    for sid, qs in sorted(by_session.items(), key=lambda kv: started.get(kv[0], "")):
        out.append(
            {
                "session_id": sid,
                "started_at": started.get(sid),
                "messages": len(qs),
                "mean_questions": round(sum(qs) / len(qs), 2),
            }
        )
    return out
