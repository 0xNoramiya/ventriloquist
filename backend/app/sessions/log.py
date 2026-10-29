"""Session logs: data/logs/sessions/{sid}.jsonl, one JSON object per line.

Records every question, observation (with per-source outputs), posterior snapshot and LLM call
metadata (model, latency, tokens, cost). Sensitive spelled messages are redacted, and the names in
the patient's profile are replaced by their relation ("Aisyah" -> "[daughter]") so the log holds no
PII beyond the pseudonymous patient id.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from app.storage import now_iso


class SessionLog:
    def __init__(self, path: Path, names: dict[str, str] | None = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._redact = [
            (re.compile(rf"\b{re.escape(name)}\b", re.I), f"[{label}]")
            for name, label in sorted((names or {}).items(), key=lambda kv: -len(kv[0]))
            if name.strip()
        ]

    def write(self, kind: str, /, **data: Any) -> None:
        line = json.dumps({"ts": now_iso(), "event": kind, **data}, ensure_ascii=False, default=str)
        for pattern, label in self._redact:
            line = pattern.sub(label, line)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
