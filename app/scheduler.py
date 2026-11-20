"""Optional scheduled low-disk space check and Windows Task Scheduler integration."""

from __future__ import annotations

import ctypes
import os
import shutil
import string
import subprocess
import sys
from pathlib import Path

from .safety import format_bytes, sanitized_subprocess_env

TASK_NAME = "DriveSweepLowDiskReminder"
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_VALID_FREQUENCIES = ("daily", "weekly", "monthly")


def list_local_drive_usage() -> list[dict]:
    """Return disk capacity and free percentage for fixed local Windows drives."""
    drives: list[dict] = []
    if os.name == "nt":
        letters = []
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                try:
                    dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                except Exception:
                    dtype = 0
                if dtype == 3:  # DRIVE_FIXED
                    letters.append(root)
    else:
        letters = ["/"]

    for root in letters:
        try:
            usage = shutil.disk_usage(root)
            total = max(1, int(usage.total))
            free = max(0, int(usage.free))
            used = max(0, int(usage.used))
            free_pct = round((free / total) * 100.0, 1)
            used_pct = round((used / total) * 100.0, 1)
            drives.append(
                {
                    "drive": root,
                    "total_bytes": total,
                    "free_bytes": free,
                    "used_bytes": used,
                    "total_human": format_bytes(total),
                    "free_human": format_bytes(free),
                    "free_pct": free_pct,
                    "used_pct": used_pct,
                }
            )
        except OSError:
            continue
    return drives


def evaluate_low_disk_alerts(
    threshold_free_pct: int | float = 15,
    drives: list[dict] | None = None,
) -> dict:
    """Identify local fixed drives whose free space is at or below threshold_free_pct."""
    threshold = max(5, min(50, int(round(float(threshold_free_pct)))))
    items = drives if drives is not None else list_local_drive_usage()
    alerts: list[dict] = []
    for item in items:
        total = max(1, int(item.get("total_bytes", 0) or 0))
        free = max(0, int(item.get("free_bytes", 0) or 0))
        free_pct = item.get("free_pct")
        if free_pct is None:
            free_pct = round((free / total) * 100.0, 1)
        if float(free_pct) <= float(threshold):
            alerts.append(
                {
                    "drive": str(item.get("drive", "")),
                    "free_bytes": free,
                    "total_bytes": total,
                    "free_human": item.get("free_human") or format_bytes(free),
                    "total_human": item.get("total_human") or format_bytes(total),
                    "free_pct": float(free_pct),
                    "severity": "critical" if float(free_pct) <= 8.0 else "warning",
                }
            )
    return {
        "threshold_free_pct": threshold,
        "has_alerts": len(alerts) > 0,
        "alerts": alerts,
    }


def _resolve_task_command() -> str:
    """Build the command string invoked by Windows Task Scheduler."""
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return f'"{exe}" --low-disk-check --no-elevate'
    main_py = os.path.abspath(str(Path(__file__).resolve().parent.parent / "main.py"))
    py_exe = os.path.abspath(sys.executable)
    # Prefer pythonw.exe when present so scheduled background checks do not flash a console
    pyw = os.path.join(os.path.dirname(py_exe), "pythonw.exe")
    runner = pyw if os.path.exists(pyw) else py_exe
    return f'"{runner}" "{main_py}" --low-disk-check --no-elevate'


def build_schtasks_create_command(
    task_name: str = TASK_NAME,
    command_str: str | None = None,
    frequency: str = "weekly",
    start_time: str = "10:00",
) -> list[str]:
    """Build argument list for schtasks.exe /Create."""
    freq = str(frequency or "weekly").strip().lower()
    if freq not in _VALID_FREQUENCIES:
        freq = "weekly"
    cmd_target = command_str or _resolve_task_command()
    args = [
        "schtasks.exe",
        "/Create",
        "/F",
        "/TN",
        task_name,
        "/TR",
        cmd_target,
        "/SC",
        freq.upper(),
        "/ST",
        start_time,
    ]
    if freq == "weekly":
        args.extend(["/D", "SUN"])
    elif freq == "monthly":
        args.extend(["/D", "1"])
    return args


