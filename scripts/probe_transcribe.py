"""Probe: Muse Voice Transcribe — file endpoint (POST /v1/asr/transcribe) and realtime WebSocket.

File endpoint (multipart: `request` JSON part + `audio` WAV part; mono s16 PCM at 16/24 kHz):
  1. English, PUSH_TO_TALK, no hints                      -> WER vs reference
  2. English, keywords=["Aisyah"]                         -> WER (keyword biasing)
  3. Indonesian, no languageBias                          -> WER
  4. Indonesian, languageBias=["Indonesian"], keywords    -> WER
     + Indonesian with languageBias only, with ["Indonesian","English"], and ENDPOINTING without a hint
     (--indonesian-only runs just the Indonesian cases)
  5. two voices, DIARIZATION                              -> turns + speaker labels
  6. two voices, ENDPOINTING, Accept: text/event-stream   -> SSE event shapes
  7. English, DIARIZATION, Accept: text/plain
  8. 48 kHz WAV (phone-mic rate)                          -> expected 400
Realtime (wss://api.meta.ai/v1/asr/realtime, key in the handshake frame):
  9. Indonesian clip streamed as PCM_24KHZ, 80 ms frames paced at real time, ENDPOINTING
Audio costs $0.18/hour; everything here is < 2 minutes of audio.
Run: backend/.venv/bin/python scripts/probe_transcribe.py
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
import wave

import httpx
from _probe_common import (
    MEDIA,
    META_BASE_URL,
    MODELS,
    ProbeRun,
    estimate_cost,
    key_tree,
    manifest,
    media,
    require_env,
)

ASR = MODELS["transcribe"]
DIGITS = {"en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"],
          "id": ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan"]}


def words(text: str, lang: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"\b(\d)\b", lambda m: DIGITS[lang][int(m.group(1))], text)
    return re.findall(r"[a-z0-9']+", text)


def wer(ref: str, hyp: str, lang: str) -> float:
    r, h = words(ref, lang), words(hyp, lang)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))


def main() -> None:
    key = require_env("MODEL_API_KEY")
    run = ProbeRun("probe_transcribe")
    audio = manifest()["audio"]
    en, idn, two = media("speech_en.wav"), media("speech_id.wav"), media("two_voices.wav")
    http = httpx.Client(base_url=META_BASE_URL, headers={"Authorization": f"Bearer {key}"}, timeout=120)

    def transcribe(label: str, path, settings: dict, accept: str = "application/json", fixture: str = ""):
        req = {"model": ASR, "audioEncoding": "WAV", **settings}
        run.guard(0.01, label)
        t0 = time.perf_counter()
        r = http.post("/asr/transcribe", params={"sessionId": f"probe-{int(time.time())}"},
                      headers={"Accept": accept},
                      files={"request": (None, json.dumps(req), "application/json"),
                             "audio": (path.name, path.read_bytes(), "audio/wav")})
        secs = time.perf_counter() - t0
        if r.status_code != 200:
            run.record(label, ASR, secs, status=f"HTTP {r.status_code}", extra=r.text[:300])
            if fixture:
                try:
                    run.save_fixture(fixture, {"http_status": r.status_code, "body": r.json()})
                except ValueError:
                    run.save_fixture(fixture, {"http_status": r.status_code, "raw_text": r.text[:2000]})
            return None, secs
        return r, secs

    # 1-4: WER runs
    cases = [
        ("EN plain", en, {"mode": "PUSH_TO_TALK"}, "en", "asr_transcribe_en_push_to_talk"),
        ("EN keywords", en, {"mode": "PUSH_TO_TALK", "keywords": ["Aisyah"]}, "en", ""),
        ("ID plain", idn, {"mode": "PUSH_TO_TALK"}, "id", ""),
        ("ID languageBias+keywords", idn,
         {"mode": "PUSH_TO_TALK", "languageBias": ["Indonesian"], "keywords": ["Aisyah"]}, "id",
         "asr_transcribe_id_language_bias"),
        ("ID languageBias only", idn, {"mode": "PUSH_TO_TALK", "languageBias": ["Indonesian"]}, "id", ""),
        ("ID languageBias [Indonesian, English]", idn,
         {"mode": "PUSH_TO_TALK", "languageBias": ["Indonesian", "English"]}, "id", ""),
        ("ID plain ENDPOINTING", idn, {"mode": "ENDPOINTING"}, "id", "asr_transcribe_id_no_bias_endpointing"),
    ]
    id_only = "--indonesian-only" in sys.argv
    if id_only:
        cases = [c for c in cases if c[0].startswith("ID")]
    for label, path, settings, lang, fixture in cases:
        r, secs = transcribe(label, path, settings, fixture=fixture)
        if r is None:
            continue
        body = r.json()
        ref = audio[path.name]["reference"]
        w = wer(ref, body.get("transcript", ""), lang)
        ms = int(body.get("audioDurationMs", 0))
        run.record(label, ASR, secs, {"audio_ms": ms}, usd=estimate_cost(ASR, audio_ms=ms),
                   extra=f"WER={w:.2f} hyp={body.get('transcript')!r}")
        if fixture:
            print(key_tree(body))
            run.save_fixture(fixture, body)
    if id_only:
        http.close()
        run.finish()
        return

    # 5. diarization
    r, secs = transcribe("two voices DIARIZATION", two, {"mode": "DIARIZATION"})
    if r is not None:
        body = r.json()
        ms = int(body.get("audioDurationMs", 0))
        turns = [(t.get("speaker"), t.get("startMs"), t.get("endMs"), t.get("transcript")) for t in body.get("turns", [])]
        w = wer(audio["two_voices.wav"]["reference"], body.get("transcript", ""), "en")
        run.record("two voices DIARIZATION", ASR, secs, {"audio_ms": ms}, usd=estimate_cost(ASR, audio_ms=ms),
                   extra=f"WER={w:.2f} turns={json.dumps(turns)}")
        run.note("truth turns: A / B / A (" + " | ".join(t["text"] for t in audio["two_voices.wav"]["turns"]) + ")")
        print(key_tree(body))
        run.save_fixture("asr_transcribe_diarization", body)

    # 6. SSE
    r, secs = transcribe("two voices ENDPOINTING SSE", two, {"mode": "ENDPOINTING", "emitAudioProgress": False},
                         accept="text/event-stream")
    if r is not None:
        events = []
        for block in r.text.split("\n\n"):
            ev = {}
            for line in block.splitlines():
                if line.startswith("event:"):
                    ev["event"] = line[6:].strip()
                elif line.startswith("data:"):
                    ev["data"] = json.loads(line[5:].strip())
            if ev:
                events.append(ev)
        kinds: dict[str, int] = {}
        for e in events:
            kinds[e.get("event", "?")] = kinds.get(e.get("event", "?"), 0) + 1
        dur = int(audio["two_voices.wav"]["duration_s"] * 1000)
        run.record("two voices ENDPOINTING SSE", ASR, secs, {"audio_ms": dur}, usd=estimate_cost(ASR, audio_ms=dur),
                   extra=f"content-type={r.headers.get('content-type')} events={json.dumps(kinds)}")
        run.save_fixture("asr_transcribe_endpointing_sse", {"content_type": r.headers.get("content-type"),
                                                            "events": events})

    # 7. text/plain
    r, secs = transcribe("EN DIARIZATION text/plain", en, {"mode": "DIARIZATION"}, accept="text/plain")
    if r is not None:
        dur = int(audio["speech_en.wav"]["duration_s"] * 1000)
        run.record("EN DIARIZATION text/plain", ASR, secs, {"audio_ms": dur}, usd=estimate_cost(ASR, audio_ms=dur),
                   extra=f"body={r.text.strip()[:160]!r}")

    # 8. 48 kHz wav -> expected 400
    wav48 = MEDIA / "speech_en_48k.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(en), "-ar", "48000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav48)], check=True)
    r, secs = transcribe("EN 48 kHz WAV", wav48, {"mode": "PUSH_TO_TALK"}, fixture="asr_error_48khz")
    if r is not None:
        body = r.json()
        run.record("EN 48 kHz WAV", ASR, secs, {"audio_ms": body.get("audioDurationMs", 0)},
                   usd=estimate_cost(ASR, audio_ms=int(body.get("audioDurationMs", 0))),
                   status="ok (48 kHz accepted)", extra=f"hyp={body.get('transcript')!r}")
    http.close()

    # 9. realtime websocket
    try:
        asyncio.run(realtime(run, key, idn, audio[idn.name]["reference"]))
    except Exception as e:  # keep the other results even if the socket fails
        run.record("realtime WS", ASR, None, status="error", extra=f"{type(e).__name__}: {e}"[:300])
    run.finish()


async def realtime(run: ProbeRun, key: str, path, reference: str) -> None:
    import websockets

    uri = META_BASE_URL.replace("https://", "wss://") + f"/asr/realtime?sessionId=probe-rt-{int(time.time())}"
    with wave.open(str(path)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        pcm = w.readframes(w.getnframes())
    frame_bytes = 24000 * 2 * 80 // 1000  # 80 ms
    events: list[dict] = []
    t0 = time.perf_counter()
    audio_done: float | None = None
    async with websockets.connect(uri, open_timeout=30) as ws:
        await ws.send(json.dumps({
            "authorization": {"accessToken": f"Bearer {key}"},
            "audioEncoding": "PCM_24KHZ", "model": ASR, "mode": "ENDPOINTING",
            "partialMode": "CUMULATIVE", "emitAudioProgress": False,
            "languageBias": ["Indonesian"], "keywords": ["Aisyah"],
        }))
        ack = json.loads(await ws.recv())
        events.append({"t": round(time.perf_counter() - t0, 3), "ack": ack})
        if "sessionId" not in ack:
            raise RuntimeError(f"handshake failed: {ack}")

        async def receiver() -> None:
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                events.append({"t": round(time.perf_counter() - t0, 3), **json.loads(msg)})

        rx = asyncio.create_task(receiver())
        start = time.perf_counter()
        for i in range(0, len(pcm), frame_bytes):
            await ws.send(pcm[i:i + frame_bytes])
            target = start + (i // frame_bytes + 1) * 0.08
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
        # trailing 1 s of silence so the endpointer can close the turn
        for _ in range(12):
            await ws.send(b"\x00" * frame_bytes)
            await asyncio.sleep(0.08)
        audio_done = time.perf_counter() - t0
        await ws.send(json.dumps({"type": "endStream"}))
        await rx
        close_code = ws.close_code
    total = time.perf_counter() - t0
    finals = [e for e in events if e.get("type") == "speechComplete"]
    first_partial = next((e["t"] for e in events if e.get("type") == "transcript"), None)
    hyp = " ".join(e.get("transcript", "") for e in finals)
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e.get("type", "ack")] = kinds.get(e.get("type", "ack"), 0) + 1
    ms = int(len(pcm) / 48)
    run.record("realtime WS ID ENDPOINTING", ASR, total, {"audio_ms": ms + 960},
               usd=estimate_cost(ASR, audio_ms=ms + 960),
               extra=(f"close={close_code} first_partial_at={first_partial}s audio_sent_by={audio_done:.2f}s "
                      f"final_at={finals[-1]['t'] if finals else None}s WER={wer(reference, hyp, 'id'):.2f} "
                      f"events={json.dumps(kinds)} hyp={hyp!r}"))
    run.save_fixture("asr_realtime_endpointing_events", {"events": events})


if __name__ == "__main__":
    main()
