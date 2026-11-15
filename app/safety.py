"""Safety guards, Windows long-path helpers, elevation check, and deletion execution."""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

from send2trash import send2trash

_KNOWN_FOLDER_GUIDS: dict[str, tuple[str, str]] = {
    "downloads": ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads"),
    "documents": ("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}", "Documents"),
    "desktop": ("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Desktop"),
    "pictures": ("{33E28130-4E1E-4676-835A-98395C3BC3BB}", "Pictures"),
    "music": ("{4BD8D571-6D19-48D3-BE97-422220080E43}", "Music"),
    "videos": ("{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Videos"),
}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


@lru_cache(maxsize=16)
def get_known_folder_path(folder_key: str) -> Path:
    """Resolve redirected Windows Known Folders (e.g., D:\\Downloads or OneDrive\\Desktop)."""
    key = folder_key.lower()
    guid_str, default_name = _KNOWN_FOLDER_GUIDS.get(key, ("", folder_key))
    fallback = Path.home() / default_name
    if os.name != "nt" or not guid_str:
        return fallback
    try:
        u = uuid.UUID(guid_str)
        guid = _GUID(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))
        ptr = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(ptr))
        try:
            if hr == 0 and ptr.value:
                resolved = Path(ptr.value)
                if resolved.exists():
                    return resolved
        finally:
            if ptr.value:
                ctypes.windll.ole32.CoTaskMemFree(ptr)
    except Exception:
        pass
    return fallback


def get_all_personal_roots() -> list[tuple[str, Path]]:
    """Return unique (space_label, path) pairs for all user personal/cloud folders."""
    seen: set[str] = set()
    roots: list[tuple[str, Path]] = []

    def _add(label: str, cand: Path) -> None:
        try:
            if not cand or not cand.exists():
                return
            norm = os.path.normcase(os.path.abspath(str(cand)))
            if norm in seen:
                return
            seen.add(norm)
            roots.append((label, cand))
        except OSError:
            pass

    for key, label in (
        ("downloads", "Downloads"),
        ("desktop", "Desktop"),
        ("documents", "Documents"),
        ("videos", "Videos"),
        ("pictures", "Pictures"),
        ("music", "Music"),
    ):
        _add(label, get_known_folder_path(key))
        _add(label, Path.home() / label)

    for env_key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        val = os.environ.get(env_key)
        if val:
            _add("OneDrive", Path(val))
    _add("OneDrive", Path.home() / "OneDrive")
    return roots


def format_bytes(num_bytes: int | float) -> str:
    """Format a byte count into a human-readable string."""
    size = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def to_os_path(raw_path: str | Path) -> str:
    """Return an OS-safe path string, applying Windows \\\\?\\ prefix for long paths."""
    p = os.path.abspath(os.path.normpath(str(raw_path)))
    if os.name == "nt" and len(p) >= 240 and not p.startswith("\\\\?\\"):
        if p.startswith("\\\\"):
            return "\\\\?\\UNC\\" + p.lstrip("\\")
        return "\\\\?\\" + p
    return p


def strip_long_prefix(path_str: str) -> str:
    """Remove Windows \\\\?\\ extended prefix for clean display and normpath."""
    if path_str.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path_str[8:]
    if path_str.startswith("\\\\?\\"):
        return path_str[4:]
    return path_str


def _normalize(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.normpath(strip_long_prefix(str(path)))))


def _is_same_or_child(path: Path, parent: Path) -> bool:
    try:
        path_norm = os.path.normcase(str(path))
        parent_norm = os.path.normcase(str(parent))
        if path_norm == parent_norm:
            return True
        return path_norm.startswith(parent_norm.rstrip("\\/") + os.sep)
    except Exception:
        return False


def is_admin() -> bool:
    """Return True if the current process has Administrator/root privileges."""
    try:
        if os.name == "nt":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


_PYI_ENV_EXACT = {"_MEIPASS2"}