def query_scheduled_task(task_name: str = TASK_NAME) -> dict:
    """Query whether the DriveSweep Windows scheduled reminder currently exists."""
    if os.name != "nt":
        return {"supported": False, "installed": False, "task_name": task_name}
    try:
        proc = subprocess.run(
            ["schtasks.exe", "/Query", "/TN", task_name, "/FO", "LIST"],
            capture_output=True,
            text=True,
            timeout=15,
            env=sanitized_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        installed = proc.returncode == 0
        next_run = ""
        for line in (proc.stdout or "").splitlines():
            if line.lower().startswith("next run time:"):
                next_run = line.split(":", 1)[1].strip()
                break
        return {
            "supported": True,
            "installed": installed,
            "task_name": task_name,
            "next_run": next_run,
        }
    except Exception as exc:
        return {
            "supported": False,
            "installed": False,
            "task_name": task_name,
            "error": str(exc),
        }


def configure_windows_reminder_task(
    enabled: bool,
    frequency: str = "weekly",
    *,
    task_name: str = TASK_NAME,
) -> dict:
    """Create or delete the DriveSweep low-disk scheduled task in Windows Task Scheduler."""
    if os.name != "nt":
        return {"ok": False, "error": "Scheduled reminders are only supported on Windows."}
    try:
        if enabled:
            cmd = build_schtasks_create_command(task_name=task_name, frequency=frequency)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                env=sanitized_subprocess_env(),
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or f"schtasks exited with code {proc.returncode}").strip()
                return {"ok": False, "error": err, "installed": False}
            status = query_scheduled_task(task_name)
            return {"ok": True, "installed": True, **status}

        proc = subprocess.run(
            ["schtasks.exe", "/Delete", "/F", "/TN", task_name],
            capture_output=True,
            text=True,
            timeout=20,
            env=sanitized_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        # Return code 1 with "cannot find the file specified" simply means already absent
        stderr_low = ((proc.stderr or "") + (proc.stdout or "")).lower()
        already_missing = "cannot find" in stderr_low or "does not exist" in stderr_low
        if proc.returncode != 0 and not already_missing:
            err = (proc.stderr or proc.stdout or f"schtasks exited with code {proc.returncode}").strip()
            return {"ok": False, "error": err}
        return {"ok": True, "installed": False, "task_name": task_name, "next_run": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def show_low_disk_notification(alerts: list[dict], title: str = "DriveSweep Low Disk Alert") -> dict:
    """Display a non-blocking Windows tray balloon notification when drives run low on free space."""
    if not alerts:
        return {"ok": True, "notified": False, "reason": "No low-disk alerts."}
    parts = [f"{a['drive'].rstrip(chr(92))} ({a['free_human']} free, {a['free_pct']}%)" for a in alerts[:3]]
    message = "Low free space on: " + ", ".join(parts) + ". Open DriveSweep to reclaim space."
    return show_notification(title, message, icon="Warning")


def show_notification(title: str, message: str, icon: str = "Information") -> dict:
    """Display a non-blocking Windows tray balloon notification."""
    if os.name != "nt":
        return {"ok": False, "notified": False, "reason": "Notifications only supported on Windows."}
    if icon not in ("Information", "Warning"):
        icon = "Information"
    # Single quotes are doubled for PowerShell; the text is never run, only displayed.
    safe_title = title.replace("'", "''")
    safe_msg = message.replace("'", "''")

    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::" + icon + "; "
        "$n.BalloonTipTitle = '" + safe_title + "'; "
        "$n.BalloonTipText = '" + safe_msg + "'; "
        "$n.Visible = $true; "
        "$n.ShowBalloonTip(7000); "
        "Start-Sleep -Milliseconds 1500; "
        "$n.Dispose()"
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=15,
            env=sanitized_subprocess_env(),
            creationflags=_CREATE_NO_WINDOW,
        )
        return {"ok": proc.returncode == 0, "notified": proc.returncode == 0, "message": message}
    except Exception as exc:
        return {"ok": False, "notified": False, "error": str(exc), "message": message}
