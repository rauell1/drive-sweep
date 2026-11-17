"""Write the GitHub Release notes for a version: its CHANGELOG.md section plus the standard
verification, signing and warranty text.

    python scripts/release_notes.py --version 0.7.1 --signing-line "..." --out dist/RELEASE_NOTES.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "rauell1/drive-sweep"

INTRO = (
    "Windows disk analyzer and cache cleaner with Recycle Bin and Permanent cleanup modes, "
    "Light/Dark themes, optional Administrator mode, and local-only data storage."
)


def changelog_section(version: str, changelog: Path = ROOT / "CHANGELOG.md") -> str:
    text = changelog.read_text(encoding="utf-8")
    m = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |^\[[^\]]+\]: |\Z)", text)
    return m.group(1).strip() if m else ""


def build_notes(version: str, signing_line: str) -> str:
    section = changelog_section(version)
    parts = [INTRO, ""]
    if section:
        parts += ["## What's new", "", section, ""]
    parts += [
        "## Verify your download",
        "* Compare the file's SHA-256 with `SHA256SUMS.txt`.",
        f"* Check the build provenance: `gh attestation verify <file> --repo {REPO}`.",
        "* `DriveSweep-sbom.cdx.json` lists every bundled Python package (CycloneDX format).",
        "",
        "## Code signing",
        signing_line.strip(),
        "",
        'Provided "as is" under the MIT License, without warranty. Back up important files before cleaning.',
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", required=True)
    ap.add_argument("--signing-line", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    version = args.version.lstrip("vV")
    if not changelog_section(version):
        print(f"warning: CHANGELOG.md has no section for {version}; notes will not list changes", file=sys.stderr)
    Path(args.out).write_text(build_notes(version, args.signing_line), encoding="utf-8")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
