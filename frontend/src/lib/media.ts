// Camera helpers: front camera stream, single frames and short clips for the backend.

const CLIP_TYPES = ['video/webm;codecs=vp8', 'video/webm', 'video/mp4'];

export function recorderMime(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined;
  return CLIP_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
}

export function cameraSupported(): boolean {
  return Boolean(navigator.mediaDevices?.getUserMedia) && window.isSecureContext;
}

export async function startCamera(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      facingMode: 'user',
      width: { ideal: 640 },
      height: { ideal: 480 },
      frameRate: { ideal: 15, max: 30 },
    },
  });
}

export function stopStream(stream: MediaStream | null | undefined): void {
  stream?.getTracks().forEach((t) => t.stop());
}

/** One JPEG frame from a playing <video>. The frame is not mirrored. */
export async function grabFrame(video: HTMLVideoElement): Promise<Blob> {
  const w = video.videoWidth || 640;
  const h = video.videoHeight || 480;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas unavailable');
  ctx.drawImage(video, 0, 0, w, h);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('no frame'))), 'image/jpeg', 0.85),
  );
}

// The backend scales answer clips down to 320x240, so the browser's default bitrate (often
// 2.5 Mbps) only slows the upload.
const CLIP_BITS_PER_SECOND = 800_000;

/** Record `ms` of video from the stream. The backend normalises the container with ffmpeg. */
export function recordClip(stream: MediaStream, ms: number): Promise<Blob> {
  const mimeType = recorderMime();
  const rec = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: CLIP_BITS_PER_SECOND });
  const chunks: Blob[] = [];
  return new Promise((resolve, reject) => {
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.onerror = () => reject(new Error('recording failed'));
    rec.onstop = () =>
      resolve(new Blob(chunks, { type: rec.mimeType || mimeType || 'video/webm' }));
    rec.start(250);
    window.setTimeout(() => {
      if (rec.state !== 'inactive') rec.stop();
    }, ms);
  });
}

type WakeLockSentinelLike = { release: () => Promise<void> };

/** Keep the patient screen on. Re-acquired when the tab becomes visible again. */
export function keepAwake(): () => void {
  let lock: WakeLockSentinelLike | null = null;
  const nav = navigator as Navigator & {
    wakeLock?: { request: (type: 'screen') => Promise<WakeLockSentinelLike> };
  };
  const acquire = async () => {
    try {
      lock = (await nav.wakeLock?.request('screen')) ?? null;
    } catch {
      lock = null; // not supported or refused; the screen may dim
    }
  };
  const onVisible = () => {
    if (document.visibilityState === 'visible') void acquire();
  };
  void acquire();
  document.addEventListener('visibilitychange', onVisible);
  return () => {
    document.removeEventListener('visibilitychange', onVisible);
    void lock?.release();
  };
}
