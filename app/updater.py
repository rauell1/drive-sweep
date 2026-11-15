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

from app import __version__

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


def pick_release_asset(assets: list[dict], install_kind: str) -> dict | None:
    """Choose the best downloadable Windows asset for the current installation type."""
    valid = [a for a in assets if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")]
    setup_assets = [
        a for a in valid
        if a["name"].lower().endswith(".exe") and "setup" in a["name"].lower()
    ]
    portable_assets = [
        a for a in valid
        if a["name"].lower() == "drivesweep.exe"
    ]
    if install_kind == "onefile_exe" and portable_assets:
        return portable_assets[0]
    if setup_assets:
        return setup_assets[0]
    if portable_assets:
        return portable_assets[0]
    return None


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
) -> dict:
    """Download an official release binary and verify its SHA-256 against SHA256SUMS.txt."""
    safe_name = os.path.basename(str(asset_name or "")).strip()
    if not safe_name or not safe_name.lower().endswith(".exe"):
        return {"ok": False, "error": "Unsupported update file type."}
    if not verify_https_github_url(asset_url) or not verify_https_github_url(sha256_url):
        return {"ok": False, "error": "Update URL must use HTTPS on GitHub."}

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

    hasher = hashlib.sha256()
    try:
        dl_req = urllib.request.Request(asset_url, headers={"User-Agent": f"DriveSweep/{__version__}"})
        with urllib.request.urlopen(dl_req, timeout=timeout) as resp, open(dest_path, "wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                hasher.update(chunk)
                fh.write(chunk)
    except Exception as exc:
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return {"ok": False, "error": f"Download failed: {exc}"}

    actual_hash = hasher.hexdigest().lower()
    if actual_hash != expected_hash:
        dest_path.unlink(missing_ok=True)
        return {"ok": False, "error": "SHA-256 verification failed. Update file was removed."}

    return {"ok": True, "file_path": str(dest_path), "sha256": actual_hash}


def launch_downloaded_update(file_path: str, install_kind: str | None = None) -> dict:
    """Launch verified Setup installer cleanly or swap portable executable after exit."""
    target = Path(file_path)
    if not target.exists():
        return {"ok": False, "error": "Downloaded update file does not exist."}

    kind = install_kind or detect_install_kind()
    name_lower = target.name.lower()

    if sys.platform != "win32":
        return {"ok": False, "error": "Self-install updates are currently supported on Windows."}

    try:
        if "setup" in name_lower and name_lower.endswith(".exe"):
            subprocess.Popen(
                [str(target), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
                close_fds=True,
            )
            return {"ok": True, "should_exit": True, "mode": "setup"}

        if kind == "onefile_exe" and getattr(sys, "frozen", False):
            env = os.environ.copy()
            env["DRIVESWEEP_OLD_EXE"] = str(Path(sys.executable).resolve())
            env["DRIVESWEEP_NEW_EXE"] = str(target.resolve())
            env["DRIVESWEEP_PID"] = str(os.getpid())
            ps_script = (
                "$p=[int]$env:DRIVESWEEP_PID; "
                "while (Get-Process -Id $p -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 250 }; "
                "Move-Item -Force -Path $env:DRIVESWEEP_NEW_EXE -Destination $env:DRIVESWEEP_OLD_EXE; "
                "Start-Process -FilePath $env:DRIVESWEEP_OLD_EXE"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
                env=env,
                close_fds=True,
            )
            return {"ok": True, "should_exit": True, "mode": "portable_swap"}

        subprocess.Popen([str(target)], close_fds=True)
        return {"ok": True, "should_exit": True, "mode": "launch"}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to start installer: {exc}"}
