"""Entry point for DriveSweep desktop application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from app.api import DriveSweepAPI
from app.logger import setup_logging
from app.safety import is_admin, relaunch_as_admin
from app.scheduler import evaluate_low_disk_alerts, show_low_disk_notification
from app.storage import load_settings
from app.system_tools import apply_windows11_frame_styling
from app.updater import cleanup_stale_updates


def ensure_admin_or_relaunch(argv: list[str] | None = None) -> bool:
    """Run with least privilege: only ask Windows for Administrator rights when requested.

    DriveSweep starts as a standard user. Admin rights are needed only for system level
    tasks (Windows Temp, DISM, hibernation, virtual disks); the user turns them on with
    "Restart as Admin" in the app, or by launching with --elevate.

    Returns True if the current process should continue running, or False if an
    elevated child process was launched and this parent process should exit.
    """
    args = sys.argv[1:] if argv is None else argv
    if "--no-elevate" in args or os.environ.get("DRIVESWEEP_NO_ELEVATE") == "1":
        return True
    if "--elevate" not in args:
        return True
    if sys.platform != "win32" or is_admin():
        return True
    res = relaunch_as_admin()
    if res.get("launching"):
        return False
    return True


def _resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def get_ui_index_path() -> str:
    """Resolve UI HTML path both from source and inside a PyInstaller bundle."""
    ui_index = _resource_root() / "app" / "ui" / "index.html"
    if ui_index.exists():
        return str(ui_index)
    return str(Path(__file__).resolve().parent / "app" / "ui" / "index.html")


def get_icon_path() -> str | None:
    """Resolve icon path if bundled or present in assets/."""
    for candidate in (
        _resource_root() / "assets" / "drivesweep.ico",
        Path(__file__).resolve().parent / "assets" / "drivesweep.ico",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def run_low_disk_check_cli() -> int:
    """Headless low-disk check invoked by Windows Task Scheduler."""
    settings = load_settings()
    threshold = int(settings.get("reminder_threshold_pct", 15))
    report = evaluate_low_disk_alerts(threshold_free_pct=threshold)
    if report["has_alerts"]:
        show_low_disk_notification(report["alerts"])
    return 0


def main() -> None:
    setup_logging()
    if "--low-disk-check" in sys.argv[1:]:
        raise SystemExit(run_low_disk_check_cli())
    if not ensure_admin_or_relaunch():
        return
    cleanup_stale_updates()
    api = DriveSweepAPI()
    window = webview.create_window(
        title="DriveSweep - PC Storage & Drive Cleaner",
        url=get_ui_index_path(),
        js_api=api,
        width=1240,
        height=840,
        min_size=(960, 640),
        background_color="#0f1419",
    )
    api.set_window(window)

    def _on_shown() -> None:
        settings = load_settings()
        apply_windows11_frame_styling(dark_mode=(settings.get("theme") == "dark"))

    if hasattr(window, "events") and hasattr(window.events, "shown"):
        window.events.shown += _on_shown

    debug_mode = os.environ.get("DRIVESWEEP_DEBUG") == "1"
    icon_path = get_icon_path()
    # pywebview supports icon= on GTK/QT/WinForms depending on version; pass safely
    if icon_path and sys.platform != "win32":
        webview.start(debug=debug_mode, icon=icon_path)
    else:
        webview.start(debug=debug_mode)


if __name__ == "__main__":
    main()
