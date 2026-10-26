"""Media normalisation with ffmpeg (brief 9.1).

Browsers record WebM (Chrome/Android) or MP4 (Safari/iOS). SAM 3.1 and Muse Spark want H.264 MP4,
Voice Transcribe wants mono 16-bit WAV at 16/24 kHz. Front-camera previews are mirrored in the UI
only; the recorded stream is not, and nothing here relies on left/right words.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class MediaError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _run(cmd: list[str], timeout: float = 60) -> None:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.decode(errors="replace")[-600:])


async def run_async(cmd: list[str], timeout: float = 60) -> None:
    await asyncio.to_thread(_run, cmd, timeout)


def normalize_video_cmd(
    src: Path, dst: Path, width: int, height: int, fps: int, max_s: float | None
) -> list[str]:
    vf = (
        f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    if max_s:
        cmd += ["-t", f"{max_s:.2f}"]
    return cmd + [
        "-an",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "28",
        "-movflags",
        "+faststart",
        str(dst),
    ]


async def normalize_video(
    src: Path,
    dst: Path,
    width: int = 640,
    height: int = 480,
    fps: int = 15,
    max_s: float | None = 6.0,
) -> Path:
    await run_async(normalize_video_cmd(src, dst, width, height, fps, max_s))
    return dst


async def to_wav(src: Path, dst: Path, rate: int = 16000) -> Path:
    await run_async(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-c:a",
            "pcm_s16le",
            "-map_metadata",
            "-1",
            str(dst),
        ]
    )
    return dst


def probe_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        timeout=20,
    )
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


@dataclass
class Frames:
    images: list[np.ndarray]  # BGR
    times: list[float]
    fps: float


def read_frames(path: Path, max_frames: int | None = None, gray: bool = False) -> Frames:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    images: list[np.ndarray] = []
    times: list[float] = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        images.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame)
        times.append(i / fps)
        i += 1
    cap.release()
    if max_frames and len(images) > max_frames:
        idx = np.linspace(0, len(images) - 1, max_frames).round().astype(int)
        images = [images[k] for k in idx]
        times = [times[k] for k in idx]
    return Frames(images, times, fps)


def sample_jpegs(path: Path, n: int = 8, quality: int = 80) -> list[tuple[float, bytes]]:
    frames = read_frames(path, max_frames=n)
    out = []
    for img, t in zip(frames.images, frames.times, strict=True):
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            out.append((t, buf.tobytes()))
    return out


def data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
