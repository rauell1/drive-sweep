"""Tests for safety guards, long paths, deduplication, storage, scanner, and API."""

from __future__ import annotations

import os
import time
from pathlib import Path

import app.safety as safety
from app.api import DriveSweepAPI
from app.presets import scan_smart_presets
from app.safety import (
    ScanGuard,
    classify_path_risk,
    deduplicate_targets,
    delete_targets,
    format_bytes,
    is_os_protected_path,
    is_personal_guarded_path,
    to_os_path,
)
from app.scanner import DriveScanner, list_drives
from app.storage import (
    add_exclusion,
    append_history,
    clear_history,
    get_exclusions,
    get_history,
    get_theme,
    is_path_excluded,
    remove_exclusion,
    set_theme,
)


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"


def test_os_protection_guards():
    assert is_os_protected_path("C:\\")
    assert is_os_protected_path("D:\\")
    assert is_os_protected_path("C:\\Windows")
    assert is_os_protected_path("C:\\Windows\\System32")
    assert is_os_protected_path("C:\\Program Files")
    assert is_os_protected_path("D:\\$Recycle.Bin")
    assert is_os_protected_path("C:\\Windows\\Temp", allow_temp_contents=False)
    assert not is_os_protected_path("C:\\Windows\\Temp", allow_temp_contents=True)
    assert not is_os_protected_path("C:\\Windows\\Temp\\stale.tmp")


def test_personal_guarded_paths():
    home = Path.home()
    assert is_personal_guarded_path(home / "Downloads")
    assert is_personal_guarded_path(home / "Downloads" / "installer.exe")
    assert is_personal_guarded_path(home / "OneDrive" / "Docs")
    assert not is_personal_guarded_path(home / "AppData" / "Local" / "Temp")


def test_deduplicate_targets(tmp_path: Path):
    parent = tmp_path / "parent"
    child = parent / "nested" / "file.txt"
    other = tmp_path / "other.log"

    deduped = deduplicate_targets([
        {"path": str(child), "contents_only": False},
        {"path": str(parent), "contents_only": False},
        {"path": str(parent), "contents_only": False},
        {"path": str(other), "contents_only": False},
    ])
    paths = [d["path"] for d in deduped]
    assert len(paths) == 2
    assert str(parent) in paths
    assert str(other) in paths


def test_windows_long_path_deletion(tmp_path: Path):
    deep_dir = tmp_path / ("a" * 80) / ("b" * 80) / ("c" * 80)
    deep_file = deep_dir / ("deep_file_" + "x" * 30 + ".tmp")
    os.makedirs(to_os_path(deep_dir), exist_ok=True)
    with open(to_os_path(deep_file), "wb") as fh:
        fh.write(b"12345678")

    assert len(str(deep_file)) >= 240
    res = delete_targets([{"path": str(tmp_path / ("a" * 80)), "contents_only": False}], mode="permanent")
    assert res.deleted_count == 1
    assert res.freed_bytes == 8
    assert not os.path.exists(to_os_path(deep_file))


def test_exclusions_and_history_persistence(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))

    assert get_exclusions() == []
    ex1 = add_exclusion(str(tmp_path / "keep_me"))
    assert len(ex1) == 1
    assert is_path_excluded(str(tmp_path / "keep_me" / "sub.txt"))
    assert not is_path_excluded(str(tmp_path / "other.txt"))

    ex2 = remove_exclusion(str(tmp_path / "keep_me"))
    assert ex2 == []

    append_history({
        "mode": "recycle",
        "freed_bytes": 2048,
        "freed_human": "2.00 KB",
        "deleted_count": 1,
        "failed_count": 0,
        "items": [str(tmp_path / "old.tmp")],
    })
    hist = get_history()
    assert len(hist) == 1
    assert hist[0]["freed_human"] == "2.00 KB"

    clear_history()
    assert get_history() == []


