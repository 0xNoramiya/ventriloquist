"""Probe: Muse Spark image understanding (Responses API, inline base64 data URL).

Calls:
  1. input_tokens count for one 640x480 PNG (image token cost, no generation)
  2. hospital_room.png -> json_schema grounding (labels + 0-1000 boxes, photo frame, people present?)
  3. face_still.png    -> json_schema eyebrow judgement (the perception-judge use case)
Run: backend/.venv/bin/python scripts/probe_spark_image.py
"""

from __future__ import annotations

import json

from _probe_common import (
    MODELS,
    ProbeRun,
    data_url,
    key_tree,
    manifest,
    media,
    meta_client,
    output_text,
    timed_raw,
)

SPARK = MODELS["spark"]

ROOM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objects", "photo_frame_present", "people_present"],
    "properties": {
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "x_min", "y_min", "x_max", "y_max"],
                "properties": {
                    "label": {"type": "string"},
                    "x_min": {"type": "integer"},
                    "y_min": {"type": "integer"},
                    "x_max": {"type": "integer"},
                    "y_max": {"type": "integer"},
                },
            },
        },
        "photo_frame_present": {"type": "boolean"},
        "people_present": {"type": "boolean"},
    },
}

FACE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["eyebrows_raised", "eyes_open", "confidence"],
    "properties": {
        "eyebrows_raised": {"type": "boolean"},
        "eyes_open": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
}


def to_px(box: dict, w: int, h: int) -> list[int]:
    return [
        round(box["x_min"] * w / 1000),
        round(box["y_min"] * h / 1000),
        round(box["x_max"] * w / 1000),
        round(box["y_max"] * h / 1000),
    ]


def main() -> None:
    client = meta_client()
    run = ProbeRun("probe_spark_image")
    rr = client.responses.with_raw_response
    room = media("hospital_room.png")
    face = media("face_still.png")
    truth = manifest()["image"]["hospital_room.png"]["objects"]

    def msg(text: str, image_path) -> list[dict]:
        return [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": data_url(image_path)},
                ],
            }
        ]

    res = run.attempt(
        "input_tokens 640x480 png",
        SPARK,
        lambda: timed_raw(
            client.responses.input_tokens.with_raw_response.count,
            model=SPARK,
            input=msg("Describe.", room),
        ),
    )
    if res:
        body, _h, secs = res
        run.record("input_tokens 640x480 png", SPARK, secs, usd=0.0, extra=json.dumps(body))

    prompt = (
        'You are an object grounding expert. Provide bounding boxes for: "bed", "bedside table", '
        '"photo frame". Coordinates are integers on a 0-1000 grid (x right, y down). '
        "Also say whether a photo frame and whether any people are present."
    )
    run.guard(0.02, "room grounding")
    res = run.attempt(
        "room grounding json_schema",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=800,
            input=msg(prompt, room),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "room_objects",
                    "schema": ROOM_SCHEMA,
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
            boxes = {o["label"]: to_px(o, 640, 480) for o in parsed["objects"]}
            extra = (
                f"photo_frame={parsed['photo_frame_present']} people={parsed['people_present']} "
                f"boxes_px={json.dumps(boxes)}"
            )
        except (json.JSONDecodeError, KeyError) as e:
            extra = f"parse failed: {e}; text={txt[:150]!r}"
        run.record("room grounding json_schema", SPARK, secs, body.get("usage"), extra=extra)
        print(key_tree(body))
        run.save_fixture("spark_responses_image_grounding", body)
        run.note(f"room ground truth px boxes (approx): {json.dumps(truth)}")

    run.guard(0.02, "face judge")
    res = run.attempt(
        "face eyebrows json_schema",
        SPARK,
        lambda: timed_raw(
            rr.create,
            model=SPARK,
            store=False,
            reasoning={"effort": "minimal"},
            max_output_tokens=400,
            input=msg(
                "Cartoon patient face. Are the eyebrows raised above their resting position? Are the eyes open?",
                face,
            ),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "face_state",
                    "schema": FACE_SCHEMA,
                    "strict": True,
                }
            },
        ),
    )
    if res:
        body, _h, secs = res
        run.record(
            "face eyebrows json_schema",
            SPARK,
            secs,
            body.get("usage"),
            extra=f"out={output_text(body)}",
        )
        run.save_fixture("spark_responses_image_face", body)

    run.finish()


if __name__ == "__main__":
    main()
