"""Probe: Muse Spark text on the Responses API and Chat Completions.

Calls (all tiny, store=false):
  1. basic text, reasoning.effort=minimal
  2. reasoning.effort=none  (docs: HTTP 400 on Spark)  -> error fixture
  3. reasoning.effort=low   (latency / reasoning-token comparison)
  4. structured output on Responses: text.format json_schema (strict)
  5. structured output on Chat Completions: response_format json_schema
  6. reasoning_effort=none on Chat Completions -> expected 400
  7. max_output_tokens=16 -> how an incomplete response looks
  8. POST /v1/responses/input_tokens (token count, no generation)
Run: backend/.venv/bin/python scripts/probe_spark_text.py
"""

from __future__ import annotations

import json

from _probe_common import MODELS, ProbeRun, key_tree, meta_client, output_text, timed_raw

SPARK = MODELS["spark"]

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hypotheses", "question", "language"],
    "properties": {
        "hypotheses": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "p"],
                "properties": {"label": {"type": "string"}, "p": {"type": "number"}},
            },
        },
        "question": {"type": "string", "description": "one yes/no question, at most 10 words"},
        "language": {"type": "string", "enum": ["en", "id"]},
    },
}
SYSTEM = (
    "You help an intubated ICU patient who can only answer yes or no. "
    "Given context, list up to 3 likely needs with probabilities and ask one yes/no question."
)
CONTEXT = (
    "Patient is restless, pointing weakly at the mouth. Last suction 3 hours ago. Language: en."
)


def main() -> None:
    client = meta_client()
    run = ProbeRun("probe_spark_text")
    rr = client.responses.with_raw_response

    # 1. basic, minimal effort
    run.guard(0.01, "basic_minimal")
    res = run.attempt(
        "basic effort=minimal",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            input="Reply with exactly one word: ready",
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=256,
        ),
    )
    if res:
        body, headers, secs = res
        run.record(
            "basic effort=minimal",
            SPARK,
            secs,
            body.get("usage"),
            extra=f"text={output_text(body)!r}",
        )
        print(key_tree(body))
        run.save_fixture("spark_responses_text_minimal", body)
        run.note(f"rate-limit headers on Responses: {json.dumps(headers)}")

    # 2. effort none -> expected 400
    res = run.attempt(
        "effort=none (Responses)",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            input="Reply: ok",
            store=False,
            reasoning={"effort": "none"},
            max_output_tokens=64,
        ),
        fixture="spark_error_reasoning_none",
    )
    if res:
        body, _h, secs = res
        run.record(
            "effort=none (Responses)",
            SPARK,
            secs,
            body.get("usage"),
            status="ok (unexpected)",
            extra=f"text={output_text(body)!r}",
        )

    # 3. effort low
    run.guard(0.01, "basic_low")
    res = run.attempt(
        "basic effort=low",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            input="Reply with exactly one word: ready",
            store=False,
            reasoning={"effort": "low"},
            max_output_tokens=512,
        ),
    )
    if res:
        body, _h, secs = res
        run.record(
            "basic effort=low", SPARK, secs, body.get("usage"), extra=f"text={output_text(body)!r}"
        )

    # 4. structured output, Responses API (text.format)
    run.guard(0.02, "json_schema_responses")
    res = run.attempt(
        "json_schema Responses",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=600,
            instructions=SYSTEM,
            input=CONTEXT,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "question_plan",
                    "schema": PLAN_SCHEMA,
                    "strict": True,
                }
            },
        ),
    )
    if res:
        body, _h, secs = res
        txt = output_text(body)
        try:
            parsed = json.loads(txt)
            extra = f"parsed OK: {json.dumps(parsed)[:160]}"
        except json.JSONDecodeError as e:
            extra = f"JSON parse FAILED: {e}; text={txt[:120]!r}"
        run.record("json_schema Responses", SPARK, secs, body.get("usage"), extra=extra)
        print(key_tree(body))
        run.save_fixture("spark_responses_json_schema", body)

    # 5. structured output, Chat Completions (response_format)
    run.guard(0.02, "json_schema_chat")
    res = run.attempt(
        "json_schema Chat",
        SPARK,
        lambda: timed_raw(
            client.chat.completions.with_raw_response.create,
            model=SPARK,
            reasoning_effort="minimal",
            max_tokens=600,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": CONTEXT}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "question_plan", "schema": PLAN_SCHEMA, "strict": True},
            },
        ),
    )
    if res:
        body, headers, secs = res
        txt = body["choices"][0]["message"].get("content") or ""
        try:
            parsed = json.loads(txt)
            extra = f"parsed OK: {json.dumps(parsed)[:160]}"
        except json.JSONDecodeError as e:
            extra = f"JSON parse FAILED: {e}"
        run.record("json_schema Chat", SPARK, secs, body.get("usage"), extra=extra)
        print(key_tree(body))
        run.save_fixture("spark_chat_json_schema", body)
        run.note(f"rate-limit headers on Chat Completions: {json.dumps(headers)}")

    # 6. reasoning_effort none on Chat Completions -> expected 400
    res = run.attempt(
        "effort=none (Chat)",
        SPARK,
        lambda: timed_raw(
            client.chat.completions.with_raw_response.create,
            model=SPARK,
            reasoning_effort="none",
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply: ok"}],
        ),
        fixture="spark_chat_error_reasoning_none",
    )
    if res:
        body, _h, secs = res
        run.record("effort=none (Chat)", SPARK, secs, body.get("usage"), status="ok (unexpected)")

    # 7. tiny output budget -> incomplete
    run.guard(0.01, "max_output_16")
    res = run.attempt(
        "max_output_tokens=16",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            input="Count from one to fifty in words.",
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=16,
        ),
    )
    if res:
        body, _h, secs = res
        run.record(
            "max_output_tokens=16",
            SPARK,
            secs,
            body.get("usage"),
            extra=f"status={body.get('status')} incomplete_details={body.get('incomplete_details')}",
        )
        run.save_fixture("spark_responses_incomplete", body)

    # 8. token count (no generation)
    res = run.attempt(
        "input_tokens count",
        SPARK,
        lambda: timed_raw(
            client.responses.input_tokens.with_raw_response.count,
            model=SPARK,
            instructions=SYSTEM,
            input=CONTEXT,
        ),
    )
    if res:
        body, _h, secs = res
        run.record("POST /responses/input_tokens", SPARK, secs, usd=0.0, extra=json.dumps(body))
        run.save_fixture("spark_input_tokens_count", body)

    run.finish()


if __name__ == "__main__":
    main()
