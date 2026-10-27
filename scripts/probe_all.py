"""Run every probe in order; continue past failures; print a summary and the spend ledger total.

Run: backend/.venv/bin/python scripts/probe_all.py
Mask decoding in the SAM probes needs `meta-sam-parser` importable (pip install meta-sam-parser).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBES = [
    "probe_models.py",
    "probe_spark_text.py",
    "probe_spark_image.py",
    "probe_spark_video.py",
    "probe_sam_image.py",
    "probe_sam_video.py",
    "probe_transcribe.py",
    "probe_wonder.py",
    "probe_baseten.py",
]


def main() -> None:
    results = []
    for name in PROBES:
        t0 = time.perf_counter()
        print(f"\n##### {name}", flush=True)
        try:
            code = subprocess.run(
                [sys.executable, str(HERE / name)], cwd=HERE.parent, timeout=900
            ).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
        results.append((name, code, time.perf_counter() - t0))
    sys.path.insert(0, str(HERE))
    from _probe_common import ledger_total

    print("\n##### summary")
    for name, code, secs in results:
        print(f"{'ok  ' if code == 0 else 'FAIL'} {name:24s} exit={code} {secs:6.1f}s")
    print(f"spend ledger total: ${ledger_total():.4f}")
    sys.exit(0 if all(c == 0 for _, c, _ in results) else 1)


if __name__ == "__main__":
    main()
