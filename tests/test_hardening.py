"""Security hardening tests: folder links, Always Keep enforcement, CSV injection, injection safe tools."""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

import pytest

from app import safety
from app.safety import delete_targets, find_link_in_path, is_link_entry


def _make_dir_link(link: Path, target: Path) -> None:
    """Create a directory junction on Windows (no admin needed) or a symlink elsewhere."""
    if os.name == "nt":
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip(f"Could not create junction: {proc.stderr or proc.stdout}")
    else:
        os.symlink(str(target), str(link), target_is_directory=True)


def _victim(tmp_path: Path) -> Path:
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "important.dat").write_bytes(b"precious" * 100)
    (victim / "sub").mkdir()
    (victim / "sub" / "nested.dat").write_bytes(b"nested")
    return victim


@pytest.mark.parametrize("mode", ["permanent", "recycle"])
def test_contents_only_through_link_is_blocked(tmp_path: Path, mode: str, monkeypatch):
    victim = _victim(tmp_path)
    cache = tmp_path / "AppCache"
    _make_dir_link(cache, victim)
    monkeypatch.setattr(safety, "send2trash", lambda p: (_ for _ in ()).throw(AssertionError(f"recycled {p}")))

    res = delete_targets([{"path": str(cache), "contents_only": True}], mode=mode)

    assert res.deleted_count == 0
    assert "folder link" in res.failed[0]["error"]
    assert (victim / "important.dat").exists()
    assert (victim / "sub" / "nested.dat").exists()


def test_target_below_link_ancestor_is_blocked(tmp_path: Path):
    victim = _victim(tmp_path)
    link = tmp_path / "redirect"
    _make_dir_link(link, victim)

    assert find_link_in_path(link / "sub") is not None
    res = delete_targets([{"path": str(link / "sub"), "contents_only": False}], mode="permanent")

    assert res.deleted_count == 0
    assert (victim / "sub" / "nested.dat").exists()


def test_deleting_link_itself_removes_only_the_link(tmp_path: Path):
    victim = _victim(tmp_path)
    link = tmp_path / "shortcut_dir"
    _make_dir_link(link, victim)
    assert is_link_entry(link)

    res = delete_targets([{"path": str(link), "contents_only": False}], mode="permanent")

    assert res.deleted_count == 1
    assert res.deleted[0].get("link_only") is True
    assert not os.path.lexists(str(link))
    assert (victim / "important.dat").exists()


def test_link_child_inside_cleaned_folder_is_unlinked_not_followed(tmp_path: Path):
    victim = _victim(tmp_path)
    cache = tmp_path / "RealCache"
    cache.mkdir()
    (cache / "junk.tmp").write_bytes(b"x" * 64)
    _make_dir_link(cache / "planted", victim)

    res = delete_targets([{"path": str(cache), "contents_only": True}], mode="permanent")

    assert res.deleted_count == 1
    assert not (cache / "junk.tmp").exists()
    assert not os.path.lexists(str(cache / "planted"))
    assert (victim / "important.dat").exists()
    assert (victim / "sub" / "nested.dat").exists()


def test_always_keep_is_enforced_by_backend(tmp_path: Path):
    keep_file = tmp_path / "keep.txt"
    keep_file.write_text("keep")
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "protected").mkdir()
    (folder / "protected" / "a.txt").write_text("a")
    (folder / "junk.tmp").write_text("junk")

    exclusions = [str(keep_file), str(folder / "protected")]

    res_file = delete_targets([{"path": str(keep_file), "contents_only": False}], mode="permanent", exclusions=exclusions)
    assert res_file.deleted_count == 0 and keep_file.exists()
    assert "Always Keep" in res_file.failed[0]["error"]

    res_parent = delete_targets([{"path": str(folder), "contents_only": False}], mode="permanent", exclusions=exclusions)
    assert res_parent.deleted_count == 0
    assert (folder / "protected" / "a.txt").exists()

    res_contents = delete_targets([{"path": str(folder), "contents_only": True}], mode="permanent", exclusions=exclusions)
    assert not (folder / "junk.tmp").exists()
    assert (folder / "protected" / "a.txt").exists()
    assert res_contents.deleted[0]["partial"] is True


def test_api_cleanup_passes_saved_exclusions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    from app.api import DriveSweepAPI
    from app.storage import add_exclusion

    target = tmp_path / "keepme"
    target.mkdir()
    (target / "f.txt").write_text("x")
    add_exclusion(str(target))

    api = DriveSweepAPI()
    res = api.execute_cleanup([{"path": str(target), "contents_only": False}], mode="permanent")

    assert res["deleted_count"] == 0
    assert (target / "f.txt").exists()


def test_contents_only_counts_freed_bytes_per_child(tmp_path: Path):
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "a.bin").write_bytes(b"1" * 300)
    (cache / "d").mkdir()
    (cache / "d" / "b.bin").write_bytes(b"2" * 200)

    res = delete_targets([{"path": str(cache), "contents_only": True}], mode="permanent")

    assert res.freed_bytes == 500
    assert cache.exists() and not any(cache.iterdir())


