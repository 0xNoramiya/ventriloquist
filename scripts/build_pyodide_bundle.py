"""Package the backend Python sources for the in-browser demo (Pyodide).

Writes a zip with config.yaml and backend/app (minus the web server and the modules that need
OpenCV or the network) to frontend/public/pyodide/backend.zip by default. The browser demo unpacks
it into Pyodide's virtual file system and imports app.browser.

    backend/.venv/bin/python scripts/build_pyodide_bundle.py [--out path.zip]
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_FILES = {"main.py", "cli.py"}
SKIP_DIRS = {"__pycache__"}


def build(out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "config.yaml", "config.yaml")
        app = ROOT / "backend" / "app"
        for path in sorted(app.rglob("*")):
            if path.is_dir() or SKIP_DIRS & set(path.parts):
                continue
            if path.parent == app and path.name in SKIP_FILES:
                continue
            if path.suffix not in {".py", ".yaml", ".json", ".md"}:
                continue
            z.write(path, path.relative_to(ROOT).as_posix())
            count += 1
    return count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "frontend" / "public" / "pyodide" / "backend.zip")
    args = ap.parse_args()
    n = build(args.out)
    print(f"wrote {args.out} ({n} files, {args.out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
