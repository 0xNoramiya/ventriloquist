"""Evidence store (brief 10.1). Every prior multiplier must cite one of these ids; the caregiver view
shows them as chips. S# scene facts, T# transcript segments, E# caregiver events, M# memory facts,
H# earlier confirmed messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

PREFIX = {"scene": "S", "transcript": "T", "event": "E", "memory": "M", "history": "H"}


def minutes_between(earlier_iso: str, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    try:
        then = datetime.fromisoformat(earlier_iso)
    except ValueError:
        return 0.0
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return max((now - then).total_seconds() / 60.0, 0.0)


@dataclass
class Evidence:
    id: str
    kind: str
    text: str
    at: str | None = None
    ref: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def minutes_ago(self, now: datetime | None = None) -> float | None:
        return minutes_between(self.at, now) if self.at else None

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        mins = self.minutes_ago(now)
        return {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "at": self.at,
            "ref": self.ref,
            "minutes_ago": round(mins, 1) if mins is not None else None,
            **self.extra,
        }


class EvidenceStore:
    def __init__(self) -> None:
        self.items: dict[str, Evidence] = {}
        self._counts: dict[str, int] = {}

    def add(
        self, kind: str, text: str, at: str | None = None, ref: str | None = None, **extra: Any
    ) -> Evidence:
        prefix = PREFIX[kind]
        self._counts[prefix] = self._counts.get(prefix, 0) + 1
        ev = Evidence(f"{prefix}{self._counts[prefix]}", kind, text.strip(), at, ref, extra)
        self.items[ev.id] = ev
        return ev

    def ids(self) -> set[str]:
        return set(self.items)

    def texts(self) -> dict[str, str]:
        return {k: v.text for k, v in self.items.items()}

    def get(self, eid: str) -> Evidence | None:
        return self.items.get(eid)

    def to_list(self, now: datetime | None = None) -> list[dict[str, Any]]:
        return [e.to_dict(now) for e in self.items.values()]
