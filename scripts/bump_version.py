"""Bump DriveSweep's version everywhere it appears, and turn the changelog's Unreleased section
into the new release.

    python scripts/bump_version.py 0.7.1
    python scripts/bump_version.py 0.7.1 --date 2026-12-01
    python scripts/bump_version.py --check        # only verify that every file agrees

The single source of truth is app/__init__.py. After bumping: commit, open a pull request,
merge it once CI is green, then tag the merge commit (for example v0.7.1) to publish.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/rauell1/drive-sweep"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _v(pattern: str) -> str:
    return pattern.replace("{V}", r"(?P<v>\d+\.\d+\.\d+)")


# (file, regex with a named group "v" capturing the version, template using {new})
LOCATIONS: list[tuple[str, str, str]] = [
    ("app/__init__.py", _v(r'__version__ = "{V}"'), '__version__ = "{new}"'),
    ("installer/DriveSweep.iss", _v(r'#define MyAppVersion "{V}"'), '#define MyAppVersion "{new}"'),
    ("app/ui/app.js", _v(r'  version: "{V}",'), '  version: "{new}",'),
    ("app/ui/index.html", _v(r'class="ver-chip">v{V}<'), 'class="ver-chip">v{new}<'),
    ("version_info.txt", _v(r"u'FileVersion', u'{V}\.0'"), "u'FileVersion', u'{new}.0'"),
    ("version_info.txt", _v(r"u'ProductVersion', u'{V}\.0'"), "u'ProductVersion', u'{new}.0'"),
    ("packaging/winget/rauell1.DriveSweep.yaml", _v(r"PackageVersion: {V}"), "PackageVersion: {new}"),
    ("packaging/winget/rauell1.DriveSweep.installer.yaml", _v(r"PackageVersion: {V}"), "PackageVersion: {new}"),
    ("packaging/winget/rauell1.DriveSweep.locale.en-US.yaml", _v(r"PackageVersion: {V}"), "PackageVersion: {new}"),
    ("README.md", _v(r"DriveSweep-Setup-{V}\.exe"), "DriveSweep-Setup-{new}.exe"),
]


def current_version() -> str:
    text = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__ = "(\d+\.\d+\.\d+)"', text)
    if not m:
        raise SystemExit("Could not read __version__ from app/__init__.py")
    return m.group(1)


def check_consistency(expected: str) -> list[str]:
    """Return a list of problems where a file does not carry the expected version."""
    problems: list[str] = []
    for rel, pattern, _tmpl in LOCATIONS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        found = [m.group("v") for m in re.finditer(pattern, text)]
        if not found:
            problems.append(f"{rel}: version pattern not found")
        elif any(v != expected for v in found):
            problems.append(f"{rel}: has {sorted(set(found))}, expected {expected}")
    vi = (ROOT / "version_info.txt").read_text(encoding="utf-8")
    tup = "(" + ", ".join(expected.split(".")) + ", 0)"
    for key in ("filevers", "prodvers"):
        if f"{key}={tup}" not in vi:
            problems.append(f"version_info.txt: {key} is not {tup}")
    inst = (ROOT / "packaging/winget/rauell1.DriveSweep.installer.yaml").read_text(encoding="utf-8")
    if f"/releases/download/v{expected}/DriveSweep-Setup-{expected}.exe" not in inst:
        problems.append("winget installer manifest: InstallerUrl does not match")
    loc = (ROOT / "packaging/winget/rauell1.DriveSweep.locale.en-US.yaml").read_text(encoding="utf-8")
    if f"/releases/tag/v{expected}" not in loc:
        problems.append("winget locale manifest: ReleaseNotesUrl does not match")
    return problems


def bump_files(old: str, new: str, date: str) -> None:
    for rel, pattern, tmpl in LOCATIONS:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        text = re.sub(pattern, tmpl.format(new=new), text)
        path.write_text(text, encoding="utf-8", newline="")
    vi_path = ROOT / "version_info.txt"
    vi = vi_path.read_text(encoding="utf-8")
    new_tup = "(" + ", ".join(new.split(".")) + ", 0)"
    vi = re.sub(r"(filevers|prodvers)=\(\d+, \d+, \d+, \d+\)", lambda m: f"{m.group(1)}={new_tup}", vi)
    vi_path.write_text(vi, encoding="utf-8", newline="")
    inst_path = ROOT / "packaging/winget/rauell1.DriveSweep.installer.yaml"
    inst = inst_path.read_text(encoding="utf-8")
    inst = re.sub(r"releases/download/v\d+\.\d+\.\d+/DriveSweep-Setup-\d+\.\d+\.\d+\.exe",
                  f"releases/download/v{new}/DriveSweep-Setup-{new}.exe", inst)
    inst = re.sub(r"(?m)^ReleaseDate: .*$", f"ReleaseDate: {date}", inst)
    inst_path.write_text(inst, encoding="utf-8", newline="")
    loc_path = ROOT / "packaging/winget/rauell1.DriveSweep.locale.en-US.yaml"
    loc = loc_path.read_text(encoding="utf-8")
    loc = re.sub(r"releases/tag/v\d+\.\d+\.\d+", f"releases/tag/v{new}", loc)
    loc_path.write_text(loc, encoding="utf-8", newline="")


def roll_changelog(old: str, new: str, date: str, allow_empty: bool) -> None:
    path = ROOT / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^## \[Unreleased\]\n(.*?)(?=^## )", text)
    if not m:
        raise SystemExit("CHANGELOG.md has no '## [Unreleased]' section followed by a release.")
    if not m.group(1).strip() and not allow_empty:
        raise SystemExit("The Unreleased section of CHANGELOG.md is empty. Describe the changes first, or pass --allow-empty.")
    text = text[: m.start()] + f"## [Unreleased]\n\n## [{new}] - {date}\n" + m.group(1) + text[m.end():]
    text = re.sub(r"(?m)^\[Unreleased\]: .*$",
                  f"[Unreleased]: {REPO_URL}/compare/v{new}...HEAD\n[{new}]: {REPO_URL}/compare/v{old}...v{new}", text, count=1)
    path.write_text(text, encoding="utf-8", newline="")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="new version, for example 0.7.1")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="release date, YYYY-MM-DD (default: today)")
    ap.add_argument("--allow-empty", action="store_true", help="allow an empty Unreleased changelog section")
    ap.add_argument("--check", action="store_true", help="only check that every file carries the same version")
    args = ap.parse_args()

    old = current_version()
    if args.check or not args.version:
        problems = check_consistency(old)
        for p in problems:
            print("MISMATCH", p)
        print("All version references agree:" if not problems else "Version references disagree.", old)
        return 1 if problems else 0

    new = args.version.lstrip("vV")
    if not SEMVER.match(new):
        raise SystemExit("Version must look like 1.2.3")
    if tuple(map(int, new.split("."))) <= tuple(map(int, old.split("."))):
        raise SystemExit(f"New version {new} must be greater than the current version {old}.")
    problems = check_consistency(old)
    if problems:
        print("Fix these before bumping:", *problems, sep="\n  ")
        return 1
    roll_changelog(old, new, args.date, args.allow_empty)
    bump_files(old, new, args.date)
    after = check_consistency(new)
    if after:
        print("Bump incomplete:", *after, sep="\n  ")
        return 1
    print(f"Bumped {old} -> {new}. Next: commit, open a pull request, merge when CI is green, then tag v{new}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
