"""Family relay: offer, consent, approval, send, receipts, reply triage, follow-up."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

from app.engine.types import Answer
from app.relay.agent import contacts_of
from app.relay.channels import WhatsAppChannel, normalise_phone, parse_webhook, verify_signature
from app.sessions.simulated import SimulatedPatient
from app.sessions.state_machine import State

from .conftest import make_session, run_until


def fast_relay(ctx, **over) -> None:
    ctx.settings.raw["relay"] = {
        "enabled": True,
        "require_approval": True,
        "reply_timeout_s": 60,
        "mock_reply_after_s": 0.3,
        "mock_silent": [],
        **over,
    }


async def until(cond, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


def test_only_consented_family_with_a_number_can_be_contacted():
    patient = {
        "family": [
            {
                "name": "Aisyah",
                "relation": "daughter",
                "phone": "+62 812-3456-7890",
                "relay_consent": True,
            },
            {
                "name": "Rizal",
                "relation": "son",
                "phone": "+62 811 000 111",
                "relay_consent": False,
            },
            {"name": "Siti", "relation": "wife", "relay_consent": True},
            {"name": "Budi", "relation": "brother", "phone": "12", "relay_consent": True},
        ]
    }
    assert [(c.name, c.phone) for c in contacts_of(patient)] == [("Aisyah", "+6281234567890")]
    assert normalise_phone("abc") is None


async def test_patient_says_yes_caregiver_approves_reply_is_read_aloud(ctx):
    fast_relay(ctx)
    events = []
    s = make_session(
        ctx, "daughter", SimulatedPatient(truth="see_person:aisyah", relay=True), events=events
    )
    await s.start()
    await run_until(s)
    offers = [t for t in s.trail if t.get("kind") == "relay_offer"]
    assert offers and "Aisyah" in offers[0]["text"]
    relay = s.relay.relays[0]
    assert relay.contact.name == "Aisyah" and relay.status == "awaiting_approval"
    assert relay.patient_text == "I want to see my daughter, Aisyah."
    assert await s.relay.approve(relay.id)
    assert s.messages[-1].acknowledged_at  # approving means a caregiver read the message
    await until(lambda: relay.status == "read_to_patient")
    spoken = [e for e in events if e.get("type") == "relay_reply"]
    assert spoken and spoken[0]["text"].startswith("Aisyah replied:")
    assert [e["kind"] for e in relay.events][:3] == ["patient_yes", "approved", "sent"]
    assert "phone" in relay.view() and "+999" not in json.dumps(s.view()["relays"])  # masked


async def test_nothing_is_sent_when_the_patient_says_no(ctx):
    fast_relay(ctx)
    s = make_session(ctx, "daughter", SimulatedPatient(truth="see_person:aisyah", relay=False))
    await s.start()
    await run_until(s)
    assert s.relay.relays == []
    assert s.state == State.DONE


async def test_a_worrying_reply_waits_for_a_caregiver(ctx):
    fast_relay(ctx, require_approval=False, mock_silent=["+999 0000 0001"])
    events = []
    s = make_session(
        ctx, "daughter", SimulatedPatient(truth="see_person:aisyah", relay=True), events=events
    )
    await s.start()
    await run_until(s)
    relay = s.relay.relays[0]
    await until(lambda: relay.status == "delivered")
    await s.relay.on_event(
        "reply", None, relay.contact.phone, "Ayah, dokter bilang operasinya ditunda."
    )
    assert relay.status == "review" and relay.reply["needs_review"]
    assert not [e for e in events if e.get("type") == "relay_reply"]
    assert any(a["kind"] == "relay" for a in s.alerts)
    assert await s.relay.read_to_patient(relay.id)
    assert [e for e in events if e.get("type") == "relay_reply"]


async def test_no_reply_offers_the_next_relative(ctx):
    fast_relay(ctx, require_approval=False, reply_timeout_s=0.2, mock_silent=["+999 0000 0001"])
    s = make_session(ctx, "daughter", SimulatedPatient(truth="see_person:aisyah", relay=False))
    await s.start()
    await run_until(s)
    s.sim, s.auto_speak = None, False  # from here the test answers for the patient
    msg = s.messages[-1]
    contact = s.relay.offer_for(msg)
    await s.relay.start(msg, contact)  # as if the patient had said YES
    relay = s.relay.relays[0]
    await until(lambda: relay.status == "no_reply")
    await until(lambda: s.state == State.ASKING)
    assert s.prompt.kind == "relay_offer" and "Aisyah has not replied" in s.prompt.text
    assert "Rizal" in s.prompt.text
    await s.spoken(s.prompt.id)
    await s.answer(s.prompt.id, Answer.YES)
    assert [r.contact.name for r in s.relay.relays] == ["Aisyah", "Rizal"]


async def test_sensitive_messages_are_never_offered(ctx):
    fast_relay(ctx)
    s = make_session(ctx, "daughter", None)
    await s.start()
    from app.sessions.session import Message

    msg = Message("m1", "see_person:aisyah", "x", "x", "spelled", "confirmed", sensitive=True)
    assert s.relay.offer_for(msg) is None


def test_whatsapp_body_template_outside_the_window_text_inside(ctx):
    ch = WhatsAppChannel(ctx.settings, "token", "106540352242922")
    assert ch.url == "https://graph.facebook.com/v26.0/106540352242922/messages"
    first = ch.body("+6281234567890", "id", "Mr Hasan", "Saya ingin bertemu putri saya, Aisyah.")
    assert first["type"] == "template" and first["template"]["name"] == "patient_message"
    assert first["template"]["language"] == {"code": "id"}
    params = first["template"]["components"][0]["parameters"]
    assert [p["text"] for p in params] == ["Mr Hasan", "Saya ingin bertemu putri saya, Aisyah."]
    ch.note_inbound("+6281234567890")
    later = ch.body("+6281234567890", "en", "Mr Hasan", "Please call me.")
    assert later["type"] == "text" and '"Please call me."' in later["text"]["body"]


def test_webhook_signature_and_parsing():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "16505551234",
                                    "id": "wamid.A",
                                    "timestamp": "1749416383",
                                    "type": "text",
                                    "text": {"body": "On my way"},
                                }
                            ],
                            "statuses": [
                                {"id": "wamid.B", "status": "read", "recipient_id": "16505551234"}
                            ],
                        }
                    }
                ]
            }
        ],
    }
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    assert verify_signature("secret", raw, sig)
    assert not verify_signature("secret", raw + b" ", sig)
    assert not verify_signature("secret", raw, None)
    assert parse_webhook(payload) == [
        ("reply", "wamid.A", "+16505551234", "On my way"),
        ("read", "wamid.B", "+16505551234", None),
    ]
