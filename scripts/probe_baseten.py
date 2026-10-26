"""Probe: Muse Spark Open on Baseten Model APIs (OpenAI-compatible Chat Completions).

Skips (exit 0) while BASETEN_API_KEY is empty. Request shapes follow
https://docs.baseten.co/inference/model-apis/overview, /vision, /audio and /reasoning:
  base_url https://inference.baseten.co/v1, Authorization: Bearer $BASETEN_API_KEY
  media as OpenAI content parts: image_url / video_url / audio_url, each {"url": <https URL or data: URL>}
  reasoning is always on; reasoning_effort low|medium|high|xhigh (default xhigh; none/minimal run as low)
  response_format json_schema is accepted but NOT enforced -> parse defensively
Calls:
  0. GET /v1/models (is the organizer slug listed?)
  1. text, reasoning_effort=low
  2. image (hospital_room.png as data URL)
  3. video (face_yes_eyebrows.mp4 as data URL) and 4. audio (speech_en.wav as data URL), only with --media
Model id: config.yaml models.spark_open (organizer: meta-models/muse-spark-open-1026); on 404 the probe
retries with the documented slug meta-models/muse-spark-open.
Run: backend/.venv/bin/python scripts/probe_baseten.py [--media]
"""

from __future__ import annotations

import json
import sys

from _probe_common import (
    BASETEN_BASE_URL,
    MODELS,
    ProbeRun,
    data_url,
    key_tree,
    media,
    require_env,
    timed_raw,
)

DOC_SLUG = "meta-models/muse-spark-open"


def main() -> None:
    key = require_env("BASETEN_API_KEY")
    from openai import NotFoundError, OpenAI

    client = OpenAI(base_url=BASETEN_BASE_URL, api_key=key, timeout=120, max_retries=0)
    run = ProbeRun("probe_baseten")
    model = MODELS["spark_open"]

    res = run.attempt("GET /models", "-", lambda: client.models.list())
    if res is not None:
        ids = [m.id for m in res.data]
        run.record("GET /models", "-", None, usd=0.0, extra=f"muse ids={[i for i in ids if 'muse' in i]}")
        run.save_fixture("baseten_models_list", res)

    def chat(label: str, content, fixture: str, **kw):
        nonlocal model
        run.guard(0.02, label)
        call = lambda m: timed_raw(  # noqa: E731
            client.chat.completions.with_raw_response.create, model=m, max_tokens=2000,
            extra_headers={"x-session-affinity": "ventriloquist-probe"},
            messages=[{"role": "user", "content": content}], **kw)
        try:
            body, headers, secs = call(model)
        except NotFoundError:
            run.note(f"{model} -> 404; retrying with documented slug {DOC_SLUG}")
            model = DOC_SLUG
            res = run.attempt(label, model, lambda: call(model))
            if res is None:
                return None
            body, headers, secs = res
        msg = body["choices"][0]["message"]
        run.record(label, model, secs, body.get("usage"),
                   extra=f"content={(msg.get('content') or '')[:160]!r} reasoning_chars={len(msg.get('reasoning_content') or '')}")
        print(key_tree(body))
        run.save_fixture(fixture, body)
        run.note(f"Baseten headers: {json.dumps(headers)}")
        return body

    chat("text effort=low", "Reply with exactly one word: ready", "baseten_spark_open_text", reasoning_effort="low")
    chat("image data URL", [
        {"type": "text", "text": "List the furniture in this room in one short sentence. Any people present?"},
        {"type": "image_url", "image_url": {"url": data_url(media("hospital_room.png")), "detail": "auto"}},
    ], "baseten_spark_open_image", reasoning_effort="low")
    if "--media" in sys.argv:
        chat("video data URL", [
            {"type": "text", "text": "How many times do the eyebrows rise in this clip? Answer with a number."},
            {"type": "video_url", "video_url": {"url": data_url(media("face_yes_eyebrows.mp4"), "video/mp4")}},
        ], "baseten_spark_open_video", reasoning_effort="low")
        chat("audio data URL", [
            {"type": "text", "text": "Transcribe this audio. Return only the transcript."},
            {"type": "audio_url", "audio_url": {"url": data_url(media("speech_en.wav"), "audio/wav")}},
        ], "baseten_spark_open_audio", reasoning_effort="low")
    run.finish()


if __name__ == "__main__":
    main()
