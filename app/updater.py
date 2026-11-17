"""Privacy-preserving GitHub Releases updater with mandatory SHA-256 verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from app import __version__
from app.safety import sanitized_subprocess_env, secure_work_dir

GITHUB_OWNER = "rauell1"
GITHUB_REPO = "drive-sweep"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse a tag or version string like 'v0.2.1' into an integer tuple."""
    clean = str(version_str or "").strip().lstrip("vV")
    nums = re.findall(r"\d+", clean.split("-")[0])
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def is_newer_version(candidate: str, current: str) -> bool:
    """Return True if candidate version is strictly newer than current version."""
    c_parts = parse_semver(candidate)
    cur_parts = parse_semver(current)
    max_len = max(len(c_parts), len(cur_parts))
    c_pad = c_parts + (0,) * (max_len - len(c_parts))
    cur_pad = cur_parts + (0,) * (max_len - len(cur_parts))
    return c_pad > cur_pad


def verify_https_github_url(url: str) -> bool:
    """Allow only HTTPS URLs hosted on GitHub or GitHub release asset CDNs."""
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
        if parsed.scheme != "https":
            return False
        host = (parsed.hostname or "").lower()
        allowed_suffixes = (
            "github.com",
            "api.github.com",
            "objects.githubusercontent.com",
            "release-assets.githubusercontent.com",
        )
        return host in allowed_suffixes or host.endswith(".githubusercontent.com")
    except Exception:
        return False


RELEASE_DOWNLOAD_PREFIX = f"/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
_ALLOWED_UPDATE_NAME = re.compile(
    r"^(drivesweep-setup-[0-9][0-9a-z.\-]*\.exe|drivesweep\.exe|drivesweep-win64\.zip|sha256sums\.txt)$"
)
PORTABLE_EXE_NAME = "drivesweep.exe"
PORTABLE_ZIP_NAME = "drivesweep-win64.zip"
# Folders used while the folder (zip) version replaces itself; they live inside the app folder.
UPDATE_STAGING_DIRNAME = "_update_staging"
UPDATE_BACKUP_DIRNAME = "_update_old"
# Written by the new version once its window has opened, so the swap step knows the update worked.
UPDATE_MARKER_NAME = ".drivesweep-update-ok"
UPDATE_MARKER_ENV = "DRIVESWEEP_UPDATE_MARKER"
# How long the swap step waits for the new version to open before leaving the backup in place.
UPDATE_VERIFY_SECONDS = 120
_MAX_ZIP_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024


def parse_release_download_url(url: str) -> tuple[str, str] | None:
    """Return (tag, file_name) for an official DriveSweep release download URL, else None.

    Only https://github.com/<owner>/<repo>/releases/download/<tag>/<file> is accepted, so a
    caller can never point the elevated updater at a file hosted in any other repository.
    """
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return None
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "github.com":
        return None
    if parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return None
    path = parsed.path
    if not path.startswith(RELEASE_DOWNLOAD_PREFIX):
        return None
    rest = path[len(RELEASE_DOWNLOAD_PREFIX):].split("/")
    if len(rest) != 2 or not rest[0] or not rest[1]:
        return None
    tag, fname = urllib.parse.unquote(rest[0]), urllib.parse.unquote(rest[1])
    if not re.fullmatch(r"[vV]?[0-9][0-9A-Za-z.\-]*", tag):
        return None
    if not _ALLOWED_UPDATE_NAME.fullmatch(fname.lower()):
        return None
    return tag, fname


