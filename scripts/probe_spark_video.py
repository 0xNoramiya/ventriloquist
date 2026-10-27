"""Probe: Muse Spark video understanding — how video is accepted and what it costs.

Calls:
  1-3. POST /v1/responses/input_tokens for the 4 s clip as an inline data URL (input_video.video_url),
       default fps, fps=2 and fps=15 (input_video.fps is in the schema; checks whether it changes tokens)
  4.   YES clip inline (data URL) -> json_schema movement classification; then input_video.fps=4 and 8
       (--fps-sweep-only runs just the token counts and the fps sweep)
  5.   upload NOD clip with POST /v1/files (purpose=user_data, expires_after 3600 s)
       -> input_video {file_id} classification
  6.   upload REST clip -> input_file {file_id} classification
  7.   DELETE /v1/files/{id} for both uploads
Run: backend/.venv/bin/python scripts/probe_spark_video.py
"""

from __future__ import annotations

import json
import sys
import time

from _probe_common import (
    MODELS,
    ProbeRun,
    data_url,
    estimate_cost,
    key_tree,
    manifest,
    media,
    meta_client,
    output_text,
    timed_raw,
)

SPARK = MODELS["spark"]

MOVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["eyebrow_raises", "head_nods", "blinks", "signal", "confidence"],
    "properties": {
        "eyebrow_raises": {"type": "integer"},
        "head_nods": {"type": "integer"},
        "blinks": {"type": "integer"},
        "signal": {"type": "string", "enum": ["EYEBROW_RAISE", "HEAD_NOD", "NONE", "UNCLEAR"]},
        "confidence": {"type": "number"},
    },
}
PROMPT = (
    "Cartoon patient face, 4 second clip. Count deliberate eyebrow raises, head nods, and blinks. "
    "signal = the deliberate movement shown (blinks alone are NONE)."
)


def main() -> None:
    client = meta_client(timeout=180)
    run = ProbeRun("probe_spark_video")
    rr = client.responses.with_raw_response
    m = manifest()["video"]
    yes, nod, rest = (
        media("face_yes_eyebrows.mp4"),
        media("face_nod.mp4"),
        media("face_rest_blinks.mp4"),
    )
    run.note(
        f"clip sizes: yes={yes.stat().st_size} B, nod={nod.stat().st_size} B, rest={rest.stat().st_size} B; "
        "640x480, 15 fps, 60 frames, H.264, no audio track"
    )

    def video_msg(part: dict) -> list[dict]:
        return [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": PROMPT}, part],
            }
        ]

    yes_url = data_url(yes, "video/mp4")
    counts: dict[str, int] = {}
    for label, part in (
        ("default fps", {"type": "input_video", "video_url": yes_url}),
        ("fps=2", {"type": "input_video", "video_url": yes_url, "fps": 2}),
        ("fps=15", {"type": "input_video", "video_url": yes_url, "fps": 15}),
    ):
        res = run.attempt(
            f"input_tokens video {label}",
            SPARK,
            lambda part=part: timed_raw(
                client.responses.input_tokens.with_raw_response.count,
                model=SPARK,
                input=video_msg(part),
            ),
        )
        if res:
            body, _h, secs = res
            counts[label] = body.get("input_tokens", 0)
            run.record(f"input_tokens video {label}", SPARK, secs, usd=0.0, extra=json.dumps(body))
    worst = max(counts.values() or [20000])
    est = estimate_cost(SPARK, {"input_tokens": worst, "output_tokens": 800})
    run.note(
        f"token counts for the 4 s clip: {json.dumps(counts)}; per-call upper estimate ${est:.4f}"
    )

    def classify(label: str, part: dict, fixture: str, truth_kind: str) -> None:
        run.guard(est, label)
        res = run.attempt(
            label,
            SPARK,
            lambda: timed_raw(
                rr.create,
                model=SPARK,
                store=False,
                reasoning={"effort": "minimal"},
                max_output_tokens=800,
                input=video_msg(part),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "movement",
                        "schema": MOVE_SCHEMA,
                        "strict": True,
                    }
                },
            ),
        )
        if res:
            body, _h, secs = res
            run.record(
                label,
                SPARK,
                secs,
                body.get("usage"),
                extra=f"truth={truth_kind} out={output_text(body)}",
            )
            if fixture:
                run.save_fixture(fixture, body)
            return body
        return None

    # 4. inline data URL (default sampling), then an fps sweep on the same clip
    sweep_only = "--fps-sweep-only" in sys.argv
    if not sweep_only:
        body = classify(
            "YES clip inline data URL",
            {"type": "input_video", "video_url": yes_url},
            "spark_responses_video_inline",
            "2 eyebrow raises, 1 blink",
        )
        if body:
            print(key_tree(body))
    for fps in (4, 8):
        classify(
            f"YES clip inline fps={fps}",
            {"type": "input_video", "video_url": yes_url, "fps": fps},
            f"spark_responses_video_inline_fps{fps}" if fps == 4 else "",
            "2 eyebrow raises, 1 blink",
        )
    if sweep_only:
        run.finish()
        return

    # 5/6. Files API upload, then reference by id
    uploaded = []
    for path, part_type, label, fixture, truth_kind in (
        (
            nod,
            "input_video",
            "NOD clip input_video file_id",
            "spark_responses_video_file_id",
            "2 head nods",
        ),
        (rest, "input_file", "REST clip input_file file_id", "", "3 blinks only"),
    ):
        t0 = time.perf_counter()
        f = run.attempt(
            f"upload {path.name}",
            "-",
            lambda path=path: client.files.create(
                file=(path.name, path.read_bytes(), "video/mp4"),
                purpose="user_data",
                expires_after={"anchor": "created_at", "seconds": 3600},
            ),
        )
        if f is None:
            continue
        run.record(
            f"POST /files {path.name}",
            "-",
            time.perf_counter() - t0,
            usd=0.0,
            extra=f"id={f.id} status={getattr(f, 'status', None)} expires_at={getattr(f, 'expires_at', None)}",
        )
        if not uploaded:
            run.save_fixture("files_upload_video", f)
        uploaded.append(f.id)
        part = {"type": part_type, "file_id": f.id}
        classify(label, part, fixture, truth_kind)

    for fid in uploaded:
        t0 = time.perf_counter()
        d = run.attempt(f"delete {fid}", "-", lambda fid=fid: client.files.delete(fid))
        if d is not None:
            run.record(
                f"DELETE /files/{fid}",
                "-",
                time.perf_counter() - t0,
                usd=0.0,
                extra=f"deleted={d.deleted}",
            )
    run.note(
        f"ground truth: {json.dumps({k: [e['type'] for e in v['events']] for k, v in m.items()})}"
    )
    run.finish()


if __name__ == "__main__":
    main()
