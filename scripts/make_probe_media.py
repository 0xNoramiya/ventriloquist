"""Generate synthetic probe media (no real people) into data/probe_media/.

Outputs
  face_yes_eyebrows.mp4   4 s, 15 fps, 640x480 H.264: eyebrows rise twice (YES), one blink
  face_nod.mp4            same face, head nods twice, eyebrows still
  face_rest_blinks.mp4    same face, only blinks (REST / no signal)
  face_still.png          one frame of the face at an eyebrow peak
  hospital_room.png       640x480 drawing: bed, bedside table with a photo frame, no people
  speech_en.wav           espeak-ng English sentence, 24 kHz mono s16 WAV
  speech_id.wav           espeak-ng Indonesian sentence, 24 kHz mono s16 WAV
  two_voices.wav          two different espeak voices alternating (diarization test)
  media_manifest.json     ground truth: event timings, reference transcripts, file facts

Run:  backend/.venv/bin/python scripts/make_probe_media.py
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "probe_media"

W, H, FPS, SECONDS = 640, 480, 15, 4.0
N_FRAMES = int(FPS * SECONDS)

EN_TEXT = "Your daughter Aisyah went home to rest, she will be back at four."
ID_TEXT = "Anak Bapak, Aisyah, pulang dulu untuk istirahat, nanti jam empat dia kembali."
TWO_VOICE_TURNS = [
    ("A", "en-us", 40, 150, "Good morning. Did you sleep at all last night?"),
    ("B", "en-gb+f4", 85, 165, "She slept a little after midnight. The nurse gave her something for pain."),
    ("A", "en-us", 40, 150, "Okay. Let us check the breathing tube in an hour."),
]

# BGR colours
BG = (225, 215, 200)
SKIN = (150, 185, 225)
SKIN_DARK = (120, 150, 195)
BROW = (40, 45, 60)
EYE_WHITE = (245, 245, 245)
IRIS = (90, 60, 30)
LIP = (95, 95, 185)
TUBE = (230, 240, 240)
TAPE = (200, 230, 240)


def bump(t: float, center: float, half_width: float) -> float:
    """Smooth 0..1..0 raised-cosine bump."""
    d = abs(t - center)
    if d >= half_width:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * d / half_width))


def draw_face(
    brow_raise_px: float = 0.0,
    eye_open: float = 1.0,
    dy: float = 0.0,
    pitch_squash: float = 0.0,
) -> np.ndarray:
    """Cartoon face on a pillow. dy shifts the head; pitch_squash (0..1) foreshortens features
    vertically to fake a forward nod."""
    img = np.full((H, W, 3), BG, np.uint8)
    # pillow
    cv2.ellipse(img, (320, 300), (260, 150), 0, 0, 360, (250, 250, 245), -1)
    cv2.ellipse(img, (320, 300), (260, 150), 0, 0, 360, (210, 210, 205), 2)

    cx, cy = 320, int(240 + dy)
    sy = 1.0 - 0.18 * pitch_squash  # vertical foreshortening of the inner face

    def fy(y_off: float) -> int:
        return int(cy + y_off * sy)

    # neck + gown
    cv2.rectangle(img, (270, fy(150)), (370, H), SKIN_DARK, -1)
    cv2.ellipse(img, (320, H + 40), (220, 90), 0, 180, 360, (200, 170, 120), -1)
    # ears
    for ex in (cx - 148, cx + 148):
        cv2.ellipse(img, (ex, fy(10)), (18, 34), 0, 0, 360, SKIN_DARK, -1)
    # head
    cv2.ellipse(img, (cx, cy), (145, int(185 * sy)), 0, 0, 360, SKIN, -1)
    cv2.ellipse(img, (cx, cy), (145, int(185 * sy)), 0, 0, 360, SKIN_DARK, 2)
    # hair
    cv2.ellipse(img, (cx, fy(-120)), (140, int(80 * sy)), 0, 180, 360, (50, 50, 60), -1)

    # eyes
    eye_y = fy(-20)
    for ex in (cx - 55, cx + 55):
        h_open = max(1, int(16 * eye_open * sy))
        cv2.ellipse(img, (ex, eye_y), (30, h_open), 0, 0, 360, EYE_WHITE, -1)
        if eye_open > 0.25:
            cv2.circle(img, (ex, eye_y), max(2, int(10 * min(1.0, eye_open))), IRIS, -1)
            cv2.circle(img, (ex, eye_y), max(1, int(4 * min(1.0, eye_open))), (10, 10, 10), -1)
        cv2.ellipse(img, (ex, eye_y), (30, h_open), 0, 0, 360, SKIN_DARK, 2)
        if eye_open < 0.25:  # closed lid line
            cv2.line(img, (ex - 30, eye_y), (ex + 30, eye_y), BROW, 3)

    # eyebrows: thick arcs, raised by brow_raise_px (and slightly more arched when raised)
    brow_y = fy(-62) - int(brow_raise_px)
    arch = 10 + int(0.25 * brow_raise_px)
    for ex in (cx - 55, cx + 55):
        pts = []
        for i in range(21):
            u = -1.0 + 2.0 * i / 20.0
            pts.append((int(ex + 38 * u), int(brow_y - arch * (1.0 - u * u))))
        cv2.polylines(img, [np.array(pts, np.int32)], False, BROW, 9, cv2.LINE_AA)

    # nose
    cv2.line(img, (cx, fy(-5)), (cx - 12, fy(45)), SKIN_DARK, 3)
    cv2.line(img, (cx - 12, fy(45)), (cx + 8, fy(48)), SKIN_DARK, 3)
    # mouth with endotracheal tube and tape (cartoon)
    mouth_y = fy(95)
    cv2.ellipse(img, (cx, mouth_y), (38, max(4, int(12 * sy))), 0, 0, 360, LIP, -1)
    cv2.circle(img, (cx + 5, mouth_y), 9, TUBE, -1)
    cv2.line(img, (cx + 5, mouth_y), (cx + 230, mouth_y + 40), TUBE, 14)
    cv2.line(img, (cx + 5, mouth_y), (cx + 230, mouth_y + 40), (170, 180, 180), 2)
    cv2.rectangle(img, (cx - 70, mouth_y - 8), (cx + 70, mouth_y + 8), TAPE, -1)
    return img


def render_clip(kind: str) -> tuple[list[np.ndarray], dict]:
    frames: list[np.ndarray] = []
    truth: dict = {"kind": kind, "fps": FPS, "frames": N_FRAMES, "events": []}
    brow_peaks = [1.0, 2.7] if kind == "yes" else []
    nod_peaks = [1.0, 2.7] if kind == "nod" else []
    blinks = {"yes": [3.6], "nod": [], "rest": [0.6, 1.9, 3.3]}[kind]
    for c in brow_peaks:
        truth["events"].append({"type": "eyebrow_raise", "start_s": c - 0.35, "peak_s": c, "end_s": c + 0.35})
    for c in nod_peaks:
        truth["events"].append({"type": "head_nod_down", "start_s": c - 0.4, "peak_s": c, "end_s": c + 0.4})
    for c in blinks:
        truth["events"].append({"type": "blink", "start_s": c - 0.1, "peak_s": c, "end_s": c + 0.1})

    for i in range(N_FRAMES):
        t = i / FPS
        brow = 28.0 * sum(bump(t, c, 0.35) for c in brow_peaks)
        nod = sum(bump(t, c, 0.4) for c in nod_peaks)
        eye = 1.0 - sum(bump(t, c, 0.1) for c in blinks)
        frames.append(draw_face(brow_raise_px=brow, eye_open=max(0.0, eye), dy=45.0 * nod, pitch_squash=nod))
    return frames, truth


def write_h264(frames: list[np.ndarray], path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", str(path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {path}")


def draw_hospital_room() -> np.ndarray:
    img = np.zeros((H, W, 3), np.uint8)
    img[:330] = (205, 220, 215)  # wall
    img[330:] = (150, 160, 165)  # floor
    for x in range(-200, W, 60):  # floor tiles
        cv2.line(img, (x, H), (x + 120, 330), (135, 145, 150), 1)
    cv2.line(img, (0, 330), (W, 330), (120, 130, 135), 3)
    # window with blinds
    cv2.rectangle(img, (40, 50), (200, 190), (240, 225, 190), -1)
    cv2.rectangle(img, (40, 50), (200, 190), (170, 170, 170), 5)
    for y in range(60, 190, 14):
        cv2.line(img, (45, y), (195, y), (215, 215, 210), 3)
    # wall clock
    cv2.circle(img, (330, 70), 28, (250, 250, 250), -1)
    cv2.circle(img, (330, 70), 28, (60, 60, 60), 3)
    cv2.line(img, (330, 70), (330, 50), (30, 30, 30), 3)
    cv2.line(img, (330, 70), (346, 76), (30, 30, 30), 3)
    # IV pole
    cv2.line(img, (230, 90), (230, 400), (180, 180, 185), 5)
    cv2.line(img, (205, 90), (255, 90), (180, 180, 185), 4)
    cv2.rectangle(img, (240, 95), (262, 140), (235, 240, 240), -1)
    cv2.line(img, (251, 140), (251, 250), (230, 230, 230), 2)
    for dx in (-25, 0, 25):
        cv2.line(img, (230, 400), (230 + dx, 415), (150, 150, 155), 4)
    # bed: headboard, frame, mattress, pillow, blanket, rail, wheels
    cv2.rectangle(img, (260, 170), (290, 360), (150, 140, 120), -1)
    cv2.rectangle(img, (280, 300), (600, 340), (170, 170, 175), -1)
    cv2.rectangle(img, (285, 255), (600, 305), (245, 245, 240), -1)
    cv2.ellipse(img, (335, 252), (48, 22), 0, 0, 360, (252, 252, 252), -1)
    cv2.ellipse(img, (335, 252), (48, 22), 0, 0, 360, (200, 200, 200), 2)
    cv2.rectangle(img, (390, 245), (600, 310), (190, 150, 110), -1)
    cv2.line(img, (390, 262), (600, 262), (220, 190, 160), 6)
    cv2.rectangle(img, (420, 225), (590, 232), (160, 160, 165), -1)
    for x in (430, 500, 580):
        cv2.line(img, (x, 232), (x, 255), (160, 160, 165), 3)
    for x in (300, 590):
        cv2.line(img, (x, 340), (x, 385), (110, 110, 115), 6)
        cv2.circle(img, (x, 392), 10, (40, 40, 40), -1)
    # bedside table with drawers
    cv2.rectangle(img, (90, 260), (200, 400), (90, 120, 160), -1)
    cv2.rectangle(img, (90, 260), (200, 400), (60, 85, 120), 3)
    for y in (300, 350):
        cv2.line(img, (95, y), (195, y), (60, 85, 120), 2)
        cv2.rectangle(img, (135, y + 15), (155, y + 22), (200, 200, 200), -1)
    cv2.rectangle(img, (85, 252), (205, 262), (70, 100, 140), -1)
    # photo frame on the table (landscape picture, no people), with a stand
    cv2.rectangle(img, (110, 180), (175, 250), (30, 60, 110), -1)
    cv2.rectangle(img, (117, 187), (168, 243), (230, 200, 150), -1)
    pts = np.array([[117, 243], [135, 205], [148, 225], [158, 210], [168, 243]], np.int32)
    cv2.fillPoly(img, [pts], (90, 140, 90))
    cv2.circle(img, (158, 197), 6, (80, 220, 250), -1)
    # water cup next to the frame
    cv2.rectangle(img, (182, 228), (196, 252), (230, 220, 200), -1)
    # vital-signs monitor on the wall
    cv2.rectangle(img, (470, 60), (600, 150), (40, 40, 40), -1)
    cv2.rectangle(img, (478, 68), (592, 142), (20, 30, 20), -1)
    ecg = [(480, 100), (500, 100), (506, 85), (512, 115), (518, 100), (545, 100), (551, 82), (557, 118), (563, 100), (590, 100)]
    cv2.polylines(img, [np.array(ecg, np.int32)], False, (80, 230, 80), 2)
    cv2.putText(img, "98", (548, 136), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 230, 230), 1)
    return img


def tts(voice: str, pitch: int, speed: int, text: str, out_wav: Path) -> None:
    """espeak-ng -> 24 kHz mono s16 RIFF WAV (the native rate of the transcription model)."""
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "raw.wav"
        subprocess.run(["espeak-ng", "-v", voice, "-p", str(pitch), "-s", str(speed), "-w", str(raw), text], check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ac", "1", "-ar", "24000",
             "-c:a", "pcm_s16le", "-map_metadata", "-1", str(out_wav)],
            check=True,
        )


def silence_wav(seconds: float, out_wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{seconds}", "-c:a", "pcm_s16le", str(out_wav)],
        check=True,
    )


def concat_wavs(parts: list[Path], out_wav: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", "-map_metadata", "-1", str(out_wav)],
            check=True,
        )


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return round(float(out.stdout.strip()), 3)


def main() -> None:
    for tool in ("ffmpeg", "ffprobe", "espeak-ng"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found on PATH")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"generator": "scripts/make_probe_media.py", "video": {}, "image": {}, "audio": {}}

    for kind, name in (("yes", "face_yes_eyebrows.mp4"), ("nod", "face_nod.mp4"), ("rest", "face_rest_blinks.mp4")):
        frames, truth = render_clip(kind)
        path = OUT / name
        write_h264(frames, path)
        truth.update({"width": W, "height": H, "codec": "h264", "bytes": path.stat().st_size, "duration_s": probe_duration(path)})
        manifest["video"][name] = truth
        if kind == "yes":
            peak_frame = int(truth["events"][0]["peak_s"] * FPS)
            cv2.imwrite(str(OUT / "face_still.png"), frames[peak_frame])
            manifest["image"]["face_still.png"] = {"width": W, "height": H, "source": f"{name} frame {peak_frame} (eyebrow peak)"}

    room = draw_hospital_room()
    cv2.imwrite(str(OUT / "hospital_room.png"), room)
    manifest["image"]["hospital_room.png"] = {
        "width": W, "height": H,
        "objects": {"bed": [260, 170, 600, 400], "bedside table": [85, 252, 205, 400], "photo frame": [110, 180, 175, 250]},
        "note": "boxes are [x1, y1, x2, y2] in pixels, approximate",
    }

    tts("en-us", 50, 150, EN_TEXT, OUT / "speech_en.wav")
    tts("id", 50, 140, ID_TEXT, OUT / "speech_id.wav")
    manifest["audio"]["speech_en.wav"] = {"language": "English", "reference": EN_TEXT, "duration_s": probe_duration(OUT / "speech_en.wav")}
    manifest["audio"]["speech_id.wav"] = {"language": "Indonesian", "reference": ID_TEXT, "duration_s": probe_duration(OUT / "speech_id.wav")}

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        gap = tdp / "gap.wav"
        silence_wav(0.8, gap)
        parts: list[Path] = []
        for i, (_spk, voice, pitch, speed, text) in enumerate(TWO_VOICE_TURNS):
            p = tdp / f"turn{i}.wav"
            tts(voice, pitch, speed, text, p)
            parts += [p, gap]
        concat_wavs(parts[:-1], OUT / "two_voices.wav")
    manifest["audio"]["two_voices.wav"] = {
        "language": "English",
        "turns": [{"speaker": s, "espeak_voice": v, "pitch": p, "text": t} for s, v, p, _sp, t in TWO_VOICE_TURNS],
        "reference": " ".join(t for *_x, t in TWO_VOICE_TURNS),
        "duration_s": probe_duration(OUT / "two_voices.wav"),
    }

    (OUT / "media_manifest.json").write_text(json.dumps(manifest, indent=2))
    for p in sorted(OUT.iterdir()):
        print(f"{p.relative_to(REPO)}  {p.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
