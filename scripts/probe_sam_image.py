"""Probe: SAM 3.1 image segmentation over the Responses API (concept prompts).

Calls ($0.0025 each):
  1. hospital_room.png, "photo frame", stream=true, include_confidence, default lossless masks
  2. hospital_room.png, "bed", stream=false (non-streaming shape), one_bit masks
  3. face_still.png, "eyebrows", stream=true, one_bit, include_confidence
Mask decoding uses the official `meta-sam-parser` package when importable (pip install meta-sam-parser).
Run: backend/.venv/bin/python scripts/probe_sam_image.py
"""

from __future__ import annotations

import json

from _probe_common import (
    MODELS,
    ProbeRun,
    data_url,
    decode_sam_masks,
    key_tree,
    manifest,
    media,
    meta_client,
    output_text,
    parse_sam_text,
    stream_response,
    timed_raw,
)

SAM = MODELS["sam"]


def sam_input(prompt: str, image) -> list[dict]:
    return [
        {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url(image)},
            ],
        }
    ]


def summarize(run: ProbeRun, text: str) -> str:
    recs = parse_sam_text(text)
    dec = decode_sam_masks(text)
    brief = [
        {k: r[k] for k in ("object_id", "box", "c", "mask_h", "mask_w", "mask_enc")} for r in recs
    ]
    s = f"{len(recs)} match(es): {json.dumps(brief)[:300]}"
    if dec is not None:
        s += f" decoded={dec['decoded']} fg_px={dec['foreground_px'][:4]} errors={dec['errors']}"
    else:
        run.note("meta_sam_parser not importable: masks not decoded (pip install meta-sam-parser)")
    return s


def main() -> None:
    client = meta_client()
    run = ProbeRun("probe_sam_image")
    room, face = media("hospital_room.png"), media("face_still.png")
    run.note(
        f"room ground truth (approx px): {json.dumps(manifest()['image']['hospital_room.png']['objects'])}"
    )

    run.guard(0.003, "sam photo frame")
    res = run.attempt(
        "photo frame stream lossless+c",
        SAM,
        lambda: stream_response(
            client,
            model=SAM,
            input=sam_input("photo frame", room),
            store=False,
            metadata={"include_confidence": "true"},
        ),
    )
    if res:
        usage = res["final"].get("usage") or {}
        run.record(
            "photo frame stream lossless+c",
            SAM,
            res["total_s"],
            usage,
            first_event_s=res["first_delta_s"],
            extra=summarize(run, res["text"]),
        )
        run.note(f"SSE event types (image, stream): {json.dumps(res['event_types'])}")
        print("first line:", res["text"][:240])
        print(key_tree(res["final"]))
        run.save_fixture("sam_image_stream_lossless", {"events": res["events"]})

    run.guard(0.003, "sam bed")
    res = run.attempt(
        "bed non-stream one_bit",
        SAM,
        lambda: timed_raw(
            client.responses.with_raw_response.create,
            model=SAM,
            input=sam_input("bed", room),
            store=False,
            metadata={"mask_encoding": "one_bit"},
        ),
    )
    if res:
        body, headers, secs = res
        text = output_text(body)
        run.record(
            "bed non-stream one_bit",
            SAM,
            secs,
            body.get("usage"),
            extra=summarize(run, text),
        )
        print(key_tree(body))
        run.save_fixture("sam_image_nonstream_one_bit", body)
        run.note(f"SAM response headers: {json.dumps(headers)}")

    run.guard(0.003, "sam eyebrows")
    res = run.attempt(
        "eyebrows stream one_bit+c",
        SAM,
        lambda: stream_response(
            client,
            model=SAM,
            input=sam_input("eyebrows", face),
            store=False,
            metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
        ),
    )
    if res:
        usage = res["final"].get("usage") or {}
        run.record(
            "eyebrows stream one_bit+c",
            SAM,
            res["total_s"],
            usage,
            first_event_s=res["first_delta_s"],
            extra=summarize(run, res["text"]),
        )
        run.save_fixture("sam_image_stream_one_bit_eyebrows", {"events": res["events"]})
    run.finish()


if __name__ == "__main__":
    main()
