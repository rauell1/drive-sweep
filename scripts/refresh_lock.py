"""Regenerate requirements-dev.lock (hash locked Windows build and test dependencies).

    python scripts/refresh_lock.py            # keep current versions, only add what changed
    python scripts/refresh_lock.py --upgrade  # move every package to its newest allowed version

Needs uv (https://docs.astral.sh/uv/). The lock targets 64-bit Windows and Python 3.12,
matching the CI and release builds, whatever machine you run this on.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements-dev.lock"
HEADER = (
    "# Hash-locked Windows build and test dependencies used by CI (pip install --require-hashes).\n"
    "# Regenerate after changing requirements*.txt:\n"
    "#   python scripts/refresh_lock.py            (add --upgrade to move to the newest versions)\n"
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upgrade", action="store_true", help="upgrade every package to its newest allowed version")
    args = ap.parse_args()
    uv = shutil.which("uv")
    if not uv:
        print("uv was not found. Install it from https://docs.astral.sh/uv/ and try again.", file=sys.stderr)
        return 1
    cmd = [
        uv, "pip", "compile", str(ROOT / "requirements-dev.txt"),
        "--python-platform", "x86_64-pc-windows-msvc",
        "--python-version", "3.12",
        "--generate-hashes", "--no-header", "--quiet",
    ]
    if args.upgrade:
        cmd.append("--upgrade")
    elif LOCK.exists():
        # Prefer the currently locked versions so only what is necessary changes.
        cmd += ["--output-file", str(LOCK)]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode
    body = result.stdout
    if not body.strip() and LOCK.exists():
        body = "".join(ln for ln in LOCK.read_text(encoding="utf-8").splitlines(keepends=True) if not ln.startswith("#"))
    LOCK.write_text(HEADER + body.lstrip("\n"), encoding="utf-8", newline="\n")
    print(f"Wrote {LOCK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
