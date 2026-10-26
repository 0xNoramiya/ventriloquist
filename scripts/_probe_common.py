"""Shared helpers for scripts/probe_*.py.

- loads .env and config.yaml (model ids, base URLs, prices)
- skip(): exit 0 with a message when a key or dependency is missing
- meta_client(): OpenAI SDK client for the Meta Model API (the SDK does not read MODEL_API_KEY itself)
- Timer, key_tree(), estimate_cost()
- ProbeRun: records each call, enforces a spend cap via a ledger, saves sanitized fixtures to
  backend/tests/fixtures/meta_api/<name>.json and appends a dated block to the
  "## Probe log" section of docs/API_NOTES.md

Secrets are never printed: sanitize() replaces any API key value found in data before it is
printed or written.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import mimetypes
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "data" / "probe_media"
FIXTURES = REPO / "backend" / "tests" / "fixtures" / "meta_api"
NOTES = REPO / "docs" / "API_NOTES.md"
LEDGER = MEDIA / "spend_ledger.jsonl"
BUDGET_CAP_USD = 1.80  # hard stop for all probes together (task budget is < $2)

load_dotenv(REPO / ".env")
CONFIG: dict = yaml.safe_load((REPO / "config.yaml").read_text())
MODELS: dict = CONFIG["models"]
PRICING: dict = CONFIG["pricing"]
META_BASE_URL: str = CONFIG["providers"]["meta_api"]["base_url"]
BASETEN_BASE_URL: str = CONFIG["providers"]["baseten"]["base_url"]

_SECRET_ENV = ("MODEL_API_KEY", "BASETEN_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "LIVE_PASSCODE")


def env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def skip(message: str) -> None:
    print(f"[skip] {message}")
    sys.exit(0)


def require_env(name: str) -> str:
    value = env(name)
    if value is None:
        skip(f"{name} is empty in .env; nothing to probe.")
    return value  # type: ignore[return-value]


def meta_client(timeout: float = 120.0):
    from openai import OpenAI

    return OpenAI(base_url=META_BASE_URL, api_key=require_env("MODEL_API_KEY"), timeout=timeout, max_retries=0)


def media(name: str) -> Path:
    path = MEDIA / name
    if not path.exists():
        print(f"[info] {path.relative_to(REPO)} missing; generating probe media")
        sys.path.insert(0, str(REPO / "scripts"))
        import make_probe_media

        make_probe_media.main()
    return path


def manifest() -> dict:
    media("media_manifest.json")
    return json.loads((MEDIA / "media_manifest.json").read_text())


def data_url(path: Path, mime: str | None = None) -> str:
    mime = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


class Timer:
    def __enter__(self) -> Timer:
        self.t0 = time.perf_counter()
        self.first: float | None = None
        return self

    def mark_first(self) -> None:
        if self.first is None:
            self.first = time.perf_counter() - self.t0

    def __exit__(self, *exc: object) -> None:
        self.s = time.perf_counter() - self.t0


def sanitize(obj: Any) -> Any:
    secrets = [v for v in (env(n) for n in _SECRET_ENV) if v and len(v) > 6]

    def walk(o: Any) -> Any:
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k == "encrypted_content" and isinstance(v, str) and len(v) > 80:
                    out[k] = v[:48] + f"...<truncated {len(v)} chars>"
                else:
                    out[k] = walk(v)
            return out
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            for s in secrets:
                o = o.replace(s, "<redacted>")
            return o
        return o

    return walk(obj)


def key_tree(obj: Any, max_depth: int = 7, max_items: int = 2, max_str: int = 80) -> str:
    """Compact, truncated tree of a JSON-like object: field paths, types and sample values."""
    lines: list[str] = []

    def walk(o: Any, prefix: str, depth: int) -> None:
        if depth > max_depth:
            lines.append(f"{prefix}: ...")
            return
        if isinstance(o, dict):
            if not o:
                lines.append(f"{prefix}: {{}}")
            for k, v in o.items():
                walk(v, f"{prefix}.{k}" if prefix else k, depth + 1)
        elif isinstance(o, list):
            lines.append(f"{prefix}: list[{len(o)}]")
            for i, v in enumerate(o[:max_items]):
                walk(v, f"{prefix}[{i}]", depth + 1)
        else:
            s = json.dumps(o, ensure_ascii=False)
            if len(s) > max_str:
                s = s[:max_str] + f"...(+{len(s) - max_str})"
            lines.append(f"{prefix}: {s}")

    walk(sanitize(obj), "", 0)
    return "\n".join(lines)


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=False)
    return obj


RATE_HEADERS = ("x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-tokens", "retry-after", "x-request-id")


def timed_raw(create_fn: Callable[..., Any], **kwargs: Any) -> tuple[dict, dict, float]:
    """Call an SDK `.with_raw_response.<method>` and return (raw JSON body, selected headers, seconds)."""
    t0 = time.perf_counter()
    raw = create_fn(**kwargs)
    body = raw.http_response.json()
    secs = time.perf_counter() - t0
    headers = {k: v for k, v in raw.headers.items() if k.lower() in RATE_HEADERS}
    return body, headers, secs


def stream_response(client: Any, **kwargs: Any) -> dict:
    """POST /v1/responses with stream=true via the SDK; collect every SSE event.
    Returns {events, text, final, first_delta_s, total_s, event_types}."""
    t0 = time.perf_counter()
    first = None
    events: list[dict] = []
    text_parts: list[str] = []
    final: dict | None = None
    stream = client.responses.create(stream=True, **kwargs)
    for ev in stream:
        d = ev.model_dump(mode="json")
        events.append(d)
        if d.get("type") == "response.output_text.delta":
            if first is None:
                first = time.perf_counter() - t0
            text_parts.append(d.get("delta", ""))
        if d.get("type") in ("response.completed", "response.failed", "response.incomplete"):
            final = d.get("response")
    types: dict[str, int] = {}
    for e in events:
        types[e.get("type", "?")] = types.get(e.get("type", "?"), 0) + 1
    return {"events": events, "text": "".join(text_parts), "final": final or {}, "first_delta_s": first,
            "total_s": time.perf_counter() - t0, "event_types": types}


def output_text(body: dict) -> str:
    """Concatenate output[].content[].text of type output_text from a raw Responses body."""
    parts = []
    for item in body.get("output") or []:
        if item.get("type") == "message":
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    parts.append(c.get("text", ""))
    return "".join(parts)


_SAM_RECORD = re.compile(r"(\d+)<\|box;([^|]*)\|><\|mask;([^|]*?)data=(\d+),(\d+),(.)")


def parse_sam_text(text: str) -> list[dict]:
    """Parse SAM 3.1 wire text (one line per frame) into records:
    {frame, object_id, box: [x1,y1,x2,y2] (inclusive px), frame_w, frame_h, c, mask_h, mask_w, mask_enc}.
    Mask payloads are skipped here; decode them with meta_sam_parser.decode_mask_to_raster."""
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        fm = re.match(r"<(\d+)f>", line)
        if not fm:
            continue
        frame = int(fm.group(1))
        for m in _SAM_RECORD.finditer(line, fm.end()):
            box = dict(kv.split("=", 1) for kv in m.group(2).split(";") if "=" in kv)
            mask_kv = dict(kv.split("=", 1) for kv in m.group(3).split(";") if "=" in kv)
            records.append({
                "frame": frame, "object_id": int(m.group(1)),
                "box": [int(box["x1"]), int(box["y1"]), int(box["x2"]), int(box["y2"])],
                "frame_w": int(box["w"]), "frame_h": int(box["h"]),
                "c": float(box["c"]) if "c" in box else None,
                "mask_c": float(mask_kv["c"]) if "c" in mask_kv else None,
                "mask_h": int(m.group(4)), "mask_w": int(m.group(5)),
                "mask_enc": {"~": "lossless", "!": "one_bit"}.get(m.group(6), m.group(6)),
            })
    return records


def sam_mask_payloads(text: str) -> list[tuple[int, int, str, int, int, str]]:
    """(frame, object_id, encoding marker, H, W, base85 payload) for every mask in the wire text."""
    out = []
    for line in text.splitlines():
        fm = re.match(r"<(\d+)f>", line.strip())
        if not fm:
            continue
        for m in re.finditer(r"(\d+)<\|box;[^|]*\|><\|mask;[^|]*?data=(\d+),(\d+),(.)(.*?)\|>", line):
            out.append((int(fm.group(1)), int(m.group(1)), m.group(4), int(m.group(2)), int(m.group(3)), m.group(5)))
    return out


def decode_sam_masks(text: str) -> dict | None:
    """Decode masks with the official meta_sam_parser if importable; returns stats or None."""
    try:
        from meta_sam_parser import SegmentationMask, decode_mask_to_raster
    except ImportError:
        return None
    stats = {"decoded": 0, "foreground_px": [], "errors": 0}
    for _frame, _oid, enc, h, w, payload in sam_mask_payloads(text):
        try:
            # payload passed to the parser keeps its leading encoding marker (~ or !)
            raster = decode_mask_to_raster(SegmentationMask(
                encoding="lossless" if enc == "~" else "one_bit", payload=enc + payload, width=w, height=h))
            stats["decoded"] += 1
            stats["foreground_px"].append(sum(raster))
        except Exception:
            stats["errors"] += 1
    return stats


def usage_of(resp: Any) -> dict:
    data = to_jsonable(resp)
    if isinstance(data, dict):
        if isinstance(data.get("usage"), dict):
            return data["usage"]
        if isinstance(data.get("response"), dict) and isinstance(data["response"].get("usage"), dict):
            return data["response"]["usage"]
    return {}


def estimate_cost(model: str, usage: dict | None = None, audio_ms: int | None = None) -> float:
    """Estimated USD from config.yaml prices. Token models: (uncached in, cached in, out).
    SAM: per image / per video frame with the 50-frame minimum. Transcribe: whole seconds."""
    p = PRICING.get(model) or PRICING.get(model.removesuffix("-contributor")) or {}
    usage = usage or {}
    if audio_ms is not None:
        return (audio_ms // 1000) / 60.0 * float(p.get("per_audio_minute", 0.0))
    if "video_frames_processed" in usage:
        frames = max(int(usage["video_frames_processed"] or 0), int(p.get("min_video_frames", 0)))
        return frames * float(p.get("per_video_frame", 0.0))
    if "images_processed" in usage:
        return int(usage["images_processed"] or 0) * float(p.get("per_image", 0.0))
    inp = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    out = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    cached = int(details.get("cached_tokens", 0) or 0)
    return (
        (inp - cached) * float(p.get("input_per_m", 0.0))
        + cached * float(p.get("cached_input_per_m", p.get("input_per_m", 0.0)))
        + out * float(p.get("output_per_m", 0.0))
    ) / 1e6


def ledger_total() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in LEDGER.read_text().splitlines() if line.strip())


class BudgetExceeded(RuntimeError):
    pass


class ProbeRun:
    """Collects call records for one probe script; writes fixtures and the docs log."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rows: list[dict] = []
        self.notes: list[str] = []
        self.started = dt.datetime.now(dt.UTC)
        print(f"=== {name}  (ledger so far: ${ledger_total():.4f} of ${BUDGET_CAP_USD:.2f} cap)")

    def guard(self, est_usd: float, label: str) -> None:
        """Refuse a call whose rough upper-bound cost would push the ledger over the cap."""
        total = ledger_total()
        if est_usd > 0.50:
            raise BudgetExceeded(f"{label}: estimated ${est_usd:.3f} > $0.50 single-call limit")
        if total + est_usd > BUDGET_CAP_USD:
            raise BudgetExceeded(f"{label}: ledger ${total:.4f} + est ${est_usd:.4f} > cap ${BUDGET_CAP_USD}")

    def record(
        self,
        label: str,
        model: str,
        latency_s: float | None,
        usage: dict | None = None,
        usd: float | None = None,
        status: str = "ok",
        extra: str = "",
        first_event_s: float | None = None,
    ) -> float:
        usage = usage or {}
        if usd is None:
            usd = estimate_cost(model, usage) if usage else 0.0
        row = {
            "label": label, "model": model, "status": status, "latency_s": latency_s,
            "first_event_s": first_event_s, "usage": usage, "usd": usd, "extra": extra,
        }
        self.rows.append(row)
        with LEDGER.open("a") as f:
            f.write(json.dumps({"ts": dt.datetime.now(dt.UTC).isoformat(), "probe": self.name, "label": label,
                                "model": model, "usd": usd}) + "\n")
        lat = f"{latency_s:.2f}s" if latency_s is not None else "-"
        fe = f" (first event {first_event_s:.2f}s)" if first_event_s is not None else ""
        print(f"[{status}] {label}: {model} {lat}{fe} usage={compact_usage(usage)} est=${usd:.5f} {extra}")
        return usd

    def note(self, text: str) -> None:
        print(f"  note: {text}")
        self.notes.append(text)

    def save_fixture(self, fixture: str, data: Any) -> Path:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        path = FIXTURES / f"{fixture}.json"
        path.write_text(json.dumps(sanitize(to_jsonable(data)), indent=2, ensure_ascii=False) + "\n")
        print(f"  fixture: {path.relative_to(REPO)}")
        return path

    def attempt(self, label: str, model: str, fn: Callable[[], Any], fixture: str | None = None) -> Any:
        """Run fn(); on an API error, record status + error body (saved as fixture if named)."""
        from openai import APIConnectionError, APIStatusError, APITimeoutError

        t0 = time.perf_counter()
        try:
            return fn()
        except APIStatusError as e:
            try:
                body = e.response.json()
            except Exception:
                body = {"raw_text": e.response.text[:2000]}
            self.record(label, model, time.perf_counter() - t0, status=f"HTTP {e.status_code}",
                        extra=json.dumps(sanitize(body))[:300])
            if fixture:
                self.save_fixture(fixture, {"http_status": e.status_code, "body": body})
            return None
        except (APIConnectionError, APITimeoutError) as e:
            self.record(label, model, time.perf_counter() - t0, status="network-error", extra=str(e)[:200])
            return None

    def finish(self) -> None:
        total = sum(r["usd"] for r in self.rows)
        print(f"=== {self.name} done: {len(self.rows)} calls, est ${total:.5f}; ledger ${ledger_total():.4f}")
        append_probe_log(self.name, self.started, self.rows, self.notes)


