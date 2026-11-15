"""Windows system space inspection, Recycle Bin management, old installers, and DISM helpers."""

from __future__ import annotations

import ctypes
import os
import re
import string
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from .safety import format_bytes, is_admin, sanitized_subprocess_env

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_SHERB_NOCONFIRMATION = 0x00000001
_SHERB_NOPROGRESSUI = 0x00000002
_SHERB_NOSOUND = 0x00000004
_INSTALLER_EXTS = {".exe", ".msi", ".msix", ".msixbundle", ".iso", ".zip", ".7z", ".rar", ".cab"}


class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_int64),
        ("i64NumItems", ctypes.c_int64),
    ]


def get_recycle_bin_info(root_path: str | None = None) -> dict:
    """Query Recycle Bin total size and item count via SHQueryRecycleBinW."""
    if os.name != "nt":
        return {"supported": False, "size_bytes": 0, "size_human": "0 B", "item_count": 0}
    try:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        hr = ctypes.windll.shell32.SHQueryRecycleBinW(root_path, ctypes.byref(info))
        if hr != 0:
            return {
                "supported": True,
                "size_bytes": 0,
                "size_human": "0 B",
                "item_count": 0,
                "hresult": int(hr),
            }
        size = max(0, int(info.i64Size))
        items = max(0, int(info.i64NumItems))
        return {
            "supported": True,
            "size_bytes": size,
            "size_human": format_bytes(size),
            "item_count": items,
        }
    except Exception as exc:
        return {
            "supported": False,
            "size_bytes": 0,
            "size_human": "0 B",
            "item_count": 0,
            "error": str(exc),
        }


