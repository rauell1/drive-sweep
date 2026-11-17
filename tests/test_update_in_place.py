"""In place updates: portable DriveSweep.exe and the zip folder version replace themselves."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import app.updater as updater

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="Runs the real PowerShell swap scripts")


class _FakeResp(io.BytesIO):
    headers: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _serve(monkeypatch, files: dict[str, bytes]) -> None:
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in files.items()).encode()

    def fake_urlopen(req, timeout=15.0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("SHA256SUMS.txt"):
            return _FakeResp(sums)
        return _FakeResp(files[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)


def _url(name: str, tag: str = "v99.0.0") -> str:
    return f"https://github.com/rauell1/drive-sweep/releases/download/{tag}/{name}"


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_check_result_describes_in_place_method(monkeypatch, tmp_path: Path):
    assets = [
        {"name": "DriveSweep.exe", "browser_download_url": _url("DriveSweep.exe"), "size": 10},
        {"name": "DriveSweep-win64.zip", "browser_download_url": _url("DriveSweep-win64.zip"), "size": 20},
        {"name": "DriveSweep-Setup-99.0.0.exe", "browser_download_url": _url("DriveSweep-Setup-99.0.0.exe"), "size": 30},
        {"name": "SHA256SUMS.txt", "browser_download_url": _url("SHA256SUMS.txt")},
    ]
    import json

    payload = json.dumps({"tag_name": "v99.0.0", "assets": assets}).encode()
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout=8.0: _FakeResp(payload))
    monkeypatch.setattr(updater, "app_install_dir", lambda: tmp_path)

    for kind, name, method in (
        ("onefile_exe", "DriveSweep.exe", "replace_exe"),
        ("onedir_zip", "DriveSweep-win64.zip", "replace_folder"),
        ("setup", "DriveSweep-Setup-99.0.0.exe", "setup"),
    ):
        monkeypatch.setattr(updater, "detect_install_kind", lambda k=kind: k)
        res = updater.check_for_updates(current_version="0.7.0")
        assert res["asset_name"] == name
        assert res["update_method"] == method
        assert bool(res["update_folder"]) == (method != "setup")


def test_portable_exe_is_downloaded_into_its_own_folder(monkeypatch, tmp_path: Path):
    new_exe = b"MZ-new-portable-build" * 50
    _serve(monkeypatch, {"DriveSweep.exe": new_exe})
    monkeypatch.setattr(updater, "app_install_dir", lambda: tmp_path)

    res = updater.download_and_verify_update(_url("DriveSweep.exe"), "DriveSweep.exe", _url("SHA256SUMS.txt"))

    assert res["ok"] is True, res
    assert res["update_method"] == "replace_exe"
    assert Path(res["file_path"]) == tmp_path / "DriveSweep.exe.new"
    assert Path(res["file_path"]).read_bytes() == new_exe


def test_zip_is_downloaded_into_its_own_folder(monkeypatch, tmp_path: Path):
    data = _zip_bytes({"DriveSweep.exe": b"MZ", "_internal/x.pyd": b"1"})
    _serve(monkeypatch, {"DriveSweep-win64.zip": data})
    monkeypatch.setattr(updater, "app_install_dir", lambda: tmp_path)

    res = updater.download_and_verify_update(_url("DriveSweep-win64.zip"), "DriveSweep-win64.zip", _url("SHA256SUMS.txt"))

    assert res["ok"] is True, res
    assert res["update_method"] == "replace_folder"
    assert Path(res["file_path"]).parent == tmp_path


def test_read_only_folder_reports_clear_error(monkeypatch, tmp_path: Path):
    _serve(monkeypatch, {"DriveSweep.exe": b"MZ"})
    monkeypatch.setattr(updater, "app_install_dir", lambda: tmp_path)
    monkeypatch.setattr(updater, "folder_is_writable", lambda _d: False)

    res = updater.download_and_verify_update(_url("DriveSweep.exe"), "DriveSweep.exe", _url("SHA256SUMS.txt"))

    assert res["ok"] is False
    assert "cannot write to its folder" in res["error"]


def test_extract_update_zip_rejects_unsafe_archives(tmp_path: Path):
    good = tmp_path / "good.zip"
    good.write_bytes(_zip_bytes({"DriveSweep.exe": b"MZ", "_internal/lib.dll": b"x"}))
    ok = updater.extract_update_zip(good, tmp_path / "stage_ok")
    assert ok["ok"] is True
    assert (tmp_path / "stage_ok" / "_internal" / "lib.dll").exists()

    slip = tmp_path / "slip.zip"
    slip.write_bytes(_zip_bytes({"DriveSweep.exe": b"MZ", "../../evil.txt": b"x"}))
    bad = updater.extract_update_zip(slip, tmp_path / "stage_slip")
    assert bad["ok"] is False and "Unsafe path" in bad["error"]
    assert not (tmp_path / "evil.txt").exists()

    no_exe = tmp_path / "noexe.zip"
    no_exe.write_bytes(_zip_bytes({"readme.txt": b"x"}))
    assert updater.extract_update_zip(no_exe, tmp_path / "stage_noexe")["ok"] is False


def test_launch_routes_to_exe_and_folder_swaps(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "_lock_file_against_writes", lambda _p: 1)
    monkeypatch.setattr(updater, "_release_file_lock", lambda _h: None)
    checked: list[str] = []
    monkeypatch.setattr(
        updater,
        "get_authenticode_info",
        lambda p: (checked.append(str(p)), {"status": "NotSigned", "subject": "", "thumbprint": ""})[1],
    )
    spawned: list[dict] = []
    monkeypatch.setattr(updater, "_spawn_hidden_powershell", lambda script, env, cwd=None: spawned.append(env))
    monkeypatch.setattr(updater, "app_install_dir", lambda: tmp_path)

    new_exe = tmp_path / "DriveSweep.exe.new"
    new_exe.write_bytes(b"MZ-new")
    sha = hashlib.sha256(b"MZ-new").hexdigest()
    res = updater.launch_downloaded_update(str(new_exe), install_kind="onefile_exe", expected_sha256=sha)
    assert res["ok"] is True and res["mode"] == "portable_swap"
    assert spawned[-1]["DS_NEW_EXE"] == str(new_exe.resolve())
    assert spawned[-1]["DS_SHA256"] == sha

    zip_file = tmp_path / "DriveSweep-win64.zip.download"
    zip_file.write_bytes(_zip_bytes({"DriveSweep.exe": b"MZ", "_internal/a.dll": b"1"}))
    res_zip = updater.launch_downloaded_update(str(zip_file), install_kind="onedir_zip")
    assert res_zip["ok"] is True and res_zip["mode"] == "folder_swap"
    assert (tmp_path / updater.UPDATE_STAGING_DIRNAME / "DriveSweep.exe").exists()
    # The signature is checked on the unpacked DriveSweep.exe, not on the zip itself
    assert checked[-1].endswith(os.path.join(updater.UPDATE_STAGING_DIRNAME, "DriveSweep.exe"))


def test_cleanup_removes_in_place_leftovers(tmp_path: Path):
    (tmp_path / "DriveSweep.exe").write_bytes(b"MZ")
    (tmp_path / "DriveSweep.exe.old").write_bytes(b"old")
    (tmp_path / "DriveSweep.exe.new").write_bytes(b"new")
    (tmp_path / updater.UPDATE_BACKUP_DIRNAME / "_internal").mkdir(parents=True)
    (tmp_path / updater.UPDATE_STAGING_DIRNAME).mkdir()
    (tmp_path / "DriveSweep-win64.zip.download").write_bytes(b"zip")

    updater.cleanup_in_place_update_leftovers(tmp_path, "DriveSweep.exe")

    assert (tmp_path / "DriveSweep.exe").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["DriveSweep.exe"]


def _run_ps(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    # Same environment the app gives the hidden swap step (inherited PSModulePath removed)
    full_env = updater.windows_powershell_env(env)
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _sys_exe(name: str) -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / name


@WINDOWS_ONLY
def test_real_exe_swap_script_replaces_and_keeps_backup(tmp_path: Path):
    old = tmp_path / "DriveSweep.exe"
    new = tmp_path / "DriveSweep.exe.new"
    # Two small console tools that exit immediately stand in for the old and new builds.
    shutil.copy2(_sys_exe("hostname.exe"), old)
    shutil.copy2(_sys_exe("whoami.exe"), new)
    new_bytes = new.read_bytes()
    old_bytes = old.read_bytes()

    proc = _run_ps(updater._EXE_SWAP_SCRIPT, {
        "DS_OLD_EXE": str(old),
        "DS_NEW_EXE": str(new),
        "DS_SHA256": hashlib.sha256(new_bytes).hexdigest(),
        "DS_WAIT_PIDS": "",
    })

    assert proc.returncode == 0, proc.stderr
    assert old.read_bytes() == new_bytes
    assert (tmp_path / "DriveSweep.exe.old").read_bytes() == old_bytes
    assert not new.exists()


@WINDOWS_ONLY
def test_real_exe_swap_script_refuses_tampered_file(tmp_path: Path):
    old = tmp_path / "DriveSweep.exe"
    new = tmp_path / "DriveSweep.exe.new"
    shutil.copy2(_sys_exe("hostname.exe"), old)
    shutil.copy2(_sys_exe("whoami.exe"), new)
    old_bytes = old.read_bytes()

    _run_ps(updater._EXE_SWAP_SCRIPT, {
        "DS_OLD_EXE": str(old),
        "DS_NEW_EXE": str(new),
        "DS_SHA256": "0" * 64,
        "DS_WAIT_PIDS": "",
    })

    assert old.read_bytes() == old_bytes
    assert not new.exists()


@WINDOWS_ONLY
def test_real_folder_swap_script_replaces_program_files_only(tmp_path: Path):
    app_dir = tmp_path / "DriveSweep-win64"
    (app_dir / "_internal").mkdir(parents=True)
    shutil.copy2(_sys_exe("hostname.exe"), app_dir / "DriveSweep.exe")
    (app_dir / "_internal" / "old_only.dll").write_text("old")
    (app_dir / "my-notes.txt").write_text("keep me")
    (app_dir / "DriveSweep-win64.zip.download").write_bytes(b"zip")

    stage = app_dir / updater.UPDATE_STAGING_DIRNAME
    (stage / "_internal").mkdir(parents=True)
    shutil.copy2(_sys_exe("whoami.exe"), stage / "DriveSweep.exe")
    (stage / "_internal" / "new_only.dll").write_text("new")
    new_exe_bytes = (stage / "DriveSweep.exe").read_bytes()

    proc = _run_ps(updater._FOLDER_SWAP_SCRIPT, {
        "DS_APP_DIR": str(app_dir),
        "DS_STAGE_NAME": updater.UPDATE_STAGING_DIRNAME,
        "DS_BACKUP_NAME": updater.UPDATE_BACKUP_DIRNAME,
        "DS_ZIP_NAME": "DriveSweep-win64.zip.download",
        "DS_EXE_NAME": "DriveSweep.exe",
        "DS_WAIT_PIDS": "",
    })

    assert proc.returncode == 0, proc.stderr
    assert (app_dir / "DriveSweep.exe").read_bytes() == new_exe_bytes
    assert (app_dir / "_internal" / "new_only.dll").exists()
    assert not (app_dir / "_internal" / "old_only.dll").exists()
    assert (app_dir / "my-notes.txt").read_text() == "keep me"
    assert not stage.exists()
    assert not (app_dir / "DriveSweep-win64.zip.download").exists()
    backup = app_dir / updater.UPDATE_BACKUP_DIRNAME
    assert (backup / "_internal" / "old_only.dll").exists()


def test_windows_powershell_env_drops_inherited_module_path(monkeypatch):
    monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "x")
    env = updater.windows_powershell_env({"DS_X": "1"})
    assert not any(k.upper() == "PSMODULEPATH" for k in env)
    assert "_PYI_ARCHIVE_FILE" not in env
    assert env["DS_X"] == "1"


def _keep_writing_marker(marker: Path, seconds: float = 25.0):
    """Stand in for the new version: keep reporting 'window opened' while the script runs."""
    import threading
    import time

    stop = threading.Event()

    def run():
        deadline = time.monotonic() + seconds
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                marker.write_text("ok", encoding="utf-8")
            except OSError:
                pass
            time.sleep(0.2)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return stop


def test_confirm_update_started_writes_marker_only_when_asked(tmp_path: Path, monkeypatch):
    marker = tmp_path / updater.UPDATE_MARKER_NAME
    monkeypatch.delenv(updater.UPDATE_MARKER_ENV, raising=False)
    assert updater.confirm_update_started() is False
    assert not marker.exists()
    monkeypatch.setenv(updater.UPDATE_MARKER_ENV, str(marker))
    assert updater.confirm_update_started() is True
    assert marker.read_text(encoding="utf-8") == "ok"
    assert updater.UPDATE_MARKER_ENV not in os.environ


@WINDOWS_ONLY
def test_real_exe_swap_rolls_back_when_new_version_does_not_open(tmp_path: Path):
    old = tmp_path / "DriveSweep.exe"
    new = tmp_path / "DriveSweep.exe.new"
    shutil.copy2(_sys_exe("hostname.exe"), old)
    shutil.copy2(_sys_exe("whoami.exe"), new)  # exits at once and never reports success
    old_bytes = old.read_bytes()

    proc = _run_ps(updater._EXE_SWAP_SCRIPT, {
        "DS_OLD_EXE": str(old),
        "DS_NEW_EXE": str(new),
        "DS_SHA256": hashlib.sha256(new.read_bytes()).hexdigest(),
        "DS_WAIT_PIDS": "",
        "DS_UPDATE_MARKER": str(tmp_path / updater.UPDATE_MARKER_NAME),
        "DS_VERIFY_SECONDS": "30",
    })

    assert proc.returncode == 2, proc.stderr
    assert old.read_bytes() == old_bytes
    assert not (tmp_path / "DriveSweep.exe.old").exists()


@WINDOWS_ONLY
def test_real_exe_swap_removes_backup_when_new_version_opens(tmp_path: Path):
    old = tmp_path / "DriveSweep.exe"
    new = tmp_path / "DriveSweep.exe.new"
    shutil.copy2(_sys_exe("hostname.exe"), old)
    shutil.copy2(_sys_exe("whoami.exe"), new)
    new_bytes = new.read_bytes()
    marker = tmp_path / updater.UPDATE_MARKER_NAME
    stop = _keep_writing_marker(marker)
    try:
        proc = _run_ps(updater._EXE_SWAP_SCRIPT, {
            "DS_OLD_EXE": str(old),
            "DS_NEW_EXE": str(new),
            "DS_SHA256": hashlib.sha256(new_bytes).hexdigest(),
            "DS_WAIT_PIDS": "",
            "DS_UPDATE_MARKER": str(marker),
            "DS_VERIFY_SECONDS": "30",
        })
    finally:
        stop.set()

    assert proc.returncode == 0, proc.stderr
    assert old.read_bytes() == new_bytes
    assert not (tmp_path / "DriveSweep.exe.old").exists()


@WINDOWS_ONLY
def test_real_folder_swap_rolls_back_when_new_version_does_not_open(tmp_path: Path):
    app_dir = tmp_path / "DriveSweep-win64"
    (app_dir / "_internal").mkdir(parents=True)
    shutil.copy2(_sys_exe("hostname.exe"), app_dir / "DriveSweep.exe")
    (app_dir / "_internal" / "old_only.dll").write_text("old")
    old_exe_bytes = (app_dir / "DriveSweep.exe").read_bytes()
    stage = app_dir / updater.UPDATE_STAGING_DIRNAME
    (stage / "_internal").mkdir(parents=True)
    shutil.copy2(_sys_exe("whoami.exe"), stage / "DriveSweep.exe")
    (stage / "_internal" / "new_only.dll").write_text("new")

    proc = _run_ps(updater._FOLDER_SWAP_SCRIPT, {
        "DS_APP_DIR": str(app_dir),
        "DS_STAGE_NAME": updater.UPDATE_STAGING_DIRNAME,
        "DS_BACKUP_NAME": updater.UPDATE_BACKUP_DIRNAME,
        "DS_ZIP_NAME": "DriveSweep-win64.zip.download",
        "DS_EXE_NAME": "DriveSweep.exe",
        "DS_WAIT_PIDS": "",
        "DS_UPDATE_MARKER": str(app_dir / updater.UPDATE_MARKER_NAME),
        "DS_VERIFY_SECONDS": "30",
    })

    assert proc.returncode == 2, proc.stderr
    assert (app_dir / "DriveSweep.exe").read_bytes() == old_exe_bytes
    assert (app_dir / "_internal" / "old_only.dll").exists()
    assert not (app_dir / "_internal" / "new_only.dll").exists()
    assert not (app_dir / updater.UPDATE_BACKUP_DIRNAME).exists()
