"""Generate AAC pictograms for every taxonomy message with Muse Image (muse-image-1.0).

Picture symbols are standard on AAC boards; they help patients with low vision, limited literacy or
fatigue recognise a message at a glance. Images are generated (we own them), checked by eye on a
contact sheet, downscaled to 256 px WebP and committed to frontend/public/pictograms/{id}.webp.
Cost: $0.01 per image (docs/API_NOTES.md section 9).

    PYTHONPATH=backend:. backend/.venv/bin/python scripts/generate_pictograms.py [--only thirst,cold] [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "public" / "pictograms"
RAW = ROOT / "data" / "pictograms"

STYLE = (
    "Flat pictogram icon for a hospital patient communication board. Thick dark charcoal outlines, "
    "two calm colours (soft blue and warm orange), plain white background, centred, generous margin, "
    "friendly and simple, no text, no letters, no numbers, no logos."
)

SUBJECTS = {
    "pain": "a simple human torso outline with a red jagged spark showing pain",
    "breathing": "a pair of lungs with a short strained airflow arrow",
    "suction": "a side view of a throat with small bubbles of mucus and a thin clean tube",
    "tube_discomfort": "a breathing tube held by a strip of tape, with a small zigzag of discomfort",
    "thirst": "a simple glass of water with a single water drop above it",
    "nausea": "a stomach outline with a wavy queasy line",
    "itch": "a hand scratching a forearm with small motion marks",
    "position": "a hospital bed with a curved arrow showing turning over",
    "hands_uncomfortable": "an open hand with small tension lines around the fingers",
    "toilet": "a simple toilet",
    "tired": "a pillow with a crescent moon above it",
    "hot": "a thermometer with a high reading next to a sun",
    "cold": "a thermometer with a low reading next to a snowflake",
    "light": "a ceiling lamp with bright rays and a hand shading eyes",
    "noise": "a loudspeaker with loud sound waves",
    "what_happened": "a question mark above a hospital bed",
    "where": "a location pin above a hospital building",
    "time": "a wall clock beside a calendar page without numbers",
    "tube_when": "a breathing tube next to a clock",
    "talk_staff": "a stethoscope with an empty speech bubble",
    "scared": "a simple worried face",
    "company": "two hands gently holding each other",
    "thanks": "a heart held in two open hands",
    "see_person": "a simple person silhouette waving hello",
    "where_person": "a simple person silhouette with a question mark",
    "call_person": "a phone handset next to a simple person silhouette",
    "want_item": "an open box with an arrow pointing toward the viewer",
    "tell_family_ok": "three simple family silhouettes with a thumbs-up",
    "pray": "two hands pressed together in prayer, no religious symbols",
    "glasses_hearing": "a pair of eyeglasses next to a hearing aid",
    "phone_music": "a smartphone with musical notes floating from it",
    "spell": "a pencil writing on a blank card",
    "stop": "a raised open hand making a gentle stop gesture",
    "other": "a speech bubble with three dots",
}


async def generate(
    client: httpx.AsyncClient, key: str, hid: str, subject: str, sem: asyncio.Semaphore
) -> str:
    async with sem:
        r = await client.post(
            "https://api.meta.ai/v1/images/generations",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "muse-image-1.0", "prompt": f"{STYLE} Subject: {subject}.", "n": 1},
            timeout=120,
        )
        if r.status_code != 200:
            return f"{hid}: HTTP {r.status_code} {r.text[:200]}"
        data = r.json()
        raw = RAW / f"{hid}.webp"
        raw.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(raw),
                "-vf",
                "scale=256:256",
                "-c:v",
                "libwebp",
                "-quality",
                "82",
                str(OUT / f"{hid}.webp"),
            ],
            check=True,
        )
        (RAW / f"{hid}.json").write_text(
            json.dumps({"prompt": f"{STYLE} Subject: {subject}.", "usage": data.get("usage")})
        )
        return f"{hid}: ok"


def contact_sheet(path: Path) -> None:
    files = sorted(OUT.glob("*.webp"))
    inputs: list[str] = []
    for f in files:
        inputs += ["-i", str(f)]
    n = len(files)
    cols = 7
    layout = "|".join(f"{(i % cols) * 256}_{(i // cols) * 256}" for i in range(n))
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            f"xstack=inputs={n}:layout={layout}:fill=white",
            str(path),
        ],
        check=True,
    )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sheet", type=Path, default=None)
    args = ap.parse_args()
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    key = os.environ.get("MODEL_API_KEY", "").strip()
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    wanted = [s for s in args.only.split(",") if s] or list(SUBJECTS)
    todo = [h for h in wanted if args.force or not (OUT / f"{h}.webp").exists()]
    if todo and not key:
        print("MODEL_API_KEY not set; nothing generated.")
        return
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        for line in await asyncio.gather(
            *(generate(client, key, h, SUBJECTS[h], sem) for h in todo)
        ):
            print(line)
    print(f"generated {len(todo)} images (~${0.01 * len(todo):.2f})")
    if args.sheet:
        contact_sheet(args.sheet)
        print(f"contact sheet: {args.sheet}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
