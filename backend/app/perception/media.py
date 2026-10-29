"""Media normalisation with ffmpeg.

Browsers record WebM (Chrome/Android) or MP4 (Safari/iOS). SAM 3.1 and Muse Spark want H.264 MP4,
Voice Transcribe wants mono 16-bit WAV at 16/24 kHz. Front-camera previews are mirrored in the UI
only; the recorded stream is not, and nothing here relies on left/right words.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: float = 60) -> None:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.decode(errors="replace")[-600:])


async def run_async(cmd: list[str], timeout: float = 60) -> None:
    await asyncio.to_thread(_run, cmd, timeout)


def normalize_video_cmd(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    fps: int,
    max_s: float | None,
    crop: tuple[int, int, int, int] | None = None,
) -> list[str]:
    vf = (
        (f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]}," if crop else "")
        + f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
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


def roi_crop_px(
    src_w: int, src_h: int, roi: list[float], out_w: int, out_h: int
) -> tuple[int, int, int, int]:
    """Map a region given as fractions of the normalised (scaled and padded) frame back to source
    pixels, as ffmpeg crop width, height, x, y (even sizes for H.264)."""
    s = min(out_w / src_w, out_h / src_h)
    ox, oy = (out_w - src_w * s) / 2, (out_h - src_h * s) / 2
    x0 = max(0.0, (roi[0] * out_w - ox) / s)
    y0 = max(0.0, (roi[1] * out_h - oy) / s)
    x1 = min(float(src_w), (roi[2] * out_w - ox) / s)
    y1 = min(float(src_h), (roi[3] * out_h - oy) / s)
    w = max(2, int(x1 - x0) // 2 * 2)
    h = max(2, int(y1 - y0) // 2 * 2)
    return w, h, int(x0), int(y0)


def frame_size(path: Path) -> tuple[int, int]:
    cap = cv2.VideoCapture(str(path))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()


async def normalize_video(
    src: Path,
    dst: Path,
    width: int = 640,
    height: int = 480,
    fps: int = 15,
    max_s: float | None = 6.0,
    roi: list[float] | None = None,
) -> Path:
    """Scale and pad to width x height at fps. With `roi` (fractions of that normalised frame),
    crop the source to the region first, at the source's full resolution."""
    crop = None
    if roi:
        w, h = frame_size(src)
        if w and h:
            crop = roi_crop_px(w, h, roi, width, height)
    await run_async(normalize_video_cmd(src, dst, width, height, fps, max_s, crop))
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


def data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
