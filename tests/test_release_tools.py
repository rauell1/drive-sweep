"""Version bump and release note tooling."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bump_version = _load("bump_version")
release_notes = _load("release_notes")


def test_every_file_carries_the_same_version():
    assert bump_version.check_consistency(bump_version.current_version()) == []


def test_bump_updates_everything_and_rolls_changelog(tmp_path: Path, monkeypatch):
    for rel in {loc[0] for loc in bump_version.LOCATIONS} | {"CHANGELOG.md"}:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
    monkeypatch.setattr(bump_version, "ROOT", tmp_path)
    old = bump_version.current_version()
    major, minor, patch = map(int, old.split("."))
    new = f"{major}.{minor}.{patch + 1}"

    bump_version.roll_changelog(old, new, "2030-01-02", allow_empty=True)
    bump_version.bump_files(old, new, "2030-01-02")

    assert bump_version.check_consistency(new) == []
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{new}] - 2030-01-02" in changelog
    assert changelog.index("## [Unreleased]") < changelog.index(f"## [{new}]")
    assert f"compare/v{new}...HEAD" in changelog
    assert "ReleaseDate: 2030-01-02" in (tmp_path / "packaging/winget/rauell1.DriveSweep.installer.yaml").read_text(encoding="utf-8")


def test_release_notes_include_changelog_section_and_signing_line():
    version = bump_version.current_version()
    notes = release_notes.build_notes(version, "Signed by nobody yet.")
    assert release_notes.changelog_section(version)
    assert "## What's new" in notes
    assert "Signed by nobody yet." in notes
    assert "SHA256SUMS.txt" in notes
