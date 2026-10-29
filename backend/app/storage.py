"""Local SQLite storage. Everything lives in ./data, which is gitignored.

Patients are identified by a pseudonymous id; no PII leaves this file except the display name the
caregiver typed (shown only on local screens).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
  id TEXT PRIMARY KEY, profile_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calibrations (
  patient_id TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
  started_at TEXT NOT NULL, ended_at TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, patient_id TEXT NOT NULL,
  hypothesis_id TEXT, text_en TEXT, text_id TEXT, source TEXT, status TEXT NOT NULL,
  questions INTEGER, sensitive INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, session_id TEXT, patient_id TEXT NOT NULL, kind TEXT NOT NULL,
  label TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transcript (
  id TEXT PRIMARY KEY, session_id TEXT, patient_id TEXT NOT NULL, speaker TEXT, text TEXT NOT NULL,
  start_s REAL, end_s REAL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scene_facts (
  id TEXT PRIMARY KEY, session_id TEXT, patient_id TEXT NOT NULL, text TEXT NOT NULL,
  snapshot_hash TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_entries (
  id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, text TEXT NOT NULL, category TEXT,
  source_type TEXT NOT NULL, source_ref TEXT, created_at TEXT NOT NULL, last_used_at TEXT,
  status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_ops (
  id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, op TEXT NOT NULL, entry_id TEXT, text TEXT,
  category TEXT, source_refs_json TEXT, reason TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE TABLE IF NOT EXISTS spend (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, provider TEXT, model TEXT, role TEXT,
  usd REAL NOT NULL, input_tokens INTEGER, output_tokens INTEGER, latency_ms REAL, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "media").mkdir(exist_ok=True)
        (data_dir / "logs" / "sessions").mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "ventriloquist.db"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def row(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        found = self.rows(sql, params)
        return found[0] if found else None

    def media_dir(self, *parts: str) -> Path:
        path = self.data_dir.joinpath("media", *parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def session_log_path(self, session_id: str) -> Path:
        return self.data_dir / "logs" / "sessions" / f"{session_id}.jsonl"

    def create_patient(self, profile: dict[str, Any]) -> str:
        pid = new_id("pt")
        self.execute("INSERT INTO patients VALUES (?,?,?)", (pid, json.dumps(profile), now_iso()))
        return pid

    def update_patient(self, pid: str, profile: dict[str, Any]) -> None:
        self.execute("UPDATE patients SET profile_json=? WHERE id=?", (json.dumps(profile), pid))

    def get_patient(self, pid: str) -> dict[str, Any] | None:
        r = self.row("SELECT * FROM patients WHERE id=?", (pid,))
        if not r:
            return None
        return {"id": r["id"], "created_at": r["created_at"], **json.loads(r["profile_json"])}

    def list_patients(self) -> list[dict[str, Any]]:
        return [
            {"id": r["id"], "created_at": r["created_at"], **json.loads(r["profile_json"])}
            for r in self.rows("SELECT * FROM patients ORDER BY created_at DESC")
        ]

    def delete_patient(self, pid: str) -> dict[str, int]:
        """Safety rule 12: 'Delete patient' wipes everything about them."""
        counts: dict[str, int] = {}
        session_ids = [
            r["id"] for r in self.rows("SELECT id FROM sessions WHERE patient_id=?", (pid,))
        ]
        for table, col in (
            ("messages", "patient_id"),
            ("events", "patient_id"),
            ("transcript", "patient_id"),
            ("scene_facts", "patient_id"),
            ("memory_entries", "patient_id"),
            ("memory_ops", "patient_id"),
            ("sessions", "patient_id"),
            ("calibrations", "patient_id"),
            ("patients", "id"),
        ):
            counts[table] = self.execute(f"DELETE FROM {table} WHERE {col}=?", (pid,)).rowcount
        for sid in session_ids:
            self.session_log_path(sid).unlink(missing_ok=True)
            shutil.rmtree(self.data_dir / "media" / "sessions" / sid, ignore_errors=True)
        shutil.rmtree(self.data_dir / "media" / "calibration" / pid, ignore_errors=True)
        counts["session_logs"] = len(session_ids)
        return counts

    def save_calibration(self, pid: str, data: dict[str, Any]) -> None:
        self.execute(
            "INSERT INTO calibrations VALUES (?,?,?) ON CONFLICT(patient_id) DO UPDATE SET "
            "data_json=excluded.data_json, updated_at=excluded.updated_at",
            (pid, json.dumps(data), now_iso()),
        )

    def get_calibration(self, pid: str) -> dict[str, Any] | None:
        r = self.row("SELECT data_json FROM calibrations WHERE patient_id=?", (pid,))
        return json.loads(r["data_json"]) if r else None

    def create_session(self, sid: str, pid: str, mode: str) -> None:
        self.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            (sid, pid, mode, "IDLE", now_iso(), None, None),
        )

    def update_session(
        self, sid: str, state: str, summary: dict[str, Any] | None = None, ended: bool = False
    ) -> None:
        self.execute(
            "UPDATE sessions SET state=?, summary_json=COALESCE(?, summary_json), ended_at=COALESCE(?, ended_at) WHERE id=?",
            (
                state,
                json.dumps(summary) if summary is not None else None,
                now_iso() if ended else None,
                sid,
            ),
        )

    def list_sessions(self, pid: str) -> list[dict[str, Any]]:
        out = []
        for r in self.rows("SELECT * FROM sessions WHERE patient_id=? ORDER BY started_at", (pid,)):
            r["summary"] = json.loads(r.pop("summary_json") or "null")
            out.append(r)
        return out

    def add_message(self, **m: Any) -> str:
        mid = m.get("id") or new_id("msg")
        self.execute(
            "INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                m["session_id"],
                m["patient_id"],
                m.get("hypothesis_id"),
                m.get("text_en"),
                m.get("text_id"),
                m.get("source"),
                m["status"],
                m.get("questions"),
                int(bool(m.get("sensitive"))),
                now_iso(),
            ),
        )
        return mid

    def messages(self, pid: str, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.rows(
                "SELECT * FROM messages WHERE patient_id=? AND status=? ORDER BY created_at",
                (pid, status),
            )
        return self.rows("SELECT * FROM messages WHERE patient_id=? ORDER BY created_at", (pid,))

    def add_event(
        self, pid: str, sid: str | None, kind: str, label: str | None = None
    ) -> dict[str, Any]:
        eid = new_id("ev")
        at = now_iso()
        self.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (eid, sid, pid, kind, label, at))
        return {"id": eid, "kind": kind, "label": label, "created_at": at}

    def events(self, pid: str, since_iso: str | None = None) -> list[dict[str, Any]]:
        if since_iso:
            return self.rows(
                "SELECT * FROM events WHERE patient_id=? AND created_at>=? ORDER BY created_at",
                (pid, since_iso),
            )
        return self.rows("SELECT * FROM events WHERE patient_id=? ORDER BY created_at", (pid,))

    def add_transcript(
        self,
        pid: str,
        sid: str | None,
        speaker: str,
        text: str,
        start_s: float | None = None,
        end_s: float | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        tid = new_id("tr")
        at = at or now_iso()
        self.execute(
            "INSERT INTO transcript VALUES (?,?,?,?,?,?,?,?)",
            (tid, sid, pid, speaker, text, start_s, end_s, at),
        )
        return {"id": tid, "speaker": speaker, "text": text, "created_at": at}

    def transcript(self, pid: str, since_iso: str | None = None) -> list[dict[str, Any]]:
        if since_iso:
            return self.rows(
                "SELECT * FROM transcript WHERE patient_id=? AND created_at>=? ORDER BY created_at",
                (pid, since_iso),
            )
        return self.rows("SELECT * FROM transcript WHERE patient_id=? ORDER BY created_at", (pid,))

    def add_scene_fact(
        self, pid: str, sid: str | None, text: str, snapshot_hash: str | None
    ) -> dict[str, Any]:
        fid = new_id("sc")
        at = now_iso()
        self.execute(
            "INSERT INTO scene_facts VALUES (?,?,?,?,?,?)", (fid, sid, pid, text, snapshot_hash, at)
        )
        return {"id": fid, "text": text, "created_at": at}

    def scene_facts(self, pid: str, sid: str | None = None) -> list[dict[str, Any]]:
        if sid:
            return self.rows(
                "SELECT * FROM scene_facts WHERE patient_id=? AND session_id=? ORDER BY created_at",
                (pid, sid),
            )
        return self.rows("SELECT * FROM scene_facts WHERE patient_id=? ORDER BY created_at", (pid,))

    def add_memory(
        self,
        pid: str,
        text: str,
        category: str | None,
        source_type: str,
        source_ref: str | None,
        status: str = "approved",
    ) -> str:
        mid = new_id("mem")
        self.execute(
            "INSERT INTO memory_entries VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, pid, text, category, source_type, source_ref, now_iso(), None, status),
        )
        return mid

    def memory(self, pid: str, status: str | None = "approved") -> list[dict[str, Any]]:
        if status:
            return self.rows(
                "SELECT * FROM memory_entries WHERE patient_id=? AND status=? ORDER BY created_at",
                (pid, status),
            )
        return self.rows(
            "SELECT * FROM memory_entries WHERE patient_id=? ORDER BY created_at", (pid,)
        )

    def get_memory(self, entry_id: str) -> dict[str, Any] | None:
        return self.row("SELECT * FROM memory_entries WHERE id=?", (entry_id,))

    def update_memory(self, entry_id: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE memory_entries SET {sets} WHERE id=?", (*fields.values(), entry_id))

    def delete_memory(self, pid: str, entry_id: str) -> bool:
        return (
            self.execute(
                "DELETE FROM memory_entries WHERE id=? AND patient_id=?", (entry_id, pid)
            ).rowcount
            > 0
        )

    def add_memory_op(self, pid: str, op: dict[str, Any]) -> str:
        oid = new_id("op")
        self.execute(
            "INSERT INTO memory_ops VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                oid,
                pid,
                op["op"],
                op.get("entry_id"),
                op.get("text"),
                op.get("category"),
                json.dumps(op.get("source_refs", [])),
                op.get("reason"),
                "pending",
                now_iso(),
                None,
            ),
        )
        return oid

    def memory_ops(self, pid: str, status: str | None = "pending") -> list[dict[str, Any]]:
        q = (
            "SELECT * FROM memory_ops WHERE patient_id=?"
            + (" AND status=?" if status else "")
            + " ORDER BY created_at"
        )
        rows = self.rows(q, (pid, status) if status else (pid,))
        for r in rows:
            r["source_refs"] = json.loads(r.pop("source_refs_json") or "[]")
        return rows

    def get_memory_op(self, oid: str) -> dict[str, Any] | None:
        r = self.row("SELECT * FROM memory_ops WHERE id=?", (oid,))
        if r:
            r["source_refs"] = json.loads(r.pop("source_refs_json") or "[]")
        return r

    def decide_memory_op(self, oid: str, status: str) -> None:
        self.execute(
            "UPDATE memory_ops SET status=?, decided_at=? WHERE id=?", (status, now_iso(), oid)
        )

    def add_spend(
        self,
        provider: str,
        model: str,
        role: str,
        usd: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.execute(
            "INSERT INTO spend (ts, provider, model, role, usd, input_tokens, output_tokens, latency_ms, detail_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                now_iso(),
                provider,
                model,
                role,
                usd,
                input_tokens,
                output_tokens,
                latency_ms,
                json.dumps(detail or {}),
            ),
        )

    def total_spend(self) -> float:
        r = self.row("SELECT COALESCE(SUM(usd), 0) AS total FROM spend")
        return float(r["total"]) if r else 0.0

    def spend_by_model(self) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT provider, model, COUNT(*) AS calls, SUM(usd) AS usd, AVG(latency_ms) AS avg_latency_ms "
            "FROM spend GROUP BY provider, model ORDER BY usd DESC"
        )

    def kv_get(self, key: str, default: Any = None) -> Any:
        r = self.row("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
