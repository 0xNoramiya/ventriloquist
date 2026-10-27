"""Channels that carry a patient's message to a family member.

WhatsApp: Meta's WhatsApp Cloud API. Request and webhook shapes follow the developer docs
(docs/API_NOTES.md, "WhatsApp Cloud API"); not yet run against a real account.
- send: POST https://graph.facebook.com/{version}/{phone-number-id}/messages with a Bearer token.
  Outside the 24-hour customer service window only a pre-approved template may be sent, so the
  first message is always the `patient_message` template (two body variables: the patient's name
  and their words). A free-form text is used only inside the window.
- replies and delivery receipts arrive at the webhook (`parse_webhook`), signed with HMAC-SHA256 of
  the raw body using the app secret, in `X-Hub-Signature-256: sha256=<hex>`.

Simulated: no account needed. A fictional family member receives, reads and replies after a few
seconds, so the whole loop can be shown and tested.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Settings
from app.storage import new_id

# (event kind, channel message id or None, phone, text or None): "sent" | "delivered" | "read" |
# "failed" | "reply"
RelayEvent = Callable[[str, str | None, str, str | None], Awaitable[None]]

WINDOW = timedelta(hours=24)


def normalise_phone(raw: str) -> str | None:
    """'+62 812-3456-7890' -> '+6281234567890'; None when it is not a plausible number."""
    digits = re.sub(r"\D", "", raw or "")
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def mask_phone(phone: str) -> str:
    return f"{phone[:3]} ••• {phone[-4:]}" if len(phone) > 7 else "•••"


@dataclass
class SendResult:
    channel_id: str
    kind: str  # "template" | "text" | "simulated"


class SimulatedChannel:
    """A fictional relative: delivered at once, read after a moment, replies after `reply_after_s`."""

    name = "simulated"
    simulated = True

    REPLIES = {
        "en": "Thank you for telling me. I'm on my way and will be there this evening.",
        "id": "Terima kasih sudah mengabari. Saya sedang menuju ke sana, sampai nanti sore.",
    }

    def __init__(self, on_event: RelayEvent, reply_after_s: float, silent: set[str] | None = None):
        self.on_event = on_event
        self.reply_after_s = reply_after_s
        self.silent = silent or set()  # numbers that never reply (tests, demos of the follow-up)
        self._tasks: set[asyncio.Task[Any]] = set()

    async def send(self, phone: str, lang: str, patient_name: str, patient_text: str) -> SendResult:
        cid = new_id("sim")
        task = asyncio.ensure_future(self._play(cid, phone, lang))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return SendResult(cid, "simulated")

    async def _play(self, cid: str, phone: str, lang: str) -> None:
        await asyncio.sleep(min(0.5, self.reply_after_s / 4))
        await self.on_event("delivered", cid, phone, None)
        if phone in self.silent:
            return
        await asyncio.sleep(self.reply_after_s / 3)
        await self.on_event("read", cid, phone, None)
        await asyncio.sleep(self.reply_after_s * 2 / 3)
        await self.on_event("reply", None, phone, self.REPLIES.get(lang, self.REPLIES["en"]))

    def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()


class WhatsAppChannel:
    """WhatsApp Cloud API. One per app: replies and receipts come back through the webhook."""

    name = "whatsapp"
    simulated = False

    def __init__(self, settings: Settings, token: str, phone_number_id: str) -> None:
        cfg = settings.section("relay").get("whatsapp", {})
        self.url = f"https://graph.facebook.com/{cfg.get('api_version', 'v26.0')}/{phone_number_id}/messages"
        self.token = token
        self.template = cfg.get("template", "patient_message")
        self.template_language: dict[str, str] = cfg.get(
            "template_language", {"en": "en", "id": "id"}
        )
        self.last_inbound: dict[str, datetime] = {}  # phone -> last message from them

    def body(self, phone: str, lang: str, patient_name: str, patient_text: str) -> dict[str, Any]:
        last = self.last_inbound.get(phone)
        if last is not None and datetime.now(UTC) - last < WINDOW:
            frame = {
                "en": f'{patient_name} asked us to send you this message: "{patient_text}"',
                "id": f'{patient_name} meminta kami mengirimkan pesan ini: "{patient_text}"',
            }
            return {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": phone,
                "type": "text",
                "text": {"preview_url": False, "body": frame.get(lang, frame["en"])},
            }
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "template",
            "template": {
                "name": self.template,
                "language": {"code": self.template_language.get(lang, "en")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": patient_name},
                            {"type": "text", "text": patient_text},
                        ],
                    }
                ],
            },
        }

    async def send(self, phone: str, lang: str, patient_name: str, patient_text: str) -> SendResult:
        import httpx

        body = self.body(phone, lang, patient_name, patient_text)
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                self.url, json=body, headers={"Authorization": f"Bearer {self.token}"}
            )
        if r.status_code >= 400:
            raise RuntimeError(f"WhatsApp send failed: HTTP {r.status_code} {r.text[:200]}")
        return SendResult(r.json()["messages"][0]["id"], body["type"])

    def note_inbound(self, phone: str) -> None:
        self.last_inbound[phone] = datetime.now(UTC)


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_webhook(payload: dict[str, Any]) -> list[tuple[str, str | None, str, str | None]]:
    """Webhook body -> (kind, channel message id, phone, text) events: text replies and
    sent/delivered/read/failed receipts. Everything else is ignored."""
    out: list[tuple[str, str | None, str, str | None]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for m in value.get("messages", []):
                if m.get("type") == "text" and m.get("from"):
                    out.append(("reply", m.get("id"), "+" + m["from"], m["text"]["body"]))
            for s in value.get("statuses", []):
                if s.get("status") in ("sent", "delivered", "read", "failed"):
                    phone = "+" + str(s.get("recipient_id", ""))
                    out.append((s["status"], s.get("id"), phone, None))
    return out
