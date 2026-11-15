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


def test_updater_semver_sha256_and_url_verification(tmp_path: Path, monkeypatch):
    import hashlib
    import io
    import app.updater as updater

    assert updater.is_newer_version("v0.2.1", "0.2.0") is True
    assert updater.is_newer_version("v0.2.0", "0.2.0") is False
    assert updater.is_newer_version("v0.1.9", "0.2.0") is False

    assert updater.verify_https_github_url("https://github.com/rauell1/drive-sweep/releases/download/v0.2.1/DriveSweep-Setup-0.2.1.exe") is True
    assert updater.verify_https_github_url("https://objects.githubusercontent.com/abc/DriveSweep.exe") is True
    assert updater.verify_https_github_url("http://github.com/rauell1/drive-sweep/releases") is False
    assert updater.verify_https_github_url("https://evil.example.com/DriveSweep.exe") is False

    assets = [
        {"name": "DriveSweep.exe", "browser_download_url": "https://github.com/a/DriveSweep.exe"},
        {"name": "DriveSweep-Setup-0.2.1.exe", "browser_download_url": "https://github.com/a/DriveSweep-Setup-0.2.1.exe"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://github.com/a/SHA256SUMS.txt"},
    ]
    assert updater.pick_release_asset(assets, "setup")["name"] == "DriveSweep-Setup-0.2.1.exe"
    assert updater.pick_release_asset(assets, "onedir_zip")["name"] == "DriveSweep-Setup-0.2.1.exe"
    assert updater.pick_release_asset(assets, "onefile_exe")["name"] == "DriveSweep-Setup-0.2.1.exe"
    assert updater.pick_release_asset(assets, "onefile_exe", prefer_setup=False)["name"] == "DriveSweep.exe"

    payload = b"MZ-mock-installer-binary"
    good_hash = hashlib.sha256(payload).hexdigest()
    bad_hash = "0" * 64
    sums_good = f"{good_hash}  DriveSweep-Setup-0.2.1.exe\n".encode("utf-8")
    sums_bad = f"{bad_hash}  DriveSweep-Setup-0.2.1.exe\n".encode("utf-8")

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            self.close()

    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def fake_urlopen_good(req, timeout=15.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        return FakeResp(sums_good if "SHA256SUMS" in url else payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen_good)
    ok_res = updater.download_and_verify_update(
        "https://github.com/rauell1/drive-sweep/releases/download/v0.2.1/DriveSweep-Setup-0.2.1.exe",
        "DriveSweep-Setup-0.2.1.exe",
        "https://github.com/rauell1/drive-sweep/releases/download/v0.2.1/SHA256SUMS.txt",
    )
    assert ok_res["ok"] is True
    assert ok_res["sha256"] == good_hash
    assert Path(ok_res["file_path"]).exists()

    def fake_urlopen_bad(req, timeout=15.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        return FakeResp(sums_bad if "SHA256SUMS" in url else payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen_bad)
    bad_res = updater.download_and_verify_update(
        "https://github.com/rauell1/drive-sweep/releases/download/v0.2.1/DriveSweep-Setup-0.2.1.exe",
        "DriveSweep-Setup-0.2.1.exe",
        "https://github.com/rauell1/drive-sweep/releases/download/v0.2.1/SHA256SUMS.txt",
    )
    assert bad_res["ok"] is False
    assert "verification failed" in bad_res["error"].lower()


def test_universal_windows_cache_safety_and_dynamic_discovery(tmp_path: Path):
    import app.presets as presets

    assert safety.is_os_protected_path(r"C:\Windows\SoftwareDistribution\Download", allow_temp_contents=True) is False
    assert safety.is_os_protected_path(r"C:\Windows\SoftwareDistribution\Download", allow_temp_contents=False) is True
    assert safety.is_os_protected_path(r"C:\Windows\System32", allow_temp_contents=True) is True

    local_app = tmp_path / "Local"
    roaming_app = tmp_path / "Roaming"
    (local_app / "SampleApp" / "Cache").mkdir(parents=True)
    (local_app / "SampleApp" / "Cache" / "blob.bin").write_bytes(b"a" * 2048)
    (local_app / "OtherApp-updater" / "pending").mkdir(parents=True)
    (local_app / "OtherApp-updater" / "pending" / "setup.exe").write_bytes(b"b" * 1024)
    # Protected / system vendor folders must never be auto-discovered dynamically
    (local_app / "Microsoft" / "Cache").mkdir(parents=True)
    (local_app / "Microsoft" / "Cache" / "keep.bin").write_bytes(b"c" * 2048)

    found: list[tuple[str, str, Path]] = []

    def fake_add(cid: str, group: str, _label: str, path: Path, *_args, **_kwargs):
        found.append((cid, group, path))

    presets._discover_dynamic_app_caches(local_app, roaming_app, fake_add)
    paths_str = [str(p) for _, _, p in found]
    groups = {g for _, g, _ in found}

    assert str(local_app / "SampleApp" / "Cache") in paths_str
    assert str(local_app / "OtherApp-updater") in paths_str
    assert str(local_app / "Microsoft" / "Cache") not in paths_str
    assert "Desktop Apps" in groups

    from app.api import DriveSweepAPI

    api = DriveSweepAPI()
    refreshed = api.refresh_drives()
    assert isinstance(refreshed, list) and len(refreshed) >= 1
    assert {"path", "name", "free_human", "total_human", "used_percent"} <= set(refreshed[0].keys())


def test_sanitized_subprocess_env_strips_pyi_markers(tmp_path: Path, monkeypatch):
    import sys
    import app.updater as updater

    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", r"C:\old\DriveSweep.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", r"C:\temp\_MEI123")
    monkeypatch.setenv("_PYI_SPLASH_IPC", "999")
    monkeypatch.setenv("_MEIPASS2", r"C:\temp\_MEI123")
    monkeypatch.setenv("DRIVESWEEP_KEEP_ENV", "yes")

    clean = safety.sanitized_subprocess_env({"EXTRA_KEY": "1"})
    assert clean.get("DRIVESWEEP_KEEP_ENV") == "yes"
    assert clean.get("EXTRA_KEY") == "1"
    for bad_key in (
        "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_ARCHIVE_FILE",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_SPLASH_IPC",
        "_MEIPASS2",
    ):
        assert bad_key not in clean

    fake_exe = tmp_path / "DriveSweep.exe"
    fake_exe.write_bytes(b"MZ")
    captured: dict = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        class DummyProc:
            pass
        return DummyProc()

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    res = updater.launch_downloaded_update(str(fake_exe), install_kind="onefile_exe")
    assert res["ok"] is True
    assert res["mode"] == "portable_swap"
    assert "_PYI_PARENT_PROCESS_LEVEL" not in captured["env"]
    assert "_MEIPASS2" not in captured["env"]

    setup_exe = tmp_path / "DriveSweep-Setup-0.3.3.exe"
    setup_exe.write_bytes(b"MZ")
    setup_calls: list[tuple[str, str]] = []

    def fake_shell_setup(exe_path: Path, args_str: str):
        setup_calls.append((str(exe_path), args_str))
        return True, 42

    monkeypatch.setattr(updater, "_launch_windows_setup", fake_shell_setup)
    setup_res = updater.launch_downloaded_update(str(setup_exe), install_kind="setup")
    assert setup_res["ok"] is True
    assert setup_res["mode"] == "setup"
    assert len(setup_calls) == 1
    assert setup_calls[0][0] == str(setup_exe.resolve())
    assert "/AUTOSTART=1" in setup_calls[0][1]
    assert "/FORCECLOSEAPPLICATIONS" in setup_calls[0][1]
    assert "/NORESTARTAPPLICATIONS" in setup_calls[0][1]
    assert "/SILENT" in setup_calls[0][1]

    # If user cancels UAC (rc <= 32), updater reports cleanly without exiting
    monkeypatch.setattr(updater, "_launch_windows_setup", lambda *_args: (False, 5))
    denied_res = updater.launch_downloaded_update(str(setup_exe), install_kind="setup")
    assert denied_res["ok"] is False


def test_async_cleanup_progress_and_cancel(tmp_path: Path, monkeypatch):
    import threading
    import time
    from app.api import DriveSweepAPI

    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    api = DriveSweepAPI()

    f1 = tmp_path / "one.tmp"
    f2 = tmp_path / "two.tmp"
    f1.write_bytes(b"x" * 2048)
    f2.write_bytes(b"y" * 2048)

    api.start_cleanup(
        [
            {"path": str(f1), "contents_only": False},
            {"path": str(f2), "contents_only": False},
        ],
        mode="permanent",
    )
    deadline = time.time() + 5.0
    st = api.get_cleanup_status()
    while st["status"] == "running" and time.time() < deadline:
        time.sleep(0.03)
        st = api.get_cleanup_status()

    assert st["status"] == "completed"
    assert st["result"]["deleted_count"] == 2
    assert not f1.exists()
    assert not f2.exists()

    hist = api.get_history(10)
    assert len(hist) >= 1
    assert hist[0]["action"] == "Cleanup"
    assert hist[0]["deleted_count"] == 2

    # Windows Tools cleanups (Empty Recycle Bin + WinSxS DISM) must also record to Cleanup Log
    import app.api as api_mod

    monkeypatch.setattr(
        api_mod,
        "empty_recycle_bin",
        lambda root_path=None: {"ok": True, "already_empty": False, "freed_bytes": 5120, "freed_human": "5.00 KB", "items_removed": 3},
    )
    rb_res = api.empty_recycle_bin()
    assert rb_res["ok"] is True
    assert rb_res["history_count"] >= 2

    monkeypatch.setattr(api_mod, "run_winsxs_cleanup", lambda: {"ok": True})
    wx_res = api.run_winsxs_cleanup()
    assert wx_res["ok"] is True
    assert wx_res["history_count"] >= 3
    actions = [h.get("action") for h in api.get_history(10)]
    assert "WinSxS Cleanup (DISM)" in actions
    assert "Empty Recycle Bin" in actions

    # Pre-cancelled event stops delete_targets before deleting queued paths
    f3 = tmp_path / "three.tmp"
    f3.write_bytes(b"z" * 1024)
    ev = threading.Event()
    ev.set()
    cancel_res = safety.delete_targets(
        [{"path": str(f3), "contents_only": False}],
        mode="permanent",
        cancel_event=ev,
    )
    assert cancel_res.cancelled is True
    assert cancel_res.deleted_count == 0
    assert f3.exists()


def test_async_update_install_progress_and_stale_cleanup(tmp_path: Path, monkeypatch):
    import hashlib
    import io
    import tempfile
    import time
    import app.api as api_mod
    import app.updater as updater

    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    upd_dir = tmp_path / "DriveSweep-Updates"
    upd_dir.mkdir(parents=True)
    stale = upd_dir / "DriveSweep-Setup-0.2.0.exe"
    stale.write_bytes(b"old")
    updater.cleanup_stale_updates()
    assert not stale.exists()

    payload = b"MZ-setup-package-bytes" * 200
    good_hash = hashlib.sha256(payload).hexdigest()
    sums = f"{good_hash}  DriveSweep-Setup-0.2.7.exe\n".encode("utf-8")

    class FakeResp(io.BytesIO):
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(req, timeout=15.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        r = FakeResp(sums if "SHA256SUMS" in url else payload)
        r.headers = {"Content-Length": str(len(sums if "SHA256SUMS" in url else payload))}
        return r

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    launched: list[str] = []
    monkeypatch.setattr(
        api_mod,
        "launch_downloaded_update",
        lambda fp, install_kind=None: (launched.append(fp), {"ok": True, "should_exit": True, "mode": "setup"})[1],
    )

    api = api_mod.DriveSweepAPI()
    api.start_update_install(
        "https://github.com/rauell1/drive-sweep/releases/download/v0.2.7/DriveSweep-Setup-0.2.7.exe",
        "DriveSweep-Setup-0.2.7.exe",
        "https://github.com/rauell1/drive-sweep/releases/download/v0.2.7/SHA256SUMS.txt",
        expected_size=len(payload),
    )

    deadline = time.time() + 5.0
    st = api.get_update_status()
    while st["status"] in ("downloading", "verifying") and time.time() < deadline:
        time.sleep(0.02)
        st = api.get_update_status()

    assert st["status"] == "launching"
    assert st["mode"] == "setup"
    assert st["sha256"] == good_hash
    assert len(launched) == 1
    assert launched[0].endswith("DriveSweep-Setup-0.2.7.exe")
    assert Path(launched[0]).exists()


def test_update_check_web_fallback_on_rate_limit(monkeypatch):
    import io
    import urllib.error
    import app.updater as updater

    class FakeWebResp(io.BytesIO):
        def geturl(self):
            return "https://github.com/rauell1/drive-sweep/releases/tag/v0.9.9"
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            self.close()

    def fake_urlopen(req, timeout=8.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "api.github.com" in url:
            raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, None)
        return FakeWebResp(b'{"tag_name": "v0.9.9"}')

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    res = updater.check_for_updates(current_version="0.2.8")
    assert res["ok"] is True
    assert res["update_available"] is True
    assert res["latest_version"] == "0.9.9"
    assert res["asset_name"] == "DriveSweep-Setup-0.9.9.exe"
    assert res["sha256_url"].endswith("/v0.9.9/SHA256SUMS.txt")
