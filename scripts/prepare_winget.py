"""Build a winget-pkgs submission folder for a published DriveSweep release.

Usage (from the repository root):

    python scripts/prepare_winget.py --version 0.7.0

It reads the templates in packaging/winget/, fills in the version, release date and the
installer's SHA-256 (taken from the release's SHA256SUMS.txt on GitHub, or given with
--sha256), and writes:

    dist/winget/manifests/r/rauell1/DriveSweep/<version>/
        rauell1.DriveSweep.yaml
        rauell1.DriveSweep.installer.yaml
        rauell1.DriveSweep.locale.en-US.yaml

With --schemas pointing at a checkout of microsoft/winget-cli/schemas/JSON/manifests, the
files are also validated against the official JSON schemas (needs PyYAML and jsonschema).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "packaging" / "winget"
PACKAGE_ID = "rauell1.DriveSweep"
REPO = "rauell1/drive-sweep"
FILES = {
    "version": f"{PACKAGE_ID}.yaml",
    "installer": f"{PACKAGE_ID}.installer.yaml",
    "defaultLocale": f"{PACKAGE_ID}.locale.en-US.yaml",
}
SCHEMA_NAMES = {
    "version": "manifest.version.{v}.json",
    "installer": "manifest.installer.{v}.json",
    "defaultLocale": "manifest.defaultLocale.{v}.json",
}


def fetch_installer_sha256(version: str) -> str:
    url = f"https://github.com/{REPO}/releases/download/v{version}/SHA256SUMS.txt"
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8-sig")
    name = f"DriveSweep-Setup-{version}.exe".lower()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*").lower() == name:
            return parts[0]
    raise SystemExit(f"{name} not found in {url}")


def fetch_release_date(version: str) -> str:
    url = f"https://api.github.com/repos/{REPO}/releases/tags/v{version}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "DriveSweep-winget-prep"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        published = json.load(resp).get("published_at") or ""
    return published[:10] or dt.date.today().isoformat()


def render(text: str, version: str, sha256: str, release_date: str) -> str:
    # Drop template only comments, keep the yaml-language-server schema line.
    lines = [ln for ln in text.splitlines() if not (ln.startswith("#") and "schema=" not in ln)]
    out = "\n".join(lines).strip() + "\n"
    out = re.sub(r"(?m)^PackageVersion:.*$", f"PackageVersion: {version}", out)
    out = re.sub(r"(?m)^ReleaseDate:.*$", f"ReleaseDate: {release_date}", out)
    out = re.sub(r"releases/download/v[0-9][^/]*/DriveSweep-Setup-[^/\s]+\.exe",
                 f"releases/download/v{version}/DriveSweep-Setup-{version}.exe", out)
    out = re.sub(r"releases/tag/v[0-9][^\s]*", f"releases/tag/v{version}", out)
    out = re.sub(r"(InstallerSha256:\s*)\S+", lambda m: m.group(1) + sha256.upper(), out)
    return out


def validate(folder: Path, schemas: Path) -> None:
    import jsonschema
    import yaml

    for kind, fname in FILES.items():
        data = yaml.safe_load((folder / fname).read_text(encoding="utf-8"))
        version = str(data["ManifestVersion"])
        schema_path = schemas / f"v{version}" / SCHEMA_NAMES[kind].format(v=version)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # Dates are compared as strings by winget; PyYAML turns them into date objects.
        if "ReleaseDate" in data:
            data["ReleaseDate"] = str(data["ReleaseDate"])
        jsonschema.validate(data, schema)
        print(f"valid  {fname}  (schema {version})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True, help="Released version, for example 0.7.0")
    ap.add_argument("--sha256", help="Installer SHA-256 (default: read SHA256SUMS.txt from the release)")
    ap.add_argument("--release-date", help="YYYY-MM-DD (default: the release's publish date)")
    ap.add_argument("--out", default=str(ROOT / "dist" / "winget"))
    ap.add_argument("--schemas", help="Path to winget-cli schemas/JSON/manifests to validate against")
    args = ap.parse_args()

    version = args.version.lstrip("vV")
    sha256 = (args.sha256 or fetch_installer_sha256(version)).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise SystemExit("Invalid SHA-256")
    release_date = args.release_date or fetch_release_date(version)

    folder = Path(args.out) / "manifests" / PACKAGE_ID[0].lower() / "rauell1" / "DriveSweep" / version
    folder.mkdir(parents=True, exist_ok=True)
    for fname in FILES.values():
        text = (TEMPLATES / fname).read_text(encoding="utf-8")
        (folder / fname).write_text(render(text, version, sha256, release_date), encoding="utf-8", newline="\n")
        print(f"wrote  {folder / fname}")
    if args.schemas:
        validate(folder, Path(args.schemas))
    print(f"\nSubmission folder ready: {folder}")


if __name__ == "__main__":
    sys.exit(main())
