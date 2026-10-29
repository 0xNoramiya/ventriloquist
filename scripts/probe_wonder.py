"""Probe: Muse Wonder on the Responses API + what "memory" actually means on the API.

Calls (reasoning.effort=minimal, small max_output_tokens):
  1. json_schema extraction of family/context facts from a bedside transcript (store=false)
  2. store=true call that states a fact, then a second call chained with previous_response_id
     that asks for it back (server-side conversation state, the only cross-call state documented)
  3. same question with store=false and no previous_response_id (expect: no recall)
  4. DELETE /v1/responses/{id} for the stored response
Run: backend/.venv/bin/python scripts/probe_wonder.py
"""

from __future__ import annotations

import json
import time

from _probe_common import MODELS, ProbeRun, key_tree, meta_client, output_text, timed_raw

WONDER = MODELS["wonder"]

MEMORY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "fact"],
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["family", "schedule", "clinical", "preference", "other"],
                    },
                    "fact": {"type": "string"},
                },
            },
        }
    },
}
TRANSCRIPT = (
    "[nurse] Good morning. Did you sleep at all last night? "
    "[family] She slept a little after midnight. The nurse gave her something for pain. "
    "[nurse] Okay. Let us check the breathing tube in an hour. "
    "[family] Your daughter Aisyah went home to rest, she will be back at four."
)


def main() -> None:
    client = meta_client(timeout=180)
    run = ProbeRun("probe_wonder")
    rr = client.responses.with_raw_response

    run.guard(0.03, "wonder extract")
    res = run.attempt(
        "extract facts json_schema",
        WONDER,
        lambda: timed_raw(
            rr.create,
            model=WONDER,
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=700,
            instructions="Extract facts useful for talking with the patient later. Short facts only.",
            input=TRANSCRIPT,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "memory_facts",
                    "schema": MEMORY_SCHEMA,
                    "strict": True,
                }
            },
        ),
    )
    if res:
        body, headers, secs = res
        run.record(
            "extract facts json_schema",
            WONDER,
            secs,
            body.get("usage"),
            extra=f"out={output_text(body)[:260]}",
        )
        print(key_tree(body))
        run.save_fixture("wonder_responses_json_schema", body)
        run.note(f"Wonder rate-limit headers: {json.dumps(headers)}")

    run.guard(0.02, "wonder store")
    res = run.attempt(
        "store=true turn 1",
        WONDER,
        lambda: timed_raw(
            rr.create,
            model=WONDER,
            store=True,
            reasoning={"effort": "minimal"},
            max_output_tokens=200,
            input="Remember this code word for later: PELANGI. Reply only: noted.",
        ),
    )
    stored_id = None
    if res:
        body, _h, secs = res
        stored_id = body.get("id")
        run.record(
            "store=true turn 1",
            WONDER,
            secs,
            body.get("usage"),
            extra=f"id={stored_id} out={output_text(body)!r}",
        )
        time.sleep(1.0)  # docs: persistence can briefly lag response.completed
        run.guard(0.02, "wonder chained")
        res2 = run.attempt(
            "previous_response_id turn 2",
            WONDER,
            lambda: timed_raw(
                rr.create,
                model=WONDER,
                store=False,
                reasoning={"effort": "minimal"},
                max_output_tokens=200,
                previous_response_id=stored_id,
                input="What was the code word? Reply with the word only.",
            ),
        )
        if res2:
            body2, _h, secs2 = res2
            run.record(
                "previous_response_id turn 2",
                WONDER,
                secs2,
                body2.get("usage"),
                extra=f"out={output_text(body2)!r}",
            )
            run.save_fixture("wonder_responses_previous_response_id", body2)

    run.guard(0.02, "wonder no memory")
    res = run.attempt(
        "fresh call, no chaining",
        WONDER,
        lambda: timed_raw(
            rr.create,
            model=WONDER,
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=200,
            input="What code word did I give you earlier? If you do not know, reply exactly: unknown.",
        ),
    )
    if res:
        body, _h, secs = res
        run.record(
            "fresh call, no chaining",
            WONDER,
            secs,
            body.get("usage"),
            extra=f"out={output_text(body)!r}",
        )

    if stored_id:
        t0 = time.perf_counter()
        d = run.attempt(
            "DELETE /responses/{id}",
            WONDER,
            lambda: client.responses.with_raw_response.delete(stored_id),
        )
        if d is not None:
            run.record(
                "DELETE /responses/{id}",
                WONDER,
                time.perf_counter() - t0,
                usd=0.0,
                extra=f"HTTP {d.http_response.status_code} body={d.http_response.text[:120]}",
            )
    run.finish()


if __name__ == "__main__":
    main()
