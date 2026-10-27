"""Family relay: an agent that carries a confirmed message to a family member and brings the reply
back to the patient.

1. offer    For a message about a family member ("Please call my son, Rizal", "I want to see my
            daughter, Aisyah", "Tell my family I'm okay"), the patient is asked "Shall I send this
            to Rizal on WhatsApp?". Only family the caregiver added with a phone number and the
            relative's consent can be offered. Sensitive messages are never relayed.
2. approve  A caregiver approves the exact text first (config relay.require_approval, on by default).
3. send     WhatsApp Cloud API, or a simulated relative without an account. The patient's words go
            verbatim inside a fixed frame; no model writes what the family receives.
4. follow   Delivery and read receipts update the caregiver screen. No reply within
            relay.reply_timeout_s: the caregiver is told and, when the phone is idle, the patient is
            asked whether to try the next relative.
5. reply    Muse Spark turns the reply into one or two short sentences for the patient and flags what
            a caregiver should read first (health or treatment, bad news, distress). Unflagged replies
            are read aloud on the patient's phone when it is idle; flagged ones wait for a caregiver.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.engine.taxonomy import slugify
from app.engine.types import Question, QuestionKind
from app.providers.registry import Mode
from app.storage import new_id, now_iso

from .channels import SendResult, SimulatedChannel, mask_phone, normalise_phone

if TYPE_CHECKING:
    from app.sessions.session import Message, Session

PERSON_MESSAGES = ("call_person:", "see_person:", "where_person:")
FAMILY_MESSAGES = ("tell_family_ok",)
OPEN = ("sent", "delivered", "read")


@dataclass(frozen=True)
class Contact:
    name: str
    relation: str
    phone: str


def contacts_of(patient: dict[str, Any]) -> list[Contact]:
    """Family members with a phone number whose consent to receive messages was recorded."""
    out = []
    for p in patient.get("family") or []:
        phone = normalise_phone(p.get("phone") or "")
        if phone and p.get("relay_consent"):
            out.append(Contact(p["name"], p.get("relation", ""), phone))
    return out


@dataclass
class Relay:
    id: str
    message_id: str
    contact: Contact
    patient_text: str  # the patient's confirmed words, in their language
    status: str = "awaiting_approval"  # | sending | sent | delivered | read | review | replied |
    #                                    read_to_patient | no_reply | cancelled | failed
    simulated: bool = True
    channel_id: str | None = None
    send_kind: str | None = None  # template | text | simulated
    reply: dict[str, Any] | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    created: str = field(default_factory=now_iso)

    def note(self, kind: str, text: str | None = None) -> None:
        self.events.append({"at": now_iso(), "kind": kind, **({"text": text} if text else {})})

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "message_id": self.message_id,
            "to": self.contact.name,
            "relation": self.contact.relation,
            "phone": mask_phone(self.contact.phone),
            "patient_text": self.patient_text,
            "status": self.status,
            "simulated": self.simulated,
            "send_kind": self.send_kind,
            "reply": self.reply,
            "events": self.events[-12:],
            "created": self.created,
        }


def relay_offer_question(contact: Contact, previous: Contact | None = None) -> Question:
    if previous is None:
        en = f"Shall I send this to {contact.name} on WhatsApp?"
        idn = f"Boleh saya kirim pesan ini ke {contact.name} lewat WhatsApp?"
    else:
        en = f"{previous.name} has not replied. Shall I send it to {contact.name} instead?"
        idn = f"{previous.name} belum membalas. Boleh saya kirim ke {contact.name}?"
    return Question(
        id=f"relay:offer:{slugify(contact.name)}",
        text_en=en,
        text_id=idn,
        kind=QuestionKind.META,
        yes_ids=frozenset({"relay"}),
    )


class RelayAgent:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.cfg: dict[str, Any] = session.ctx.settings.section("relay")
        shared = getattr(session.ctx, "relay_channel", None)
        # Real WhatsApp only in live mode and never for demo scenarios (fictional relatives).
        if shared is not None and session.mode == Mode.LIVE and not session.scenario:
            self.channel: Any = shared  # replies arrive through the webhook (SessionManager)
        else:
            self.channel = SimulatedChannel(
                self.on_event, float(self.cfg.get("mock_reply_after_s", 8)), self._silent()
            )
        self.relays: list[Relay] = []
        self.to_read: list[str] = []  # relay ids whose reply waits for the phone to be idle
        self.followups: list[tuple[Relay, Contact]] = []  # offers to try the next relative
        self._timers: dict[str, asyncio.Task[Any]] = {}

    def _silent(self) -> set[str]:
        return {p for p in (normalise_phone(x) for x in self.cfg.get("mock_silent", [])) if p}

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True)) and bool(contacts_of(self.s.patient))

    # ------------------------------------------------------------------ offer
    def offer_for(self, msg: Message) -> Contact | None:
        """The relative a confirmed message is about, if they can receive it."""
        if not self.enabled or msg.sensitive or not msg.hypothesis_id:
            return None
        people = contacts_of(self.s.patient)
        hid = msg.hypothesis_id
        if hid.startswith(PERSON_MESSAGES):
            slug = hid.split(":", 1)[1]
            return next((c for c in people if slugify(c.name) == slug), None)
        if hid in FAMILY_MESSAGES:
            return people[0]
        return None

    def next_contact(self, relay: Relay) -> Contact | None:
        tried = {r.contact.phone for r in self.relays if r.message_id == relay.message_id}
        return next((c for c in contacts_of(self.s.patient) if c.phone not in tried), None)

    # ------------------------------------------------------------------ act
    async def start(self, msg: Message, contact: Contact) -> Relay:
        """The patient said YES to sending."""
        text = msg.text_id if self.s.lang == "id" else msg.text_en
        relay = Relay(new_id("rel"), msg.id, contact, text, simulated=bool(self.channel.simulated))
        relay.note("patient_yes")
        self.relays.append(relay)
        self.s.log.write("relay_start", relay_id=relay.id, to=contact.name, message_id=msg.id)
        if self.cfg.get("require_approval", True):
            relay.status = "awaiting_approval"
        else:
            await self._send(relay)
        return relay

    def find(self, relay_id: str) -> Relay | None:
        return next((r for r in self.relays if r.id == relay_id), None)

    async def approve(self, relay_id: str) -> bool:
        relay = self.find(relay_id)
        if relay is None or relay.status != "awaiting_approval":
            return False
        relay.note("approved")
        await self.s.acknowledge(relay.message_id)  # the caregiver has read the message
        await self._send(relay)
        return True

    async def cancel(self, relay_id: str) -> bool:
        relay = self.find(relay_id)
        if relay is None or relay.status not in ("awaiting_approval", *OPEN):
            return False
        relay.status = "cancelled"
        relay.note("cancelled")
        self._stop_timer(relay.id)
        self.s.log.write("relay_cancelled", relay_id=relay.id)
        return True

    async def _send(self, relay: Relay) -> None:
        relay.status = "sending"
        name = str(self.s.patient.get("display_name") or "")
        try:
            res: SendResult = await self.channel.send(
                relay.contact.phone, self.s.lang, name, relay.patient_text
            )
        except Exception as exc:
            relay.status = "failed"
            relay.note("failed", str(exc)[:160])
            self.s.log.write("relay_failed", relay_id=relay.id, error=str(exc)[:200])
            self._alert(relay, f"The message to {relay.contact.name} could not be sent.")
            return
        relay.channel_id, relay.send_kind = res.channel_id, res.kind
        relay.status = "sent"
        relay.note("sent")
        self.s.log.write("relay_sent", relay_id=relay.id, kind=res.kind)
        self._start_timer(relay)

    # ------------------------------------------------------------------ observe
    def owns(self, channel_id: str | None, phone: str) -> bool:
        return any(
            (channel_id and r.channel_id == channel_id) or (r.contact.phone == phone)
            for r in self.relays
        )

    async def on_event(
        self, kind: str, channel_id: str | None, phone: str, text: str | None
    ) -> None:
        """Receipts and replies from the channel (simulated, or the WhatsApp webhook)."""
        if kind == "reply":
            relay = next(
                (r for r in reversed(self.relays) if r.contact.phone == phone and r.status in OPEN),
                None,
            )
            if relay is not None and text:
                await self._reply(relay, text)
        else:
            relay = next((r for r in self.relays if r.channel_id == channel_id), None)
            if relay is None or relay.status not in OPEN:
                return
            if kind == "failed":
                relay.status = "failed"
                relay.note("failed")
                self._stop_timer(relay.id)
                self._alert(
                    relay, f"WhatsApp could not deliver the message to {relay.contact.name}."
                )
            elif kind in ("delivered", "read") and OPEN.index(kind) > OPEN.index(relay.status):
                relay.status = kind
                relay.note(kind)
        await self.s._notify()  # noqa: SLF001 - the session owns the subscribers

    async def _reply(self, relay: Relay, text: str) -> None:
        self._stop_timer(relay.id)
        relay.note("reply")
        res = await self.s.ctx.roles.read_relay_reply(
            self.s.mode,
            {
                "from": relay.contact.name,
                "relation": relay.contact.relation,
                "patient_language": self.s.lang,
                "patient_message": relay.patient_text,
                "reply": text,
            },
        )
        self.s._record_call(res.meta.to_dict())  # noqa: SLF001
        spoken = res.data.spoken.strip() if res.ok else ""
        # Fail safe: without a usable reading, a caregiver reads the reply first.
        review = (not res.ok) or res.data.needs_review or not spoken
        relay.reply = {
            "text": text,
            "spoken": spoken or text,
            "needs_review": review,
            "reason": (res.data.reason if res.ok else "") or ("" if not review else "check first"),
            "at": now_iso(),
            "read_at": None,
        }
        self.s.log.write("relay_reply", relay_id=relay.id, needs_review=review)
        if review:
            relay.status = "review"
            self._alert(
                relay, f"{relay.contact.name} replied. Please read it before the patient hears it."
            )
        else:
            relay.status = "replied"
            await self._read_or_queue(relay)

    async def read_to_patient(self, relay_id: str) -> bool:
        """A caregiver read a flagged reply and lets the phone say it."""
        relay = self.find(relay_id)
        if relay is None or relay.reply is None or relay.status not in ("review", "replied"):
            return False
        relay.reply["needs_review"] = False
        relay.note("caregiver_released")
        await self._read_or_queue(relay)
        return True

    async def _read_or_queue(self, relay: Relay) -> None:
        if self.s.idle:
            await self._read(relay)
        elif relay.id not in self.to_read:
            self.to_read.append(relay.id)

    async def _read(self, relay: Relay) -> None:
        assert relay.reply is not None
        relay.reply["read_at"] = now_iso()
        relay.status = "read_to_patient"
        relay.note("read_to_patient")
        self.s.log.write("relay_read", relay_id=relay.id)
        await self.s.say_to_patient(relay.reply["spoken"], kind="relay_reply")

    async def flush(self) -> None:
        """The phone is idle again: read replies that arrived during a conversation, then offer to
        try the next relative where nobody answered."""
        while self.to_read:
            relay = self.find(self.to_read.pop(0))
            if relay is not None and relay.reply and not relay.reply["needs_review"]:
                await self._read(relay)
        if self.followups:
            relay, contact = self.followups.pop(0)
            await self.s.offer_relay(relay.message_id, contact, previous=relay.contact)

    # ------------------------------------------------------------------ follow up
    def _start_timer(self, relay: Relay) -> None:
        self._timers[relay.id] = asyncio.ensure_future(self._no_reply_after(relay))

    def _stop_timer(self, relay_id: str) -> None:
        task = self._timers.pop(relay_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _no_reply_after(self, relay: Relay) -> None:
        await asyncio.sleep(float(self.cfg.get("reply_timeout_s", 900)))
        if relay.status not in OPEN:
            return
        relay.status = "no_reply"
        relay.note("no_reply")
        self._timers.pop(relay.id, None)
        self.s.log.write("relay_no_reply", relay_id=relay.id)
        nxt = self.next_contact(relay)
        self._alert(
            relay,
            f"{relay.contact.name} has not replied."
            + (f" The patient will be asked about {nxt.name}." if nxt else ""),
        )
        if nxt is not None:
            self.followups.append((relay, nxt))
            async with self.s.lock:  # may start a question: same rule as every other turn
                if self.s.idle:
                    await self.flush()
        await self.s._notify()  # noqa: SLF001

    def _alert(self, relay: Relay, text: str) -> None:
        self.s.alerts.append({"kind": "relay", "at": now_iso(), "relay_id": relay.id, "text": text})

    def close(self) -> None:
        for t in list(self._timers.values()):
            t.cancel()
        if isinstance(self.channel, SimulatedChannel):
            self.channel.close()