def test_csv_export_neutralizes_formulas(tmp_path: Path):
    from app.scanner import DriveScanner, csv_safe_cell

    assert csv_safe_cell("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert csv_safe_cell("@SUM(A1)") == "'@SUM(A1)"
    assert csv_safe_cell("+cmd") == "'+cmd"
    assert csv_safe_cell("normal.txt") == "normal.txt"
    assert csv_safe_cell(1234) == 1234

    root = tmp_path / "scanroot"
    evil_dir = root / "=1+2"
    evil_dir.mkdir(parents=True)
    (evil_dir / "x.bin").write_bytes(b"0" * 10)

    scanner = DriveScanner()
    scanner.start_scan(str(root))
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and scanner.get_status()["status"] == "scanning":
        time.sleep(0.02)
    out = tmp_path / "report.csv"
    scanner.export_scan_report(str(out), fmt="csv")
    with out.open(encoding="utf-8-sig", newline="") as fh:
        names = [row[1] for row in csv.reader(fh)]
    assert "'=1+2" in names
    assert "=1+2" not in names


def test_compact_virtual_disk_never_puts_path_in_command(tmp_path: Path, monkeypatch):
    import app.system_tools as st

    vhdx = tmp_path / "evil\u2019;calc;\u2019.vhdx"
    vhdx.write_bytes(b"VHDX" * 16)
    monkeypatch.setattr(st.sys, "platform", "win32")
    monkeypatch.setattr(st, "is_admin", lambda: True)
    monkeypatch.setattr(st, "secure_work_dir", lambda _n: tmp_path)
    monkeypatch.setattr(st, "_CREATE_NO_WINDOW", 0)
    calls: list[tuple[list[str], dict]] = []

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs.get("env") or {}))
        return _Proc()

    monkeypatch.setattr(st.subprocess, "run", fake_run)
    res = st.compact_virtual_disk(str(vhdx))

    assert res["ok"] is True
    ps_cmd, ps_env = next(c for c in calls if "powershell" in c[0][0].lower())
    assert all(str(vhdx) not in part for part in ps_cmd)
    assert "\u2019" not in " ".join(ps_cmd)
    assert ps_env["DS_VHD_PATH"] == str(vhdx.resolve()) or ps_env["DS_VHD_PATH"] == os.path.abspath(str(vhdx))


def test_compact_virtual_disk_rejects_linked_path(tmp_path: Path, monkeypatch):
    import app.system_tools as st

    real = tmp_path / "real"
    real.mkdir()
    (real / "disk.vhdx").write_bytes(b"VHDX")
    _make_dir_link(tmp_path / "lnk", real)
    monkeypatch.setattr(st, "is_admin", lambda: True)
    res = st.compact_virtual_disk(str(tmp_path / "lnk" / "disk.vhdx"))
    assert res["ok"] is False


def test_escape_html_covers_attribute_quotes():
    js = (Path(__file__).resolve().parent.parent / "app" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "'\"': \"&quot;\"" in js and "\"'\": \"&#39;\"" in js
    html = (Path(__file__).resolve().parent.parent / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html
    csp = html.split("Content-Security-Policy", 1)[1].split("/>", 1)[0]
    assert "object-src 'none'" in csp
    assert "script-src 'self' file: 'unsafe-eval';" in csp  # no 'unsafe-inline' for scripts


def test_update_checks_are_opt_in_and_disclaimer_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    from app.api import DriveSweepAPI

    api = DriveSweepAPI()
    info = api.get_app_info()
    assert info["auto_check_updates"] is False
    assert info["disclaimer_accepted"] is False
    api.accept_disclaimer(True)
    info2 = api.get_app_info()
    assert info2["disclaimer_accepted"] is True
    assert info2["auto_check_updates"] is True


def test_data_dir_override_ignored_when_frozen(tmp_path: Path, monkeypatch):
    import sys

    from app.storage import get_app_data_dir

    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "evil"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert "evil" not in str(get_app_data_dir())


def test_clear_logs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    from app.logger import clear_logs, get_log_path, get_logger, setup_logging

    setup_logging()
    get_logger().info("secret path C:\\Users\\me\\taxes.pdf")
    backup = Path(f"{get_log_path()}.1")
    backup.write_text("old")
    clear_logs()
    assert not backup.exists()
    assert "taxes.pdf" not in get_log_path().read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows profile layout")
def test_other_user_profiles_and_users_root_are_protected():
    home = Path.home()
    users = home.parent
    assert safety.is_os_protected_path(users)
    assert safety.is_os_protected_path(users / "Public" / "Documents")
    assert safety.is_os_protected_path(users / "SomeOtherAccount" / "AppData" / "Local" / "Temp")
    assert not safety.is_os_protected_path(home / "AppData" / "Local" / "Temp" / "x.tmp")
    assert safety.is_os_protected_path(os.environ.get("ProgramData", "C:\\ProgramData"))
    guard = safety.ScanGuard()
    other = str(users / "SomeOtherAccount")
    assert guard.check_dir(other, "someotheraccount")[0] is True
    assert guard.check_dir(str(users), users.name.lower())[0] is True