def sanitized_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of os.environ without PyInstaller onefile bootloader markers.

    PyInstaller 6+ onefile executables fail with 'invalid originating onefile parent
    process (PID not found)' if spawned by a child of an already-exited onefile app
    that inherited _PYI_PARENT_PROCESS_LEVEL / _PYI_* environment variables.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("_PYI_") and k not in _PYI_ENV_EXACT
    }
    if extra:
        env.update(extra)
    return env


def relaunch_as_admin() -> dict:
    """Prompt UAC elevation to restart DriveSweep with Administrator rights on Windows."""
    if os.name != "nt":
        return {"ok": False, "error": "Elevation prompt is only implemented for Windows."}
    if is_admin():
        return {"ok": True, "already_admin": True}
    removed: dict[str, str] = {}
    for key in list(os.environ.keys()):
        if key.startswith("_PYI_") or key in _PYI_ENV_EXACT:
            removed[key] = os.environ.pop(key)
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = subprocess.list2cmdline(sys.argv[1:])
        else:
            exe = sys.executable
            params = subprocess.list2cmdline(sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if rc <= 32:
            os.environ.update(removed)
            return {"ok": False, "error": f"Elevation cancelled or failed (code {rc})."}
        return {"ok": True, "launching": True}
    except Exception as exc:
        os.environ.update(removed)
        return {"ok": False, "error": str(exc)}


def _windows_protected_roots() -> list[Path]:
    system_drive = os.environ.get("SystemDrive", "C:") + "\\"
    windir = Path(os.environ.get("WINDIR", os.path.join(system_drive, "Windows")))
    prog_files = Path(os.environ.get("ProgramFiles", os.path.join(system_drive, "Program Files")))
    prog_files_x86 = Path(
        os.environ.get("ProgramFiles(x86)", os.path.join(system_drive, "Program Files (x86)"))
    )
    program_data = Path(os.environ.get("ProgramData", os.path.join(system_drive, "ProgramData")))
    return [
        windir,
        prog_files,
        prog_files_x86,
        program_data / "Microsoft",
    ]


def is_os_protected_path(raw_path: str | Path, *, allow_temp_contents: bool = False) -> bool:
    """Return True if deleting this path could damage the OS or drive metadata."""
    p = _normalize(raw_path)

    # Never delete filesystem/drive roots (e.g., C:\, D:\, /)
    if p == p.parent or len(p.parts) <= 1:
        return True

    if os.name == "nt":
        windir = Path(os.environ.get("WINDIR", "C:\\Windows"))
        program_data = Path(os.environ.get("ProgramData", os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "ProgramData")))
        safe_system_caches = (
            _normalize(windir / "Temp"),
            _normalize(windir / "SoftwareDistribution" / "Download"),
            _normalize(
                windir
                / "ServiceProfiles"
                / "NetworkService"
                / "AppData"
                / "Local"
                / "Microsoft"
                / "Windows"
                / "DeliveryOptimization"
                / "Cache"
            ),
            _normalize(windir / "Minidump"),
            _normalize(windir / "LiveKernelReports"),
            _normalize(windir / "Logs" / "CBS"),
            _normalize(windir / "Logs" / "DISM"),
            _normalize(program_data / "Microsoft" / "Windows" / "WER" / "ReportArchive"),
            _normalize(program_data / "Microsoft" / "Windows" / "WER" / "ReportQueue"),
        )

        # Allow cleaning items *inside* safe Windows cache/temp folders (or the folder when contents_only=True)
        for cache_root in safe_system_caches:
            if allow_temp_contents and p == cache_root:
                return False
            if _is_same_or_child(p, cache_root) and p != cache_root:
                return False

        # Protected drive-root system entries on any drive
        name_lower = p.name.lower()
        if name_lower in {
            "$recycle.bin",
            "system volume information",
            "pagefile.sys",
            "hiberfil.sys",
            "swapfile.sys",
            "bootmgr",
            "bootnxt",
        }:
            return True

        if len(p.parts) == 2 and name_lower in {"recovery", "boot", "$winreagent"}:
            return True

        for root in _windows_protected_roots():
            if _is_same_or_child(p, _normalize(root)):
                return True

        home = _normalize(Path.home())
        if p in (home, home / "AppData", home / "AppData" / "Local", home / "AppData" / "Roaming"):
            return True
    else:
        for root in ("/System", "/usr", "/bin", "/sbin", "/etc", "/lib", "/lib64", "/var", "/boot", "/dev", "/proc", "/sys"):
            if _is_same_or_child(p, Path(root)):
                return True
        if p == _normalize(Path.home()):
            return True

    return False