def test_scanner_indexes_and_age_filters(tmp_path: Path):
    proj = tmp_path / "my-app"
    nm = proj / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (proj / "readme.md").write_bytes(b"hello" * 100)
    old_bundle = nm / "bundle.js"
    old_bundle.write_bytes(b"x" * 2048)
    (tmp_path / "big.log").write_bytes(b"z" * 4096)

    # Set bundle.js mtime to 120 days ago
    old_ts = time.time() - (120 * 86400)
    os.utime(old_bundle, (old_ts, old_ts))
    os.utime(nm, (old_ts, old_ts))
    os.utime(proj / "node_modules", (old_ts, old_ts))

    scanner = DriveScanner()
    scanner.start_scan(str(tmp_path))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = scanner.get_status()
        if st["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.05)

    st = scanner.get_status()
    assert st["status"] == "done"
    assert st["files_scanned"] == 3
    assert st["bytes_scanned"] == 500 + 2048 + 4096

    browse = scanner.browse_folder(str(tmp_path))
    assert browse["total_items"] == 2
    assert browse["items"][0]["name"] == "big.log"

    old_search = scanner.search_all_files(min_age_days=90)
    assert old_search["total_matches"] == 1
    assert old_search["items"][0]["name"] == "bundle.js"

    dev_old = scanner.get_dev_artifacts(min_age_days=90)
    assert len(dev_old) == 1
    assert dev_old[0]["name"] == "node_modules"
    assert dev_old[0]["age_days"] >= 119


def test_api_execute_cleanup_syncs_contents_only_and_logs_history(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "a.tmp").write_bytes(b"12345")
    (cache_dir / "b.tmp").write_bytes(b"67890")

    api = DriveSweepAPI()
    api.start_drive_scan(str(tmp_path))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and api.get_scan_status()["status"] == "scanning":
        time.sleep(0.05)

    res = api.execute_cleanup([{"path": str(cache_dir), "contents_only": True}], mode="permanent")
    assert res["deleted_count"] == 1
    assert res["freed_bytes"] == 10
    assert cache_dir.exists()
    assert api.get_scan_status()["bytes_scanned"] == 0
    assert len(api.get_history()) == 1


def test_recycle_mode_and_long_path_error(tmp_path: Path, monkeypatch):
    target = tmp_path / "sample.tmp"
    target.write_bytes(b"abc")
    recycled: list[str] = []

    def fake_send2trash(p: str) -> None:
        recycled.append(p)
        os.unlink(p)

    monkeypatch.setattr(safety, "send2trash", fake_send2trash)
    res = delete_targets([{"path": str(target), "contents_only": False}], mode="recycle")
    assert res.deleted_count == 1
    assert len(recycled) == 1
    assert not target.exists()


def test_list_drives_and_smart_scan_smoke(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    drives = list_drives()
    assert len(drives) >= 1
    smart = scan_smart_presets()
    assert "items" in smart
    for item in smart["items"]:
        assert not is_personal_guarded_path(item["path"])
        assert item["risk_level"] in ("safe", "caution")


def test_risk_classification_theme_and_analytics(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))

    assert get_theme() == "dark"
    set_theme("light")
    assert get_theme() == "light"

    assert classify_path_risk("C:\\Windows\\System32")["risk_level"] == "critical"
    assert classify_path_risk(Path.home() / "Downloads" / "setup.exe")["risk_level"] == "caution"
    assert classify_path_risk(tmp_path / "app.db")["risk_level"] == "caution"
    assert classify_path_risk(tmp_path / "node_modules", is_dir=True, age_days=5, is_dev_bloat=True)["risk_level"] == "caution"
    assert classify_path_risk(tmp_path / "cache.tmp")["risk_level"] == "safe"

    scan_root = tmp_path / "scan_target"
    sub = scan_root / "logs"
    sub.mkdir(parents=True)
    (sub / "app.log").write_bytes(b"a" * 1000)
    (scan_root / "archive.zip").write_bytes(b"b" * 2000)

    api = DriveSweepAPI()
    api.start_drive_scan(str(scan_root))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and api.get_scan_status()["status"] == "scanning":
        time.sleep(0.05)

    analytics = api.get_drive_analytics()
    assert analytics["total_bytes"] == 3000
    assert len(analytics["top_folders"]) == 1
    assert len(analytics["by_category"]) >= 2
    assert len(analytics["by_age"]) == 4
    assert analytics["risk_summary"]["safe"]["size_bytes"] == 3000


def test_scan_guard_parity_and_drive_scan_cache(tmp_path: Path):
    guard = ScanGuard()
    home = Path.home()

    samples = [
        ("C:\\Windows", "windows", False, False),
        ("C:\\Windows\\System32", "system32", True, False),
        ("C:\\Windows\\Temp", "temp", True, False),
        ("C:\\Windows\\Temp\\cache_dir", "cache_dir", True, False),
        (str(home / "Downloads"), "downloads", False, False),
        (str(home / "Downloads" / "Sub"), "sub", False, True),
        ("D:\\$Recycle.Bin", "$recycle.bin", False, False),
        (str(tmp_path / "work"), "work", False, False),
    ]
    for path_str, name_l, p_prot, p_pers in samples:
        g_prot, g_pers = guard.check_dir(path_str, name_l, p_prot, p_pers)
        assert g_prot == is_os_protected_path(path_str), path_str
        assert g_pers == is_personal_guarded_path(path_str), path_str

    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "a.bin").write_bytes(b"1" * 100)
    (root_b / "b.bin").write_bytes(b"2" * 200)

    scanner = DriveScanner()
    for target in (root_a, root_b):
        scanner.start_scan(str(target))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and scanner.get_status()["status"] == "scanning":
            time.sleep(0.02)
        assert scanner.get_status()["status"] == "done"

    # Switching back to root_a without force returns cached index immediately
    st_cached = scanner.start_scan(str(root_a), force=False)
    assert st_cached["status"] == "done"
    assert st_cached["cached"] is True
    assert st_cached["bytes_scanned"] == 100

    # Force rescan picks up newly added file
    (root_a / "a2.bin").write_bytes(b"3" * 50)
    scanner.start_scan(str(root_a), force=True)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and scanner.get_status()["status"] == "scanning":
        time.sleep(0.02)
    st_fresh = scanner.get_status()
    assert st_fresh["status"] == "done"
    assert st_fresh["cached"] is False
    assert st_fresh["bytes_scanned"] == 150


def test_ensure_admin_or_relaunch(monkeypatch):
    import sys
    import main as entry_main

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("DRIVESWEEP_NO_ELEVATE", raising=False)

    # Bypass flags allow running without UAC prompt (for tests/debugging)
    assert entry_main.ensure_admin_or_relaunch(["--no-elevate"]) is True

    # Already Administrator -> continues immediately
    monkeypatch.setattr(entry_main, "is_admin", lambda: True)
    assert entry_main.ensure_admin_or_relaunch([]) is True

    # Standard user -> attempts UAC relaunch and returns False so parent exits cleanly
    monkeypatch.setattr(entry_main, "is_admin", lambda: False)
    monkeypatch.setattr(entry_main, "relaunch_as_admin", lambda: {"ok": True, "launching": True})
    assert entry_main.ensure_admin_or_relaunch([]) is False

    # If user declines UAC, returns True cleanly instead of looping infinitely
    monkeypatch.setattr(entry_main, "relaunch_as_admin", lambda: {"ok": False, "error": "cancelled"})
    assert entry_main.ensure_admin_or_relaunch([]) is True