def compact_usage(u: dict) -> str:
    if not u:
        return "{}"
    keep = {}
    for k in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "images_processed",
              "video_frames_processed", "audio_ms"):
        if k in u:
            keep[k] = u[k]
    for parent, child in (("input_tokens_details", "cached_tokens"), ("output_tokens_details", "reasoning_tokens"),
                          ("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
        d = u.get(parent)
        if isinstance(d, dict) and d.get(child):
            keep[child] = d[child]
    return json.dumps(keep)


def append_probe_log(name: str, started: dt.datetime, rows: list[dict], notes: list[str]) -> None:
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    text = NOTES.read_text() if NOTES.exists() else "# API notes\n"
    if "\n## Probe log" not in text:
        text = text.rstrip("\n") + "\n\n## Probe log\n\nAppended by `scripts/_probe_common.py`; newest last.\n"
    block = [f"\n### {started.strftime('%Y-%m-%d %H:%M UTC')} `{name}`\n",
             "| call | model | status | latency | usage | est. USD |", "|---|---|---|---|---|---|"]
    for r in rows:
        lat = "-" if r["latency_s"] is None else f"{r['latency_s']:.2f}s"
        if r.get("first_event_s") is not None:
            lat += f" (1st {r['first_event_s']:.2f}s)"
        extra = f" {r['extra']}" if r["extra"] else ""
        status = (r["status"] + extra).replace("|", "/").replace("\n", " ")[:220]
        block.append(f"| {r['label']} | `{r['model']}` | {status} | {lat} | `{compact_usage(r['usage'])}` | {r['usd']:.5f} |")
    for n in notes:
        block.append(f"- {n}")
    NOTES.write_text(text.rstrip("\n") + "\n" + "\n".join(block) + "\n")