class ScanGuard:
    """Precomputed fast path-prefix guard used during multithreaded drive scans."""

    __slots__ = (
        "is_nt",
        "protected_prefixes",
        "win_temp_exact",
        "win_temp_prefix",
        "home_exact_set",
        "personal_prefixes",
    )

    def __init__(self) -> None:
        self.is_nt = os.name == "nt"
        home = _normalize(Path.home())
        if self.is_nt:
            windir = _normalize(os.environ.get("WINDIR", "C:\\Windows"))
            win_temp = _normalize(windir / "Temp")
            self.win_temp_exact = os.path.normcase(str(win_temp))
            self.win_temp_prefix = self.win_temp_exact.rstrip("\\/") + os.sep
            roots = [_normalize(r) for r in _windows_protected_roots()]
            self.protected_prefixes = tuple(
                os.path.normcase(str(r)).rstrip("\\/") + os.sep for r in roots
            )
            protected_exacts = tuple(os.path.normcase(str(r)) for r in roots)
            home_targets = (
                home,
                home / "AppData",
                home / "AppData" / "Local",
                home / "AppData" / "Roaming",
            )
            self.home_exact_set = frozenset(
                os.path.normcase(str(h)) for h in home_targets
            ) | frozenset(protected_exacts)
        else:
            self.win_temp_exact = ""
            self.win_temp_prefix = ""
            roots = (
                "/System", "/usr", "/bin", "/sbin", "/etc", "/lib",
                "/lib64", "/var", "/boot", "/dev", "/proc", "/sys",
            )
            self.protected_prefixes = tuple(r.rstrip("/") + "/" for r in roots)
            self.home_exact_set = frozenset({str(home), *roots})

        personal_names = (
            "Downloads", "OneDrive", "CrossDevice", "Documents",
            "Desktop", "Pictures", "Music", "Videos",
        )
        pref_set: list[str] = [
            os.path.normcase(str(home / name)).rstrip("\\/") + os.sep
            for name in personal_names
        ]
        if self.is_nt:
            for _lbl, p_root in get_all_personal_roots():
                pref = os.path.normcase(os.path.abspath(str(p_root))).rstrip("\\/") + os.sep
                if pref not in pref_set:
                    pref_set.append(pref)
        self.personal_prefixes = tuple(pref_set)

    def check_dir(
        self,
        raw_path: str,
        name_lower: str,
        parent_protected: bool = False,
        parent_personal: bool = False,
    ) -> tuple[bool, bool]:
        """Return (is_protected, is_personal) using fast string ops and parent inheritance."""
        norm = os.path.normcase(raw_path)

        # Personal folder check (monotonic downward)
        if parent_personal or name_lower in {"downloads", "onedrive", "crossdevice"}:
            is_personal = True
        else:
            norm_slash = norm + os.sep
            is_personal = norm_slash.startswith(self.personal_prefixes)

        # OS protected check (inherits unless path is inside Windows\Temp)
        if parent_protected and not (
            self.win_temp_exact
            and (
                norm == self.win_temp_exact
                or self.win_temp_exact.startswith(norm + os.sep)
                or norm.startswith(self.win_temp_prefix)
            )
        ):
            return True, is_personal

        if self.is_nt:
            if norm == self.win_temp_exact or norm in self.home_exact_set:
                return True, is_personal
            if norm.startswith(self.win_temp_prefix):
                return False, is_personal
            if name_lower in {
                "$recycle.bin",
                "system volume information",
                "pagefile.sys",
                "hiberfil.sys",
                "swapfile.sys",
                "bootmgr",
                "bootnxt",
            }:
                return True, is_personal
            # Root-level recovery/boot/$winreagent (e.g., C:\Recovery)
            if len(norm) >= 3 and norm[1:3] == ":\\" and norm.count("\\") == 1:
                if name_lower in {"recovery", "boot", "$winreagent"}:
                    return True, is_personal
            if norm.startswith(self.protected_prefixes):
                return True, is_personal
            return False, is_personal

        if norm in self.home_exact_set or norm.startswith(self.protected_prefixes):
            return True, is_personal
        return False, is_personal


