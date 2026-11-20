"""Undo and scheduled cleanup against the real Windows Recycle Bin.

The other undo tests use a simulated Recycle Bin. These run only on Windows (every pull request
runs them on GitHub's Windows machines) and check the real thing: files are sent to the Recycle
Bin by the same code a cleanup uses, found again from Windows' own $I records, and restored.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows Recycle Bin")


def _make_folder(tmp_path: Path, files: int = 3) -> tuple[Path, dict[str, bytes]]:
    folder = tmp_path / f"DriveSweepUndoTest-{uuid.uuid4().hex[:8]}"
    folder.mkdir()
    contents = {}
    for i in range(files):
        data = os.urandom(64) + f"file {i}".encode()
        (folder / f"cache_{i}.tmp").write_bytes(data)
        contents[f"cache_{i}.tmp"] = data
    sub = folder / "sub"
    sub.mkdir()
    (sub / "nested.bin").write_bytes(b"nested")
    contents["sub/nested.bin"] = b"nested"
    return folder, contents


def _assert_restored(folder: Path, contents: dict[str, bytes]) -> None:
    for rel, data in contents.items():
        assert (folder / rel).read_bytes() == data, rel


def _cleanup_leftovers(folder: Path) -> None:
    """Remove anything the test left in the Recycle Bin, so runs do not pile up."""
    from app.recycle_restore import list_recycled

    for item in list_recycled():
        if os.path.normcase(item.original_path).startswith(os.path.normcase(str(folder))):
            for p in (item.data_path, item.info_path):
                try:
                    if p.is_dir():
                        import shutil

                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        p.unlink(missing_ok=True)
                except OSError:
                    pass


def test_real_recycle_bin_round_trip(tmp_path: Path):
    from send2trash import send2trash

    from app.recycle_restore import find_cleanup_items, restore_items

    folder, contents = _make_folder(tmp_path)
    try:
        start = datetime.now(timezone.utc)
        for name in list(contents):
            if "/" not in name:
                send2trash(str(folder / name))
        send2trash(str(folder / "sub"))
        finish = datetime.now(timezone.utc)
        assert not any((folder / n).exists() for n in contents)

        items = find_cleanup_items([str(folder)], start, finish)
        assert len(items) == 4, [i.original_path for i in items]
        res = restore_items(items)
        assert res["restored_count"] == 4, res
        _assert_restored(folder, contents)
    finally:
        _cleanup_leftovers(folder)


def test_real_cleanup_then_undo_through_the_api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    from app.api import DriveSweepAPI

    folder, contents = _make_folder(tmp_path, files=60)  # more than one Recycle Bin batch
    try:
        api = DriveSweepAPI()
        res = api.execute_cleanup([{"path": str(folder), "contents_only": True}], mode="recycle")
        assert res["deleted_count"] == 1 and not res["failed"], res
        assert folder.exists() and not any(folder.iterdir())

        cands = api.get_undo_candidates()
        assert cands["ok"] and len(cands["candidates"]) == 1, cands
        info = api.get_undo_candidate()
        assert info["ok"] and info["item_count"] == len([c for c in contents if "/" not in c]) + 1, info

        undo = api.undo_last_cleanup(True)
        assert undo["restored_count"] == info["item_count"] and not undo["failed"], undo
        _assert_restored(folder, contents)
        assert api.get_undo_candidate()["ok"] is False
    finally:
        _cleanup_leftovers(folder)


def test_short_8dot3_root_still_matches(tmp_path: Path):
    """A cleanup root written in short 8.3 form (as TEMP often is) still finds its items."""
    import ctypes

    from send2trash import send2trash

    from app.recycle_restore import find_cleanup_items

    folder, contents = _make_folder(tmp_path, files=1)
    buf = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(folder), buf, 1024) or buf.value == str(folder):
        pytest.skip("8.3 short names are disabled on this volume")
    short_root = buf.value
    try:
        start = datetime.now(timezone.utc)
        send2trash(str(folder / "cache_0.tmp"))
        items = find_cleanup_items([short_root], start, datetime.now(timezone.utc))
        assert len(items) == 1
    finally:
        _cleanup_leftovers(folder)


def test_scheduled_cleanup_is_real_and_undoable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    import app.auto_clean as ac
    from app.api import DriveSweepAPI

    folder, contents = _make_folder(tmp_path)
    try:
        item = {"path": str(folder), "risk_level": "safe", "default_checked": True, "excluded": False,
                "running_app": None, "is_custom": False, "is_docker_prune": False, "size_bytes": 1000,
                "contents_only": True}
        monkeypatch.setattr(ac, "scan_smart_presets", lambda exclusions=None: {"items": [item]})
        res = ac.run_scheduled_cleanup()
        assert res["cleaned"] and not any(folder.iterdir()), res
        time.sleep(0.5)
        undo = DriveSweepAPI().undo_last_cleanup(True)
        assert undo["restored_count"] >= 1, undo
        _assert_restored(folder, contents)
    finally:
        _cleanup_leftovers(folder)
