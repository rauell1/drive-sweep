"""Safety guards, Windows long-path helpers, elevation check, and deletion execution."""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from send2trash import send2trash


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


def relaunch_as_admin() -> dict:
    """Prompt UAC elevation to restart DriveSweep with Administrator rights on Windows."""
    if os.name != "nt":
        return {"ok": False, "error": "Elevation prompt is only implemented for Windows."}
    if is_admin():
        return {"ok": True, "already_admin": True}
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = subprocess.list2cmdline(sys.argv[1:])
        else:
            exe = sys.executable
            params = subprocess.list2cmdline(sys.argv)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        if rc <= 32:
            return {"ok": False, "error": f"Elevation cancelled or failed (code {rc})."}
        return {"ok": True, "launching": True}
    except Exception as exc:
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
        win_temp = _normalize(windir / "Temp")

        # Allow cleaning items *inside* C:\Windows\Temp (or the Temp container when contents_only=True)
        if allow_temp_contents and p == win_temp:
            return False
        if _is_same_or_child(p, win_temp) and p != win_temp:
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
        self.personal_prefixes = tuple(
            os.path.normcase(str(home / name)).rstrip("\\/") + os.sep
            for name in personal_names
        )

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
    if is_personal_guarded_path(p):
        return {
            "risk_level": "caution",
            "risk_reason": "Personal user folder/file (Downloads, OneDrive, Documents, etc.). Confirm before deleting.",
        }

    if name_lower in CAUTION_DIR_NAMES or any(part.lower() in CAUTION_DIR_NAMES for part in p.parts):
        return {
            "risk_level": "caution",
            "risk_reason": "Contains repository history or credentials (.git, .ssh, etc.).",
        }

    if not is_dir:
        ext = p.suffix.lower()
        if ext in CAUTION_EXTENSIONS or name_lower.startswith(".env"):
            return {
                "risk_level": "caution",
                "risk_reason": f"Sensitive, executable, database, or virtual disk file ({ext or name_lower}).",
            }

    if is_dev_bloat and age_days is not None and age_days < 30:
        return {
            "risk_level": "caution",
            "risk_reason": f"Active project dependency folder (modified {age_days} day(s) ago).",
        }

    return {
        "risk_level": "safe",
        "risk_reason": "Standard file or regenerable folder.",
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


def delete_targets(targets: Iterable[dict], mode: str = "recycle") -> DeleteResult:
    """Delete selected files/directories via Recycle Bin or Permanent Delete."""
    if mode not in ("recycle", "permanent"):
        raise ValueError(f"Invalid delete mode: {mode}")

    deduped = deduplicate_targets(targets)
    delete_fn = _recycle_entry if mode == "recycle" else _permanent_delete_entry
    deleted: list[dict] = []
    failed: list[dict] = []
    freed_bytes = 0

    for item in deduped:
        raw_path = item["path"]
        contents_only = item["contents_only"]
        target = _normalize(raw_path)
        os_target = to_os_path(target)

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
                        "partial": bool(child_errors),
                    })
                if child_errors:
                    failed.append({
                        "path": str(target),
                        "error": "; ".join(child_errors[:3]),
                    })
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

    return DeleteResult(
        mode=mode,
        freed_bytes=freed_bytes,
        deleted_count=len(deleted),
        deleted=deleted,
        failed=failed,
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