def is_personal_guarded_path(raw_path: str | Path) -> bool:
    """Return True if path is inside user's personal folders excluded from Smart Scan."""
    p = _normalize(raw_path)
    home = _normalize(Path.home())
    personal_names = ("Downloads", "OneDrive", "CrossDevice", "Documents", "Desktop", "Pictures", "Music", "Videos")
    for name in personal_names:
        if _is_same_or_child(p, home / name):
            return True
    if os.name == "nt":
        for _lbl, root in get_all_personal_roots():
            if _is_same_or_child(p, _normalize(root)):
                return True
    lowered_parts = {part.lower() for part in p.parts}
    return bool(lowered_parts & {"downloads", "onedrive", "crossdevice"})


CAUTION_DIR_NAMES = {".git", ".ssh", ".gnupg", ".aws", ".kube"}
CAUTION_EXTENSIONS = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pst",
    ".ost",
    ".vhdx",
    ".vhd",
    ".vmdk",
    ".exe",
    ".msi",
    ".dll",
    ".sys",
    ".env",
    ".pem",
    ".key",
}


def explain_path_human(
    raw_path: str | Path,
    *,
    is_dir: bool = False,
    age_days: int | None = None,
    is_dev_bloat: bool = False,
    base_level: str = "safe",
    base_reason: str = "",
) -> str:
    """Return a concise, plain-English explanation of what a file or folder is and whether removing it is safe."""
    if base_level == "critical":
        return base_reason or "Critical OS or system folder/file. Locked to protect your system."

    p = _normalize(raw_path)
    full_lower = str(p).lower().replace("/", "\\")
    name_lower = p.name.lower()
    ext = "" if is_dir else p.suffix.lower()
    in_downloads = "\\downloads\\" in full_lower or full_lower.endswith("\\downloads")
    parts_lower = [part.lower() for part in p.parts]

    # Virtual disks (never auto-delete; shrink via Windows Tools instead)
    if ext in {".vhdx", ".vhd", ".vmdk", ".vdi"}:
        if "docker" in full_lower or "wsl" in full_lower:
            return "Linux or Docker virtual disk. Do not delete directly; use Windows Tools > Shrink Disk to reclaim unused space."
        return "Virtual machine disk image. Contains a full virtual computer; only delete if you no longer use that VM."

    # Repository / credential guards
    if name_lower in CAUTION_DIR_NAMES or any(part in CAUTION_DIR_NAMES for part in parts_lower):
        if name_lower == ".git" or ".git" in parts_lower:
            return "Git version history folder. Only delete if you do not need local commit history or branches."
        return "Sensitive configuration or credentials folder (.ssh, .aws, etc.). Keep unless you no longer need these keys."

    # Developer dependency & build caches
    if is_dir or is_dev_bloat:
        if name_lower == "node_modules":
            age_note = f" Inactive for {age_days} days." if age_days is not None and age_days >= 30 else ""
            return f"JavaScript packages for a project.{age_note} Safe to delete if inactive; restore anytime with npm or pnpm install."
        if name_lower in {".venv", "venv"}:
            return "Python virtual environment. Safe to delete if inactive; recreate anytime from requirements or pyproject."
        if name_lower in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox"}:
            return "Python bytecode or test cache. Safe to delete; Python recreates it automatically."
        if name_lower in {".next", ".nuxt", ".turbo", ".parcel-cache", ".angular", ".svelte-kit"}:
            return "Web framework build cache. Safe to delete; rebuilt automatically on your next build."
        if name_lower in {".gradle", "target"}:
            return "Compiled build cache folder. Safe to delete if inactive; rebuilt on your next project build."
        if is_dev_bloat:
            if age_days is not None and age_days < 30:
                return f"Active project dependency folder (modified {age_days} day(s) ago). Recreated by your package manager if removed."
            return "Project dependency or build cache folder. Safe to delete if inactive; your build tool can reinstall it."

    # Global package & AI model caches
    if "\\huggingface\\hub" in full_lower or full_lower.endswith("\\huggingface\\hub") or "\\huggingface\\" in full_lower:
        return "Downloaded Hugging Face AI models. Safe to delete; models re-download automatically when needed."
    if "\\.ollama\\" in full_lower or "\\ollama\\models" in full_lower:
        return "Downloaded Ollama local AI models. Safe to delete if you no longer run these local models."
    if "\\pip\\cache" in full_lower or "\\uv\\cache" in full_lower or "\\uv\\archive" in full_lower:
        return "Cached Python package downloads. Safe to delete; pip or uv will re-download only when needed."
    if "\\npm-cache" in full_lower or "\\pnpm\\store" in full_lower or "\\yarn\\cache" in full_lower:
        return "Cached JavaScript packages. Safe to delete; your package manager re-fetches packages as needed."
    if "\\.cargo\\registry" in full_lower or "\\.cargo\\git" in full_lower:
        return "Cached Rust crates. Safe to delete; Cargo re-downloads dependencies on your next build."
    if "\\.nuget\\packages" in full_lower:
        return "Cached .NET NuGet packages. Safe to delete; Visual Studio or dotnet restore re-downloads them if needed."

    # GPU & game caches
    if any(tok in full_lower for tok in ("\\nv_cache", "\\dxcache", "\\glcache", "\\d3dscache", "\\shadercache", "\\amd\\dxcache")):
        return "Compiled graphics shader cache. Safe to delete; Windows and games rebuild shaders automatically."
    if "\\steamapps\\downloading" in full_lower or "\\steamapps\\temp" in full_lower:
        return "Incomplete Steam download cache. Safe to delete when Steam is closed."
    if "\\steamapps\\common" in full_lower:
        return "Installed Steam game files. Uninstall via Steam first, or delete if the game was already removed."

    # Windows update & crash logs
    if "\\windows.old" in full_lower or name_lower == "windows.old":
        return "Previous Windows version backup. Safe to remove if your current Windows update is working well."
    if "\\softwaredistribution\\download" in full_lower:
        return "Downloaded Windows Update installers. Safe to delete; Windows re-downloads any pending updates."
    if ext == ".dmp" or any(tok in full_lower for tok in ("\\crashdumps", "\\minidump", "\\reportarchive", "\\reportqueue")):
        return "Diagnostic crash dump or error report. Safe to delete unless troubleshooting a recent crash."

    # Browser & desktop app cache folders
    if is_dir and any(tok in name_lower for tok in ("cache", "gpucache", "code cache", "cachestorage")):
        return "Temporary browser or app cache. Safe to delete; the app regenerates it automatically."

    # File-type friendly hints (especially inside Downloads / user spaces)
    if not is_dir:
        if ext in {".iso", ".img"}:
            if in_downloads:
                return "Downloaded disk image or OS installer. Safe to delete if you no longer need the installer."
            return "Disk image file. Usually an installer or backup; check if you still need it before deleting."
        if ext in {".msi", ".msix", ".msixbundle", ".exe"}:
            if in_downloads:
                return "Downloaded setup installer. Safe to delete if you have already installed this app."
            return "Windows program or installer file. Keep if part of an installed app; delete old downloaded setups."
        if ext in {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz"}:
            if in_downloads:
                return "Downloaded archive file. Safe to delete if you have already extracted or moved its contents."
            return "Compressed archive file. Check whether you already extracted or backed up what is inside."
        if ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv"}:
            return "Video or screen recording file. Review before deleting to make sure you do not want to keep it."
        if ext in {".pst", ".ost"}:
            return "Outlook email archive file. Deleting removes offline cached mail for that profile."
        if ext in {".db", ".sqlite", ".sqlite3", ".mdb"}:
            return "Application database file. Review carefully; deleting may reset local app history or saved data."
        if ext in {".log", ".tmp", ".temp", ".bak", ".old"}:
            return "Temporary, backup, or log file. Safe to remove once related programs are closed."
        if ext in {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls"}:
            return "Personal document or spreadsheet. Keep unless you are sure it is no longer needed."

    if in_downloads:
        return "File or folder inside Downloads. Review first; safe to remove if you already used or saved it elsewhere."

    return base_reason or "Standard file or regenerable folder."


def classify_path_risk(
    raw_path: str | Path,
    *,
    is_dir: bool = False,
    age_days: int | None = None,
    is_dev_bloat: bool = False,
) -> dict:
    """Classify criticality of a file/folder: 'critical', 'caution', or 'safe'."""
    p = _normalize(raw_path)
    if is_os_protected_path(p):
        return {
            "risk_level": "critical",
            "risk_reason": "Critical OS or system folder/file. Locked to protect your system.",
        }

    name_lower = p.name.lower()
    base_level = "safe"
    base_reason = "Standard file or regenerable folder."

    if is_personal_guarded_path(p):
        base_level = "caution"
        base_reason = "Personal user folder/file (Downloads, OneDrive, Documents, etc.). Confirm before deleting."
    elif name_lower in CAUTION_DIR_NAMES or any(part.lower() in CAUTION_DIR_NAMES for part in p.parts):
        base_level = "caution"
        base_reason = "Contains repository history or credentials (.git, .ssh, etc.)."
    elif not is_dir and (p.suffix.lower() in CAUTION_EXTENSIONS or name_lower.startswith(".env")):
        ext = p.suffix.lower()
        base_level = "caution"
        base_reason = f"Sensitive, executable, database, or virtual disk file ({ext or name_lower})."
    elif is_dev_bloat and age_days is not None and age_days < 30:
        base_level = "caution"
        base_reason = f"Active project dependency folder (modified {age_days} day(s) ago)."

    return {
        "risk_level": base_level,
        "risk_reason": explain_path_human(
            p,
            is_dir=is_dir,
            age_days=age_days,
            is_dev_bloat=is_dev_bloat,
            base_level=base_level,
            base_reason=base_reason,
        ),
    }


def deduplicate_targets(targets: Iterable[dict]) -> list[dict]:
    """Remove redundant child targets when a parent folder is already selected."""
    normalized: list[tuple[str, dict]] = []
    for item in targets:
        raw_path = item.get("path", "")
        if not raw_path:
            continue
        clean_path = str(_normalize(raw_path))
        norm_key = os.path.normcase(clean_path)
        normalized.append((
            norm_key,
            {"path": clean_path, "contents_only": bool(item.get("contents_only", False))},
        ))

    # Sort shallowest paths first so parents precede children
    normalized.sort(key=lambda pair: (pair[0].count(os.sep), len(pair[0])))

    kept: list[tuple[str, dict]] = []
    for norm_key, payload in normalized:
        covered = False
        for parent_key, _parent_payload in kept:
            if norm_key == parent_key:
                covered = True
                break
            if norm_key.startswith(parent_key.rstrip("\\/") + os.sep):
                covered = True
                break
        if not covered:
            kept.append((norm_key, payload))

    return [payload for _, payload in kept]


def _handle_remove_readonly(func, path: str, _exc_info) -> None:
    os_path = to_os_path(path)
    os.chmod(os_path, stat.S_IWRITE)
    func(os_path)


def _permanent_delete_entry(target: Path) -> None:
    os_target = to_os_path(target)
    if os.path.islink(os_target) or os.path.isfile(os_target):
        try:
            os.unlink(os_target)
        except PermissionError:
            os.chmod(os_target, stat.S_IWRITE)
            os.unlink(os_target)
    elif os.path.isdir(os_target):
        shutil.rmtree(os_target, onerror=_handle_remove_readonly)


def _recycle_entry(target: Path) -> None:
    path_str = str(target)
    if os.name == "nt" and len(path_str) >= 255:
        raise OSError(
            "Path exceeds Windows 255-char Recycle Bin limit. Use Permanent Delete for this item."
        )
    send2trash(path_str)


def get_entry_size(raw_path: str | Path) -> int:
    """Compute byte size of a file or directory safely (supports long Windows paths)."""
    os_p = to_os_path(raw_path)
    if not os.path.lexists(os_p):
        return 0
    if os.path.islink(os_p):
        return 0
    if os.path.isfile(os_p):
        try:
            return os.stat(os_p, follow_symlinks=False).st_size
        except OSError:
            return 0

    total = 0
    stack = [os_p]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return total


@dataclass
class DeleteResult:
    mode: str
    freed_bytes: int
    deleted_count: int
    deleted: list[dict]
    failed: list[dict]
    cancelled: bool = False


def delete_targets(
    targets: Iterable[dict],
    mode: str = "recycle",
    progress_cb: Callable[[int, int, str, int], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> DeleteResult:
    """Delete selected files/directories via Recycle Bin or Permanent Delete."""
    if mode not in ("recycle", "permanent"):
        raise ValueError(f"Invalid delete mode: {mode}")

    deduped = deduplicate_targets(targets)
    total_items = len(deduped)
    delete_fn = _recycle_entry if mode == "recycle" else _permanent_delete_entry
    deleted: list[dict] = []
    failed: list[dict] = []
    freed_bytes = 0
    cancelled = False

    for idx, item in enumerate(deduped):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        raw_path = item["path"]
        contents_only = item["contents_only"]
        target = _normalize(raw_path)
        os_target = to_os_path(target)
        if progress_cb is not None:
            progress_cb(idx, total_items, str(target), freed_bytes)

        if is_os_protected_path(target, allow_temp_contents=contents_only):
            failed.append({
                "path": str(target),
                "error": "Blocked: protected operating system or root path.",
            })
            continue

        if not os.path.lexists(os_target):
            failed.append({
                "path": str(target),
                "error": "Path no longer exists.",
            })
            continue

        before_size = get_entry_size(target)

        try:
            if contents_only and os.path.isdir(os_target):
                child_errors: list[str] = []
                with os.scandir(os_target) as it:
                    children = [Path(strip_long_prefix(e.path)) for e in it]
                for child in children:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        break
                    if is_os_protected_path(child, allow_temp_contents=False):
                        child_errors.append(f"Protected child skipped: {child.name}")
                        continue
                    try:
                        delete_fn(child)
                    except Exception as exc:
                        child_errors.append(f"{child.name}: {exc}")

                after_size = get_entry_size(target)
                reclaimed = max(0, before_size - after_size)
                freed_bytes += reclaimed
                if reclaimed > 0 or not child_errors:
                    deleted.append({
                        "path": str(target),
                        "freed_bytes": reclaimed,
                        "partial": bool(child_errors) or cancelled,
                    })
                if child_errors:
                    failed.append({
                        "path": str(target),
                        "error": "; ".join(child_errors[:3]),
                    })
                if cancelled:
                    break
            else:
                delete_fn(target)
                after_size = get_entry_size(target) if os.path.lexists(os_target) else 0
                reclaimed = max(0, before_size - after_size)
                freed_bytes += reclaimed
                deleted.append({
                    "path": str(target),
                    "freed_bytes": reclaimed,
                    "partial": False,
                })
        except Exception as exc:
            failed.append({
                "path": str(target),
                "error": str(exc),
            })

        if progress_cb is not None:
            progress_cb(idx + 1, total_items, str(target), freed_bytes)

    return DeleteResult(
        mode=mode,
        freed_bytes=freed_bytes,
        deleted_count=len(deleted),
        deleted=deleted,
        failed=failed,
        cancelled=cancelled,
    )


def run_docker_builder_prune() -> dict:
    """Run `docker builder prune -f` if Docker CLI and daemon are available."""
    docker_exe = shutil.which("docker")
    if not docker_exe:
        return {"ok": False, "message": "Docker CLI not found on PATH."}
    try:
        proc = subprocess.run(
            [docker_exe, "builder", "prune", "-f"],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = (proc.stdout or proc.stderr or "").strip()
        return {
            "ok": proc.returncode == 0,
            "message": output or ("Docker builder cache pruned." if proc.returncode == 0 else "Docker prune failed."),
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