def empty_recycle_bin(root_path: str | None = None) -> dict:
    """Empty the Windows Recycle Bin silently after explicit UI confirmation."""
    if os.name != "nt":
        return {"ok": False, "error": "Recycle Bin cleanup is only supported on Windows."}
    before = get_recycle_bin_info(root_path)
    before_bytes = int(before.get("size_bytes", 0) or 0)
    before_items = int(before.get("item_count", 0) or 0)
    if before_bytes == 0 and before_items == 0:
        return {
            "ok": True,
            "already_empty": True,
            "freed_bytes": 0,
            "freed_human": "0 B",
            "items_removed": 0,
        }
    try:
        flags = _SHERB_NOCONFIRMATION | _SHERB_NOPROGRESSUI | _SHERB_NOSOUND
        hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, root_path, flags)
        # 0 is S_OK; -2147418113 (0x8000FFFF) can happen when already empty
        if hr not in (0, -2147418113):
            return {
                "ok": False,
                "error": f"Windows returned error code {hr} while emptying the Recycle Bin.",
                "hresult": int(hr),
            }
        after = get_recycle_bin_info(root_path)
        after_bytes = int(after.get("size_bytes", 0) or 0)
        freed = max(0, before_bytes - after_bytes)
        return {
            "ok": True,
            "already_empty": False,
            "freed_bytes": freed,
            "freed_human": format_bytes(freed),
            "items_removed": max(0, before_items - int(after.get("item_count", 0) or 0)),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def open_recycle_bin_folder() -> dict:
    """Open the Windows Recycle Bin in File Explorer so users can restore files."""
    if os.name != "nt":
        return {"ok": False, "error": "Recycle Bin folder is only available on Windows."}
    try:
        subprocess.Popen(
            ["explorer.exe", "shell:RecycleBinFolder"],
            env=sanitized_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def find_old_download_installers(
    max_age_days: int = 30,
    downloads_dir: str | Path | None = None,
    *,
    max_items: int = 200,
) -> dict:
    """Find old installer packages and archives in Downloads (read-only discovery)."""
    target_dir = Path(downloads_dir) if downloads_dir else (Path.home() / "Downloads")
    if not target_dir.exists() or not target_dir.is_dir():
        return {
            "directory": str(target_dir),
            "exists": False,
            "max_age_days": max_age_days,
            "count": 0,
            "total_bytes": 0,
            "total_human": "0 B",
            "items": [],
        }

    cutoff = time.time() - max(1, int(max_age_days)) * 86400
    now = time.time()
    found: list[dict] = []

    try:
        with os.scandir(target_dir) as it:
            for entry in it:
                try:
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext not in _INSTALLER_EXTS:
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if st.st_mtime > cutoff or st.st_size <= 0:
                        continue
                    age_days = max(1, int((now - st.st_mtime) // 86400))
                    found.append(
                        {
                            "path": entry.path,
                            "name": entry.name,
                            "ext": ext,
                            "size_bytes": int(st.st_size),
                            "size_human": format_bytes(st.st_size),
                            "age_days": age_days,
                            "mtime": float(st.st_mtime),
                        }
                    )
                except OSError:
                    continue
    except OSError:
        pass

    found.sort(key=lambda item: item["size_bytes"], reverse=True)
    limited = found[:max_items]
    total_bytes = sum(item["size_bytes"] for item in found)
    return {
        "directory": str(target_dir),
        "exists": True,
        "max_age_days": int(max_age_days),
        "count": len(found),
        "total_bytes": total_bytes,
        "total_human": format_bytes(total_bytes),
        "items": limited,
    }


def find_hibernation_info(system_drive: str | None = None) -> dict:
    """Check whether Windows hiberfil.sys is present and how much space it uses."""
    if os.name != "nt":
        return {"present": False, "path": "", "size_bytes": 0, "size_human": "0 B"}
    drive = (system_drive or os.environ.get("SystemDrive") or "C:").rstrip("\\/") + "\\"
    hiber_path = os.path.join(drive, "hiberfil.sys")
    try:
        st = os.stat(hiber_path)
        return {
            "present": True,
            "path": hiber_path,
            "size_bytes": int(st.st_size),
            "size_human": format_bytes(st.st_size),
            "command_hint": "powercfg /hibernate off",
        }
    except OSError:
        return {"present": False, "path": hiber_path, "size_bytes": 0, "size_human": "0 B"}


def find_wsl_docker_vhdx(
    local_app_data: str | Path | None = None,
    program_data: str | Path | None = None,
) -> dict:
    """Locate WSL2 and Docker Desktop virtual disk (.vhdx) files for inspection."""
    roots: list[Path] = []
    local = Path(local_app_data) if local_app_data else Path(os.environ.get("LOCALAPPDATA", ""))
    pdata = Path(program_data) if program_data else Path(os.environ.get("ProgramData", ""))

    if str(local):
        for sub in ("Docker", "Packages", "wsl"):
            candidate = local / sub
            if candidate.exists():
                roots.append(candidate)
    if str(pdata):
        candidate = pdata / "DockerDesktop"
        if candidate.exists():
            roots.append(candidate)

    vhdx_items: list[dict] = []
    seen: set[str] = set()
    for root in roots:
        # Bounded depth walk (max 5 levels) so startup inspection stays sub-second
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            if depth > 5:
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append((Path(entry.path), depth + 1))
                            elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".vhdx"):
                                norm = os.path.normcase(os.path.abspath(entry.path))
                                if norm in seen:
                                    continue
                                seen.add(norm)
                                st = entry.stat(follow_symlinks=False)
                                vhdx_items.append(
                                    {
                                        "path": entry.path,
                                        "name": entry.name,
                                        "parent": os.path.basename(os.path.dirname(entry.path)),
                                        "size_bytes": int(st.st_size),
                                        "size_human": format_bytes(st.st_size),
                                    }
                                )
                        except OSError:
                            continue
            except OSError:
                continue

    vhdx_items.sort(key=lambda item: item["size_bytes"], reverse=True)
    total_bytes = sum(item["size_bytes"] for item in vhdx_items)
    return {
        "count": len(vhdx_items),
        "total_bytes": total_bytes,
        "total_human": format_bytes(total_bytes),
        "items": vhdx_items[:30],
    }


def _get_per_drive_recycle_bins() -> list[dict]:
    if os.name != "nt":
        return []
    drives: list[dict] = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            try:
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
            except Exception:
                dtype = 0
            if dtype in (2, 3):  # removable or fixed
                info = get_recycle_bin_info(root)
                if info.get("size_bytes", 0) > 0 or info.get("item_count", 0) > 0:
                    drives.append({"drive": root, **info})
    return drives


def inspect_system_space(max_installer_age_days: int = 30) -> dict:
    """Return a consolidated overview of Windows Recycle Bin, old installers, hiberfil, and WSL2/Docker VHDX."""
    return {
        "is_admin": is_admin(),
        "recycle_bin": get_recycle_bin_info(),
        "recycle_bin_drives": _get_per_drive_recycle_bins(),
        "old_installers": find_old_download_installers(max_age_days=max_installer_age_days),
        "hibernation": find_hibernation_info(),
        "virtual_disks": find_wsl_docker_vhdx(),
    }


def parse_dism_analyze_output(output: str) -> dict:
    """Extract clean human-readable fields from DISM /AnalyzeComponentStore output."""
    text = output or ""
    result = {
        "component_store_size": "",
        "reclaimable_packages": "",
        "backups_and_disabled": "",
        "cache_and_temp": "",
        "cleanup_recommended": False,
        "raw": text.strip(),
    }
    patterns = {
        "component_store_size": r"Windows Explorer Reported Size of Component Store\s*:\s*(.+)",
        "reclaimable_packages": r"Number of Reclaimable Packages\s*:\s*(.+)",
        "backups_and_disabled": r"Backups and Disabled Features\s*:\s*(.+)",
        "cache_and_temp": r"Cache and Temporary Data\s*:\s*(.+)",
    }
    for key, pat in patterns.items():
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            result[key] = match.group(1).strip()

    rec_match = re.search(r"Component Store Cleanup Recommended\s*:\s*(Yes|No)", text, flags=re.IGNORECASE)
    if rec_match:
        result["cleanup_recommended"] = rec_match.group(1).strip().lower() == "yes"
    return result


def analyze_winsxs() -> dict:
    """Inspect Windows WinSxS component store using DISM (Administrator required)."""
    if os.name != "nt":
        return {"ok": False, "error": "WinSxS analysis is only supported on Windows."}
    if not is_admin():
        return {
            "ok": False,
            "requires_admin": True,
            "error": "Administrator rights are required to run DISM component store analysis.",
        }
    try:
        proc = subprocess.run(
            ["dism.exe", "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"],
            capture_output=True,
            text=True,
            timeout=180,
            env=sanitized_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        parsed = parse_dism_analyze_output(combined)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            **parsed,
            "error": "" if proc.returncode == 0 else (proc.stderr or proc.stdout or f"DISM exited with code {proc.returncode}").strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "DISM analysis timed out after 3 minutes."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_winsxs_cleanup() -> dict:
    """Run Windows DISM /StartComponentCleanup to reclaim superseded Windows update files."""
    if os.name != "nt":
        return {"ok": False, "error": "WinSxS cleanup is only supported on Windows."}
    if not is_admin():
        return {
            "ok": False,
            "requires_admin": True,
            "error": "Administrator rights are required to clean Windows Update components.",
        }
    try:
        proc = subprocess.run(
            ["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
            capture_output=True,
            text=True,
            timeout=600,
            env=sanitized_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": combined,
            "error": "" if proc.returncode == 0 else (proc.stderr or proc.stdout or f"DISM exited with code {proc.returncode}").strip(),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "DISM cleanup timed out after 10 minutes."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
