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
from app.safety import sanitized_subprocess_env

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
    update_dir = Path(tempfile.gettempdir()) / "DriveSweep-Updates"
    if not update_dir.exists():
        return
    try:
        for entry in update_dir.iterdir():
            if entry.is_file() and entry.suffix.lower() in {".exe", ".part", ".tmp"}:
                entry.unlink(missing_ok=True)
    except Exception:
        pass


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
        return {"ok": False, "error": f"Update check failed (HTTP {exc.code}).", "current_version": current_version}
    except Exception as exc:
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
    if not verify_https_github_url(asset_url) or not verify_https_github_url(sha256_url):
        return {"ok": False, "error": "Update URL must use HTTPS on GitHub."}

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

    update_dir = Path(tempfile.gettempdir()) / "DriveSweep-Updates"
    update_dir.mkdir(parents=True, exist_ok=True)
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


def launch_downloaded_update(file_path: str, install_kind: str | None = None) -> dict:
    """Exit cleanly, launch the verified Setup package silently, and relaunch DriveSweep."""
    target = Path(file_path)
    if not target.exists():
        return {"ok": False, "error": "Downloaded update file does not exist."}

    kind = install_kind or detect_install_kind()
    name_lower = target.name.lower()

    if sys.platform != "win32":
        return {"ok": False, "error": "Self-install updates are currently supported on Windows."}

    try:
        clean_env = sanitized_subprocess_env()
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        no_window_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | creation_flags

        if "setup" in name_lower and name_lower.endswith(".exe"):
            env = sanitized_subprocess_env({
                "DRIVESWEEP_SETUP_EXE": str(target.resolve()),
                "DRIVESWEEP_PID": str(os.getpid()),
            })
            ps_script = (
                "$p=[int]$env:DRIVESWEEP_PID; "
                "$deadline=[DateTime]::UtcNow.AddSeconds(20); "
                "while ((Get-Process -Id $p -ErrorAction SilentlyContinue) -and ([DateTime]::UtcNow -lt $deadline)) "
                "{ Start-Sleep -Milliseconds 200 }; "
                "Start-Sleep -Milliseconds 350; "
                "Get-ChildItem Env:_PYI_* -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue; "
                "Remove-Item Env:_MEIPASS2 -ErrorAction SilentlyContinue; "
                "$a = @('/SILENT','/SUPPRESSMSGBOXES','/NORESTART','/CLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS','/AUTOSTART=1'); "
                "try { Start-Process -FilePath $env:DRIVESWEEP_SETUP_EXE -ArgumentList $a -ErrorAction Stop } "
                "catch { & $env:DRIVESWEEP_SETUP_EXE $a }"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
                env=env,
                creationflags=no_window_flags,
                close_fds=True,
            )
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