def detect_install_kind() -> str:
    """Detect whether running from Inno Setup, portable exe, folder bundle, or source."""
    if not getattr(sys, "frozen", False):
        return "source"
    exe_dir = Path(sys.executable).resolve().parent
    if (exe_dir / "unins000.exe").exists():
        return "setup"
    if (exe_dir / "_internal").exists():
        return "onedir_zip"
    return "onefile_exe"


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse SHA256SUMS.txt contents into {lowercase_filename: lowercase_hex}."""
    hashes: dict[str, str] = {}
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest = parts[0].strip().lower()
        fname = parts[1].strip().lstrip("*").strip()
        if re.fullmatch(r"[0-9a-f]{64}", digest) and fname:
            hashes[os.path.basename(fname).lower()] = digest
    return hashes


def pick_release_asset(
    assets: list[dict],
    install_kind: str,
    prefer_setup: bool = False,
) -> dict | None:
    """Choose the release file that updates the copy of DriveSweep the user actually runs.

    * Installed with Setup  -> the new DriveSweep-Setup-*.exe (upgrades Program Files in place).
    * Portable DriveSweep.exe -> the new DriveSweep.exe, swapped into the same folder.
    * Folder version from the zip -> the new DriveSweep-win64.zip, unpacked into the same folder.
    * Running from source, or a portable file is missing from the release -> Setup.
    """
    valid = [a for a in assets if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")]
    setup_assets = [
        a for a in valid
        if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower()
    ]
    portable_assets = [a for a in valid if a["name"].lower() == PORTABLE_EXE_NAME]
    zip_assets = [a for a in valid if a["name"].lower() == PORTABLE_ZIP_NAME]
    if prefer_setup and setup_assets:
        return setup_assets[0]
    if install_kind == "onefile_exe" and portable_assets:
        return portable_assets[0]
    if install_kind == "onedir_zip" and zip_assets:
        return zip_assets[0]
    if setup_assets:
        return setup_assets[0]
    if portable_assets:
        return portable_assets[0]
    return None


def update_method_for(asset_name: str) -> str:
    """Return how a release file is applied: 'setup', 'replace_exe' or 'replace_folder'."""
    name = os.path.basename(str(asset_name or "")).lower()
    if name == PORTABLE_EXE_NAME:
        return "replace_exe"
    if name == PORTABLE_ZIP_NAME:
        return "replace_folder"
    return "setup"


def app_install_dir() -> Path:
    """Folder that holds the running DriveSweep.exe (or the source tree when not frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def folder_is_writable(folder: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=str(folder), prefix=".ds_write_test_", delete=True):
            return True
    except OSError:
        return False


def cleanup_stale_updates() -> None:
    """Remove leftover temporary installer files from completed or aborted updates."""
    candidates = [Path(tempfile.gettempdir()) / "DriveSweep-Updates"]
    if os.name == "nt":
        candidates.append(Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "DriveSweep" / "Updates")
    for update_dir in candidates:
        if not update_dir.exists():
            continue
        try:
            for entry in update_dir.iterdir():
                if entry.is_file() and entry.suffix.lower() in {".exe", ".zip", ".part", ".tmp"}:
                    entry.unlink(missing_ok=True)
        except Exception:
            pass


def confirm_update_started() -> bool:
    """Tell a waiting in place update that this new version opened successfully.

    Called once the main window is shown. Writes the marker file the swap step is waiting for
    (only when this run was started by an update) and then removes the previous version's
    backup. Returns True when a marker was written.
    """
    marker = os.environ.pop(UPDATE_MARKER_ENV, "")
    wrote = False
    if marker:
        try:
            Path(marker).write_text("ok", encoding="utf-8")
            wrote = True
        except OSError:
            pass
    cleanup_in_place_update_leftovers()
    return wrote


def cleanup_in_place_update_leftovers(app_dir: Path | None = None, exe_name: str | None = None) -> None:
    """Remove backups and partial files left in the app folder by an in place update.

    Runs once the new version's window has opened, which proves the swap worked, so the backup
    of the previous version is no longer needed. (A crash before that point keeps the backup,
    and the swap step restores it.)
    """
    if app_dir is None:
        if not getattr(sys, "frozen", False):
            return
        app_dir = app_install_dir()
        exe_name = Path(sys.executable).name
    exe_name = exe_name or "DriveSweep.exe"
    for suffix in (".old", ".new", ".new.part"):
        try:
            (app_dir / f"{exe_name}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
    for dirname in (UPDATE_BACKUP_DIRNAME, UPDATE_STAGING_DIRNAME):
        leftover = app_dir / dirname
        try:
            if leftover.is_dir() and not leftover.is_symlink():
                shutil.rmtree(leftover, ignore_errors=True)
        except OSError:
            pass
    for leftover_zip in ("DriveSweep-win64.zip.download", "DriveSweep-win64.zip.download.part"):
        try:
            (app_dir / leftover_zip).unlink(missing_ok=True)
        except OSError:
            pass


LATEST_RELEASE_WEB = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def _check_updates_via_web_redirect(
    current_version: str,
    install_kind: str,
    timeout: float,
) -> dict | None:
    """Rate-limit-free fallback using github.com/releases/latest when api.github.com throttles."""
    req = urllib.request.Request(
        LATEST_RELEASE_WEB,
        headers={
            "Accept": "application/json",
            "User-Agent": f"DriveSweep/{current_version}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = str(resp.geturl() or "")
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    tag = ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            tag = str(data.get("tag_name") or "").strip()
    except Exception:
        tag = ""
    if not tag and "/releases/tag/" in final_url:
        tag = final_url.rsplit("/releases/tag/", 1)[-1].split("?")[0].strip()
    if not tag:
        return None

    latest_ver = tag.lstrip("vV") or current_version
    if install_kind == "onefile_exe":
        asset_name = "DriveSweep.exe"
    elif install_kind == "onedir_zip":
        asset_name = "DriveSweep-win64.zip"
    else:
        asset_name = f"DriveSweep-Setup-{latest_ver}.exe"
    asset_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{tag}/{asset_name}"
    sha256_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{tag}/SHA256SUMS.txt"
    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest_ver,
        "update_available": is_newer_version(tag, current_version),
        "install_kind": install_kind,
        "release_url": f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{tag}",
        "release_notes": "",
        "asset_name": asset_name,
        "update_method": update_method_for(asset_name),
        "asset_url": asset_url,
        "asset_size": 0,
        "sha256_url": sha256_url,
    }


def check_for_updates(current_version: str = __version__, timeout: float = 8.0) -> dict:
    """Perform a read-only GET to public GitHub Releases without sending user/device data."""
    install_kind = detect_install_kind()
    req = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"DriveSweep/{current_version}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {
                "ok": True,
                "current_version": current_version,
                "latest_version": current_version,
                "update_available": False,
                "install_kind": install_kind,
                "message": "No published updates found yet.",
            }
        if exc.code in (403, 429):
            fallback = _check_updates_via_web_redirect(current_version, install_kind, timeout)
            if fallback is not None:
                return fallback
        return {"ok": False, "error": f"Update check failed (HTTP {exc.code}).", "current_version": current_version}
    except Exception as exc:
        fallback = _check_updates_via_web_redirect(current_version, install_kind, timeout)
        if fallback is not None:
            return fallback
        return {"ok": False, "error": f"Could not reach GitHub Releases: {exc}", "current_version": current_version}

    tag = str(payload.get("tag_name") or "").strip()
    latest_ver = tag.lstrip("vV") or current_version
    assets = payload.get("assets") or []
    chosen = pick_release_asset(assets, install_kind)
    sha_asset = next(
        (a for a in assets if str(a.get("name", "")).lower() == "sha256sums.txt"),
        None,
    )
    update_available = bool(tag and is_newer_version(tag, current_version))

    return {
        "ok": True,
        "current_version": current_version,
        "latest_version": latest_ver,
        "update_available": update_available,
        "install_kind": install_kind,
        "release_url": str(payload.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"),
        "release_notes": str(payload.get("body") or "")[:2000],
        "asset_name": str(chosen.get("name")) if chosen else "",
        "update_method": update_method_for(str(chosen.get("name"))) if chosen else "",
        "update_folder": str(app_install_dir()) if chosen and update_method_for(str(chosen.get("name"))) != "setup" else "",
        "asset_url": str(chosen.get("browser_download_url")) if chosen else "",
        "asset_size": int(chosen.get("size") or 0) if chosen else 0,
        "sha256_url": str(sha_asset.get("browser_download_url")) if sha_asset else "",
    }


def download_and_verify_update(
    asset_url: str,
    asset_name: str,
    sha256_url: str,
    timeout: float = 90.0,
    progress_cb: Callable[[str, int, int, str], None] | None = None,
    expected_size: int = 0,
) -> dict:
    """Download an official release package and verify its SHA-256 against SHA256SUMS.txt."""
    safe_name = os.path.basename(str(asset_name or "")).strip()
    if not safe_name or not (safe_name.lower().endswith(".exe") or safe_name.lower() == PORTABLE_ZIP_NAME):
        return {"ok": False, "error": "Unsupported update file type."}
    asset_info = parse_release_download_url(asset_url)
    sums_info = parse_release_download_url(sha256_url)
    if asset_info is None or sums_info is None:
        return {"ok": False, "error": "Update URL must be an official DriveSweep GitHub release download."}
    if asset_info[1].lower() != safe_name.lower() or sums_info[1].lower() != "sha256sums.txt":
        return {"ok": False, "error": "Update file name does not match the release download."}
    if asset_info[0] != sums_info[0]:
        return {"ok": False, "error": "Installer and checksum file must come from the same release."}
    if not is_newer_version(asset_info[0], __version__):
        return {"ok": False, "error": "Refusing to install a release that is not newer than this version."}

    if progress_cb is not None:
        progress_cb("checksum", 0, max(0, int(expected_size or 0)), "Checking release checksums...")

    try:
        sha_req = urllib.request.Request(sha256_url, headers={"User-Agent": f"DriveSweep/{__version__}"})
        with urllib.request.urlopen(sha_req, timeout=15.0) as resp:
            sums_map = parse_sha256sums(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"ok": False, "error": f"Failed to download SHA256SUMS.txt: {exc}"}

    expected_hash = sums_map.get(safe_name.lower())
    if not expected_hash:
        return {"ok": False, "error": f"Checksum for {safe_name} was not found in SHA256SUMS.txt."}

    method = update_method_for(safe_name)
    if method == "setup":
        update_dir = secure_work_dir("Updates")
        dest_path = update_dir / safe_name
    else:
        # Portable copies are updated where they live: the new file is saved in the same
        # folder as the running DriveSweep.exe, then swapped in after DriveSweep closes.
        update_dir = app_install_dir()
        if not folder_is_writable(update_dir):
            return {
                "ok": False,
                "error": (
                    f"DriveSweep cannot write to its folder ({update_dir}). Move DriveSweep to a folder "
                    "you can write to, or install it with DriveSweep Setup."
                ),
            }
        if method == "replace_exe":
            dest_path = update_dir / f"{Path(sys.executable).name if getattr(sys, 'frozen', False) else 'DriveSweep.exe'}.new"
        else:
            dest_path = update_dir / f"{safe_name}.download"
    part_path = dest_path.with_name(dest_path.name + ".part")
    part_path.unlink(missing_ok=True)

    hasher = hashlib.sha256()
    downloaded = 0
    total_bytes = max(0, int(expected_size or 0))
    last_reported = -1
    try:
        dl_req = urllib.request.Request(asset_url, headers={"User-Agent": f"DriveSweep/{__version__}"})
        with urllib.request.urlopen(dl_req, timeout=timeout) as resp, open(part_path, "wb") as fh:
            headers = getattr(resp, "headers", None)
            if headers is not None:
                try:
                    header_len = int(headers.get("Content-Length") or 0)
                    if header_len > 0:
                        total_bytes = header_len
                except (TypeError, ValueError):
                    pass
            if progress_cb is not None:
                progress_cb("downloading", 0, total_bytes, f"Downloading {safe_name}...")
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb is not None and (downloaded - last_reported >= 131072):
                    last_reported = downloaded
                    progress_cb("downloading", downloaded, total_bytes, f"Downloading {safe_name}...")
    except Exception as exc:
        part_path.unlink(missing_ok=True)
        dest_path.unlink(missing_ok=True)
        return {"ok": False, "error": f"Download failed: {exc}"}

    if progress_cb is not None:
        progress_cb("verifying", downloaded, max(downloaded, total_bytes), "Verifying SHA-256 checksum...")

    actual_hash = hasher.hexdigest().lower()
    if actual_hash != expected_hash:
        part_path.unlink(missing_ok=True)
        dest_path.unlink(missing_ok=True)
        return {"ok": False, "error": "SHA-256 verification failed. Update file was removed."}

    try:
        part_path.replace(dest_path)
    except Exception as exc:
        part_path.unlink(missing_ok=True)
        return {"ok": False, "error": f"Could not finalize update package: {exc}"}

    return {"ok": True, "file_path": str(dest_path), "sha256": actual_hash, "update_method": method}


def _pyinstaller_bootloader_ppid() -> int:
    """Return parent bootloader PID if running frozen inside onefile DriveSweep.exe."""
    if not getattr(sys, "frozen", False):
        return 0
    try:
        import psutil

        ppid = os.getppid()
        if ppid > 0 and psutil.Process(ppid).name().lower() == "drivesweep.exe":
            return ppid
    except Exception:
        pass
    return 0


def _strip_pyi_from_process_env() -> None:
    """Remove PyInstaller _PYI_* / _MEIPASS2 variables before spawning an external installer."""
    for key in [k for k in list(os.environ.keys()) if k.startswith("_PYI_") or k == "_MEIPASS2"]:
        os.environ.pop(key, None)


def _launch_windows_setup(setup_exe: Path, setup_args: str) -> tuple[bool, int]:
    """Launch Inno Setup directly via ShellExecuteW so UAC appears immediately without PowerShell delay."""
    import ctypes
    import ctypes.wintypes as wintypes

    _strip_pyi_from_process_env()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = [
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_int,
    ]
    shell32.ShellExecuteW.restype = wintypes.HINSTANCE
    hinst = shell32.ShellExecuteW(
        None,
        "open",
        str(setup_exe),
        setup_args,
        str(setup_exe.parent),
        1,
    )
    rc = int(hinst or 0)
    return rc > 32, rc


_FILE_SHARE_READ = 0x00000001
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3


def _lock_file_against_writes(path: Path) -> int | None:
    """Open path with read only sharing so no process can modify, rename or delete it while held."""
    if sys.platform != "win32":
        return None
    import ctypes
    import ctypes.wintypes as wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(str(path), _GENERIC_READ, _FILE_SHARE_READ, None, _OPEN_EXISTING, 0, None)
    value = int(handle or 0) if handle is not None else 0
    if value in (0, ctypes.c_void_p(-1).value, -1):
        return None
    return value


def _release_file_lock(handle: int | None) -> None:
    if handle is None or sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def get_authenticode_info(path: str | Path) -> dict:
    """Return {'status', 'subject', 'thumbprint'} of a file's Authenticode signature on Windows."""
    if sys.platform != "win32":
        return {"status": "Unsupported", "subject": "", "thumbprint": ""}
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:DS_SIG_PATH; "
        "[pscustomobject]@{ Status = [string]$s.Status; "
        "Subject = [string]$s.SignerCertificate.Subject; "
        "Thumbprint = [string]$s.SignerCertificate.Thumbprint } | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=60,
            env=windows_powershell_env({"DS_SIG_PATH": str(path)}),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        data = json.loads((proc.stdout or "").strip() or "{}")
        return {
            "status": str(data.get("Status") or "Unknown"),
            "subject": str(data.get("Subject") or ""),
            "thumbprint": str(data.get("Thumbprint") or ""),
        }
    except Exception:
        return {"status": "Unknown", "subject": "", "thumbprint": ""}


def check_update_signature(update_path: str | Path, current_exe: str | None = None) -> dict:
    """Decide whether a downloaded installer's Authenticode signature is acceptable.

    Rules:
    * A signature that is present but broken (tampered, revoked, untrusted) is always rejected.
    * If the running DriveSweep is signed, the update must be validly signed by the same publisher.
    * If the running build is unsigned (before code signing is live), an unsigned update is allowed
      because the SHA-256 checksum has already been verified.
    """
    update_sig = get_authenticode_info(update_path)
    status = update_sig["status"]
    if status not in ("Valid", "NotSigned", "Unsupported", "Unknown"):
        return {"ok": False, "error": f"Update signature check failed ({status}). The file was not run."}

    current_sig = {"status": "NotSigned", "subject": ""}
    exe = current_exe if current_exe is not None else (sys.executable if getattr(sys, "frozen", False) else "")
    if exe:
        current_sig = get_authenticode_info(exe)
    if current_sig["status"] == "Valid":
        if status != "Valid":
            return {"ok": False, "error": "This DriveSweep build is signed, but the update is not. The file was not run."}
        if update_sig["subject"] != current_sig["subject"]:
            return {"ok": False, "error": "The update is signed by a different publisher. The file was not run."}
    return {"ok": True, "status": status, "subject": update_sig["subject"]}


def launch_downloaded_update(
    file_path: str,
    install_kind: str | None = None,
    expected_sha256: str = "",
) -> dict:
    """Launch the verified Setup package directly (instant UAC) and signal DriveSweep to exit.

    The file is locked against writes, its SHA-256 is checked again, and its Authenticode
    signature is checked, all immediately before it starts, so it cannot be swapped after
    verification.
    """
    target = Path(file_path)
    if not target.exists():
        return {"ok": False, "error": "Downloaded update file does not exist."}

    kind = install_kind or detect_install_kind()
    name_lower = target.name.lower()

    if sys.platform != "win32":
        return {"ok": False, "error": "Self-install updates are currently supported on Windows."}

    lock = _lock_file_against_writes(target)
    if lock is None:
        return {"ok": False, "error": "Could not lock the update file for verification. Try again."}
    try:
        return _launch_locked_update(target, kind, name_lower, expected_sha256)
    finally:
        _release_file_lock(lock)


def _launch_locked_update(target: Path, kind: str, name_lower: str, expected_sha256: str) -> dict:
    if expected_sha256:
        try:
            if _sha256_file(target) != expected_sha256.lower():
                target.unlink(missing_ok=True)
                return {"ok": False, "error": "Update file changed after verification. It was removed and not run."}
        except OSError as exc:
            return {"ok": False, "error": f"Could not re-verify update file: {exc}"}

    is_zip = name_lower.endswith(".zip") or name_lower.endswith(".zip.download")
    if not is_zip:
        sig = check_update_signature(target)
        if not sig.get("ok"):
            return sig

    try:
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        if "setup" in name_lower and name_lower.endswith(".exe"):
            resolved_setup = target.resolve()
            setup_args = (
                "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART "
                "/CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS "
                "/NORESTARTAPPLICATIONS /AUTOSTART=1"
            )
            ok, rc = _launch_windows_setup(resolved_setup, setup_args)
            if not ok:
                return {
                    "ok": False,
                    "error": f"Windows installer did not start (ShellExecute code {rc}). Try again or run Setup manually.",
                }
            return {"ok": True, "should_exit": True, "mode": "setup"}

        if is_zip:
            return _start_folder_swap(target)

        if name_lower.endswith(".exe.new") or (kind == "onefile_exe" and getattr(sys, "frozen", False)):
            return _start_exe_swap(target, expected_sha256 or _sha256_file(target))

        subprocess.Popen(
            [str(target)],
            env=sanitized_subprocess_env(),
            creationflags=creation_flags,
            close_fds=True,
        )
        return {"ok": True, "should_exit": True, "mode": "launch"}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to start the update: {exc}"}


# Runs after DriveSweep exits. It checks the new exe's SHA-256 once more, keeps the current exe
# as DriveSweep.exe.old, moves the new one into place (restoring the old one if that fails),
# and starts DriveSweep again. If the new version exits without opening its window, the previous
# version is restored and started instead; otherwise the backup is deleted.
_EXE_SWAP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
foreach ($p in ($env:DS_WAIT_PIDS -split ',' | Where-Object { $_ })) {
  while (Get-Process -Id ([int]$p) -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 250 }
}
Start-Sleep -Milliseconds 400
Get-ChildItem Env:_PYI_* -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
Remove-Item Env:_MEIPASS2 -ErrorAction SilentlyContinue
# Starts the new version and waits until it reports that its window opened (it writes the
# marker file named in DRIVESWEEP_UPDATE_MARKER). Returns $true when it did, $false when the new
# version exited without opening, and $null when it is still starting after the wait.
function Start-AndVerify([string]$exePath, [string]$workDir) {
  $marker = $env:DS_UPDATE_MARKER
  $verify = 0
  [void][int]::TryParse("$env:DS_VERIFY_SECONDS", [ref]$verify)
  if (-not $marker -or $verify -le 0) {
    if ($workDir) { Start-Process -FilePath $exePath -WorkingDirectory $workDir } else { Start-Process -FilePath $exePath }
    return $null
  }
  Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
  $env:DRIVESWEEP_UPDATE_MARKER = $marker
  if ($workDir) { $proc = Start-Process -FilePath $exePath -WorkingDirectory $workDir -PassThru } else { $proc = Start-Process -FilePath $exePath -PassThru }
  Remove-Item Env:DRIVESWEEP_UPDATE_MARKER -ErrorAction SilentlyContinue
  $deadline = (Get-Date).AddSeconds($verify)
  while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue; return $true }
    if ($proc.HasExited) {
      Start-Sleep -Seconds 2
      if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue; return $true }
      return $false
    }
    Start-Sleep -Milliseconds 500
  }
  return $null
}
$old = $env:DS_OLD_EXE; $new = $env:DS_NEW_EXE; $bak = "$old.old"
# Hash with .NET directly so no PowerShell module has to load (works in any PowerShell host).
$fs = [System.IO.File]::OpenRead($new)
try {
  $sha = [System.Security.Cryptography.SHA256]::Create()
  $hash = ([System.BitConverter]::ToString($sha.ComputeHash($fs)) -replace '[^0-9A-Fa-f]', '').ToLower()
} finally { $fs.Dispose() }
if ($hash -ne $env:DS_SHA256) {
  Remove-Item -LiteralPath $new -Force -ErrorAction SilentlyContinue
  Start-Process -FilePath $old
  exit 1
}
$swapped = $false
for ($i = 0; $i -lt 20 -and -not $swapped; $i++) {
  try {
    if (Test-Path -LiteralPath $bak) { Remove-Item -LiteralPath $bak -Force }
    Move-Item -LiteralPath $old -Destination $bak -Force
    try {
      Move-Item -LiteralPath $new -Destination $old -Force
      $swapped = $true
    } catch {
      Move-Item -LiteralPath $bak -Destination $old -Force
      throw
    }
  } catch { Start-Sleep -Milliseconds 300 }
}
if (-not $swapped) { Start-Process -FilePath $old; exit 1 }
$result = Start-AndVerify $old $null
if ($result -eq $true) {
  Remove-Item -LiteralPath $bak -Force -ErrorAction SilentlyContinue
  exit 0
}
if ($result -eq $false) {
  # The new version closed without opening its window: put the previous version back.
  Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue
  Move-Item -LiteralPath $bak -Destination $old -Force
  Start-Process -FilePath $old
  exit 2
}
exit 0
"""

# Runs after DriveSweep exits. Moves the current app files that the new version replaces into _update_old, moves the
# unpacked new version from _update_staging into the app folder, restores the old files if
# anything fails, and starts DriveSweep again.
_FOLDER_SWAP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
foreach ($p in ($env:DS_WAIT_PIDS -split ',' | Where-Object { $_ })) {
  while (Get-Process -Id ([int]$p) -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 250 }
}
Start-Sleep -Milliseconds 400
Get-ChildItem Env:_PYI_* -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
Remove-Item Env:_MEIPASS2 -ErrorAction SilentlyContinue
# Starts the new version and waits until it reports that its window opened (it writes the
# marker file named in DRIVESWEEP_UPDATE_MARKER). Returns $true when it did, $false when the new
# version exited without opening, and $null when it is still starting after the wait.
function Start-AndVerify([string]$exePath, [string]$workDir) {
  $marker = $env:DS_UPDATE_MARKER
  $verify = 0
  [void][int]::TryParse("$env:DS_VERIFY_SECONDS", [ref]$verify)
  if (-not $marker -or $verify -le 0) {
    if ($workDir) { Start-Process -FilePath $exePath -WorkingDirectory $workDir } else { Start-Process -FilePath $exePath }
    return $null
  }
  Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
  $env:DRIVESWEEP_UPDATE_MARKER = $marker
  if ($workDir) { $proc = Start-Process -FilePath $exePath -WorkingDirectory $workDir -PassThru } else { $proc = Start-Process -FilePath $exePath -PassThru }
  Remove-Item Env:DRIVESWEEP_UPDATE_MARKER -ErrorAction SilentlyContinue
  $deadline = (Get-Date).AddSeconds($verify)
  while ((Get-Date) -lt $deadline) {
    if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue; return $true }
    if ($proc.HasExited) {
      Start-Sleep -Seconds 2
      if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue; return $true }
      return $false
    }
    Start-Sleep -Milliseconds 500
  }
  return $null
}
$app = $env:DS_APP_DIR
$stage = Join-Path $app $env:DS_STAGE_NAME
$old = Join-Path $app $env:DS_BACKUP_NAME
$exe = Join-Path $app $env:DS_EXE_NAME
$skip = @($env:DS_STAGE_NAME, $env:DS_BACKUP_NAME, $env:DS_ZIP_NAME)
$placed = @()
$swapped = $false
try {
  if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
  New-Item -ItemType Directory -Path $old | Out-Null
  # Only items the new version ships are replaced; anything else in the folder is left alone.
  $incoming = @(Get-ChildItem -LiteralPath $stage -Force | ForEach-Object { $_.Name })
  Get-ChildItem -LiteralPath $app -Force | Where-Object { ($skip -notcontains $_.Name) -and ($incoming -contains $_.Name) } | ForEach-Object {
    Move-Item -LiteralPath $_.FullName -Destination $old -Force
  }
  Get-ChildItem -LiteralPath $stage -Force | ForEach-Object {
    Move-Item -LiteralPath $_.FullName -Destination $app -Force
    $placed += $_.Name
  }
  Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath (Join-Path $app $env:DS_ZIP_NAME) -Force -ErrorAction SilentlyContinue
  $swapped = $true
} catch {
  foreach ($n in $placed) { Remove-Item -LiteralPath (Join-Path $app $n) -Recurse -Force -ErrorAction SilentlyContinue }
  Get-ChildItem -LiteralPath $old -Force | ForEach-Object {
    Move-Item -LiteralPath $_.FullName -Destination $app -Force -ErrorAction SilentlyContinue
  }
}
if (-not $swapped) { Start-Process -FilePath $exe -WorkingDirectory $app; exit 1 }
$result = Start-AndVerify $exe $app
if ($result -eq $true) {
  Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
  exit 0
}
if ($result -eq $false) {
  # The new version closed without opening its window: put the previous version back.
  foreach ($n in $placed) { Remove-Item -LiteralPath (Join-Path $app $n) -Recurse -Force -ErrorAction SilentlyContinue }
  Get-ChildItem -LiteralPath $old -Force | ForEach-Object {
    Move-Item -LiteralPath $_.FullName -Destination $app -Force -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
  Start-Process -FilePath $exe -WorkingDirectory $app
  exit 2
}
exit 0
"""


