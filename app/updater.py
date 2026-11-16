"""Privacy-preserving GitHub Releases updater with mandatory SHA-256 verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
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
_ALLOWED_UPDATE_NAME = re.compile(r"^(drivesweep-setup-[0-9][0-9a-z.\-]*\.exe|drivesweep\.exe|sha256sums\.txt)$")


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
    prefer_setup: bool = True,
) -> dict | None:
    """Choose the best downloadable Windows asset for updating DriveSweep.

    Setup installers (DriveSweep-Setup-*.exe) are preferred by default across all
    Windows install kinds so updates install cleanly via Setup and relaunch.
    """
    valid = [a for a in assets if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")]
    setup_assets = [
        a for a in valid
        if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower()
    ]
    portable_assets = [
        a for a in valid
        if a["name"].lower() == "drivesweep.exe"
    ]
    if prefer_setup and setup_assets:
        return setup_assets[0]
    if install_kind == "onefile_exe" and portable_assets:
        return portable_assets[0]
    if setup_assets:
        return setup_assets[0]
    if portable_assets:
        return portable_assets[0]
    return None


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
                if entry.is_file() and entry.suffix.lower() in {".exe", ".part", ".tmp"}:
                    entry.unlink(missing_ok=True)
        except Exception:
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
    if not safe_name or not safe_name.lower().endswith(".exe"):
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

    update_dir = secure_work_dir("Updates")
    dest_path = update_dir / safe_name
    part_path = update_dir / f"{safe_name}.part"
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

    return {"ok": True, "file_path": str(dest_path), "sha256": actual_hash}


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
            env=sanitized_subprocess_env({"DS_SIG_PATH": str(path)}),
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
    sig = check_update_signature(target)
    if not sig.get("ok"):
        return sig

    try:
        clean_env = sanitized_subprocess_env()
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        no_window_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | creation_flags

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

        if kind == "onefile_exe" and getattr(sys, "frozen", False):
            env = sanitized_subprocess_env({
                "DRIVESWEEP_OLD_EXE": str(Path(sys.executable).resolve()),
                "DRIVESWEEP_NEW_EXE": str(target.resolve()),
                "DRIVESWEEP_PID": str(os.getpid()),
            })
            ps_script = (
                "$p=[int]$env:DRIVESWEEP_PID; "
                "while (Get-Process -Id $p -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 250 }; "
                "Start-Sleep -Milliseconds 350; "
                "Get-ChildItem Env:_PYI_* -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue; "
                "Remove-Item Env:_MEIPASS2 -ErrorAction SilentlyContinue; "
                "for ($i=0; $i -lt 10; $i++) { "
                "  try { Move-Item -Force -Path $env:DRIVESWEEP_NEW_EXE -Destination $env:DRIVESWEEP_OLD_EXE -ErrorAction Stop; break } "
                "  catch { Start-Sleep -Milliseconds 300 } "
                "}; "
                "Start-Process -FilePath $env:DRIVESWEEP_OLD_EXE"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
                env=env,
                creationflags=no_window_flags,
                close_fds=True,
            )
            return {"ok": True, "should_exit": True, "mode": "portable_swap"}

        subprocess.Popen(
            [str(target)],
            env=clean_env,
            creationflags=creation_flags,
            close_fds=True,
        )
        return {"ok": True, "should_exit": True, "mode": "launch"}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to start installer: {exc}"}
