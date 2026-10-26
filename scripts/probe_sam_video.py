"""Probe: SAM 3.1 video segmentation + tracking (concept prompts) on the 4 s, 15 fps synthetic clips.

Calls (60 frames each -> 60 x $0.0002 = $0.012; the minimum bill is 50 frames):
  1. YES clip, "eyebrows", inline data URL (input_video.video_url), stream=true, one_bit, include_confidence
  2. NOD clip uploaded via POST /v1/files, "face", input_video.file_id, stream=true, one_bit
  3. REST clip, "eyebrows", inline, stream=false (non-streaming shape), default lossless masks
Per frame it prints the box top (y1) / centre so the YES/NOD motion can be checked against
data/probe_media/media_manifest.json. Output carries frame indices only, no timestamps:
t = frame_index / source fps.
Run: backend/.venv/bin/python scripts/probe_sam_video.py
"""

from __future__ import annotations

import json
import time

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
FPS = 15


def series(recs: list[dict]) -> dict:
    """Per object id: frames seen, y1 series, centre-y series, confidences."""
    by: dict[int, dict] = {}
    for r in sorted(recs, key=lambda r: (r["object_id"], r["frame"])):
        o = by.setdefault(r["object_id"], {"frames": [], "y1": [], "cy": [], "c": []})
        o["frames"].append(r["frame"])
        o["y1"].append(r["box"][1])
        o["cy"].append((r["box"][1] + r["box"][3]) // 2)
        if r["c"] is not None:
            o["c"].append(round(r["c"], 3))
    return by


def describe(run: ProbeRun, label: str, text: str, signal_key: str) -> str:
    recs = parse_sam_text(text)
    frames = sorted({r["frame"] for r in recs})
    s = series(recs)
    dec = decode_sam_masks(text)
    parts = [f"{len(frames)} frame lines, {len(recs)} records, object ids={sorted(s)}"]
    if frames:
        parts.append(f"frames {frames[0]}..{frames[-1]} ascending={frames == sorted(frames)}")
    for oid, o in s.items():
        vals = o[signal_key]
        base = sorted(vals)[len(vals) // 2] if vals else 0
        dev = [v - base for v in vals]
        peaks = [o["frames"][i] for i, d in enumerate(dev) if abs(d) == max(abs(x) for x in dev)] if dev else []
        run.note(f"{label} obj {oid} {signal_key} (px, median {base}): {vals}")
        parts.append(f"obj{oid}: {signal_key} range {min(vals)}..{max(vals)} peak frames {peaks[:4]}"
                     + (f" c {min(o['c'])}..{max(o['c'])}" if o["c"] else ""))
    if dec is not None:
        parts.append(f"decoded {dec['decoded']} masks, errors {dec['errors']}")
    return "; ".join(parts)


def main() -> None:
    client = meta_client(timeout=300)
    run = ProbeRun("probe_sam_video")
    m = manifest()["video"]
    yes, nod, rest = media("face_yes_eyebrows.mp4"), media("face_nod.mp4"), media("face_rest_blinks.mp4")
    for name in (yes.name, nod.name):
        ev = [(e["type"], round(e["peak_s"] * FPS)) for e in m[name]["events"]]
        run.note(f"truth {name}: (event, peak frame) {ev}")

    def vid_input(prompt: str, part: dict) -> list[dict]:
        return [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}, part]}]

    # 1. inline data URL, streaming
    run.guard(0.02, "sam video yes")
    res = run.attempt("YES eyebrows inline stream", SAM, lambda: stream_response(
        client, model=SAM, store=False, metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
        input=vid_input("eyebrows", {"type": "input_video", "video_url": data_url(yes, "video/mp4")})))
    if res:
        usage = res["final"].get("usage") or {}
        run.record("YES eyebrows inline stream", SAM, res["total_s"], usage, first_event_s=res["first_delta_s"],
                   extra=describe(run, "YES eyebrows", res["text"], "y1"))
        run.note(f"SSE event types (video, stream): {json.dumps(res['event_types'])}")
        print(key_tree(res["final"]))
        run.save_fixture("sam_video_stream_one_bit_eyebrows", {"events": res["events"]})

    # 2. upload + file_id, streaming
    t0 = time.perf_counter()
    f = run.attempt("upload nod clip", "-", lambda: client.files.create(
        file=(nod.name, nod.read_bytes(), "video/mp4"), purpose="user_data",
        expires_after={"anchor": "created_at", "seconds": 3600}))
    if f is not None:
        run.record(f"POST /files {nod.name}", "-", time.perf_counter() - t0, usd=0.0, extra=f"id={f.id}")
        run.guard(0.02, "sam video nod")
        res = run.attempt("NOD face file_id stream", SAM, lambda: stream_response(
            client, model=SAM, store=False, metadata={"mask_encoding": "one_bit"},
            input=vid_input("face", {"type": "input_video", "file_id": f.id})))
        if res:
            usage = res["final"].get("usage") or {}
            run.record("NOD face file_id stream", SAM, res["total_s"], usage, first_event_s=res["first_delta_s"],
                       extra=describe(run, "NOD face", res["text"], "cy"))
            run.save_fixture("sam_video_stream_file_id_face", {"events": res["events"]})
        client.files.delete(f.id)

    # 3. non-streaming, lossless
    run.guard(0.02, "sam video rest")
    res = run.attempt("REST eyebrows inline non-stream", SAM, lambda: timed_raw(
        client.responses.with_raw_response.create, model=SAM, store=False,
        input=vid_input("eyebrows", {"type": "input_video", "video_url": data_url(rest, "video/mp4")})))
    if res:
        body, _h, secs = res
        text = output_text(body)
        run.record("REST eyebrows inline non-stream", SAM, secs, body.get("usage"),
                   extra=describe(run, "REST eyebrows", text, "y1") + f"; text bytes {len(text)}")
        run.save_fixture("sam_video_nonstream_lossless_eyebrows", body)
    run.finish()


if __name__ == "__main__":
    main()