def _wait_pids() -> str:
    pids = [str(os.getpid())]
    boot = _pyinstaller_bootloader_ppid()
    if boot:
        pids.append(str(boot))
    return ",".join(pids)


def windows_powershell_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for Windows PowerShell without an inherited PSModulePath.

    If DriveSweep was started from PowerShell 7, PSModulePath points at PowerShell 7 modules and
    Windows PowerShell 5.1 then fails to load its own built in modules (Get-FileHash and
    Get-AuthenticodeSignature are not found). Dropping it restores the default module paths.
    """
    env = sanitized_subprocess_env(extra)
    for key in [k for k in env if k.upper() == "PSMODULEPATH"]:
        env.pop(key, None)
    return env


def _spawn_hidden_powershell(script: str, extra_env: dict[str, str], cwd: str | None = None) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", script],
        env=windows_powershell_env(extra_env),
        creationflags=flags,
        close_fds=True,
        cwd=cwd,
    )


def _start_exe_swap(new_exe: Path, sha256: str) -> dict:
    """Replace the running portable DriveSweep.exe with the verified new one after exit."""
    current = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else app_install_dir() / "DriveSweep.exe"
    _spawn_hidden_powershell(
        _EXE_SWAP_SCRIPT,
        {
            "DS_OLD_EXE": str(current),
            "DS_NEW_EXE": str(new_exe.resolve()),
            "DS_SHA256": sha256.lower(),
            "DS_WAIT_PIDS": _wait_pids(),
            "DS_UPDATE_MARKER": str(current.parent / UPDATE_MARKER_NAME),
            "DS_VERIFY_SECONDS": str(UPDATE_VERIFY_SECONDS),
        },
        cwd=str(current.parent.parent if current.parent.parent != current.parent else current.parent),
    )
    return {"ok": True, "should_exit": True, "mode": "portable_swap", "target": str(current)}


def extract_update_zip(zip_path: Path, staging: Path) -> dict:
    """Safely unpack the folder version into staging, rejecting unsafe or unexpected archives."""
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    root = staging.resolve()
    total = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = zf.infolist()
            names = {m.filename.replace("\\", "/").lower() for m in members}
            if "drivesweep.exe" not in names:
                return {"ok": False, "error": "The update archive does not contain DriveSweep.exe at its top level."}
            for m in members:
                name = m.filename.replace("\\", "/")
                if name.startswith("/") or ":" in name or any(part == ".." for part in name.split("/")):
                    return {"ok": False, "error": f"Unsafe path in update archive: {m.filename}"}
                if (m.external_attr >> 16) & 0o170000 == 0o120000:
                    return {"ok": False, "error": f"Links are not allowed in the update archive: {m.filename}"}
                total += m.file_size
                if total > _MAX_ZIP_UNPACKED_BYTES:
                    return {"ok": False, "error": "The update archive is unexpectedly large."}
                dest = (staging / name).resolve()
                if dest != root and root not in dest.parents:
                    return {"ok": False, "error": f"Unsafe path in update archive: {m.filename}"}
            zf.extractall(staging)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": f"Could not unpack the update: {exc}"}
    return {"ok": True, "exe": str(staging / "DriveSweep.exe")}


def _start_folder_swap(zip_path: Path) -> dict:
    """Unpack the verified zip next to the running app and swap the folder contents after exit."""
    app_dir = app_install_dir()
    staging = app_dir / UPDATE_STAGING_DIRNAME
    unpacked = extract_update_zip(zip_path, staging)
    if not unpacked.get("ok"):
        return unpacked
    sig = check_update_signature(unpacked["exe"])
    if not sig.get("ok"):
        shutil.rmtree(staging, ignore_errors=True)
        return sig
    exe_name = Path(sys.executable).name if getattr(sys, "frozen", False) else "DriveSweep.exe"
    _spawn_hidden_powershell(
        _FOLDER_SWAP_SCRIPT,
        {
            "DS_APP_DIR": str(app_dir),
            "DS_STAGE_NAME": UPDATE_STAGING_DIRNAME,
            "DS_BACKUP_NAME": UPDATE_BACKUP_DIRNAME,
            "DS_ZIP_NAME": zip_path.name,
            "DS_EXE_NAME": exe_name,
            "DS_WAIT_PIDS": _wait_pids(),
            "DS_UPDATE_MARKER": str(app_dir / UPDATE_MARKER_NAME),
            "DS_VERIFY_SECONDS": str(UPDATE_VERIFY_SECONDS),
        },
        cwd=str(app_dir.parent if app_dir.parent != app_dir else app_dir),
    )
    return {"ok": True, "should_exit": True, "mode": "folder_swap", "target": str(app_dir)}
