"""Entry point for DriveSweep desktop application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from app.api import DriveSweepAPI
from app.logger import get_logger, setup_logging
from app.safety import is_admin, relaunch_as_admin
from app.scheduler import evaluate_low_disk_alerts, show_low_disk_notification
from app.storage import load_settings
from app.system_tools import apply_windows11_frame_styling
from app.updater import cleanup_stale_updates, confirm_update_started


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
    if settings.get("auto_clean_safe"):
        # Optional (off by default): clean Safe items to the Recycle Bin before checking space.
        try:
            from app.auto_clean import run_scheduled_cleanup
            from app.scheduler import show_notification

            res = run_scheduled_cleanup()
            if res.get("cleaned"):
                show_notification(
                    "DriveSweep",
                    f"Moved {res['freed_human']} of temporary files to the Recycle Bin. "
                    "Open DriveSweep's Cleanup Log to see them or undo.",
                )
        except Exception:
            get_logger().exception("Scheduled cleanup failed")
    # The same scheduled task serves both features, so the alert runs only if it is turned on.
    if settings.get("reminder_enabled", True):
        report = evaluate_low_disk_alerts(threshold_free_pct=threshold)
        if report["has_alerts"]:
            show_low_disk_notification(report["alerts"])
    return 0


def run_self_test(output_path: str) -> int:
    """Non-interactive smoke test used by CI on the built executables.

    Writes a JSON report to output_path and returns 0 when the bundle is complete: the app
    modules import, the UI and icon files are present, and the version is readable. It
    opens no window, needs no elevation and changes nothing on the machine.
    """
    import json
    import traceback

    from app import __version__

    report: dict = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "checks": {}}
    ok = True

    def check(name: str, fn) -> None:
        nonlocal ok
        try:
            value = fn()
            report["checks"][name] = {"ok": bool(value), "value": str(value)}
            ok = ok and bool(value)
        except Exception:
            report["checks"][name] = {"ok": False, "error": traceback.format_exc(limit=3)}
            ok = False

    check("ui_index", lambda: Path(get_ui_index_path()).is_file())
    check("ui_app_js", lambda: (Path(get_ui_index_path()).parent / "app.js").is_file())
    check("icon", lambda: get_icon_path() is not None)
    check("imports", lambda: all(
        __import__(m) for m in (
            "app.api", "app.scanner", "app.duplicates", "app.ntfs_mft", "app.presets",
            "app.system_tools", "app.updater", "webview", "send2trash", "psutil",
        )
    ))
    check("install_kind", lambda: __import__("app.updater", fromlist=["x"]).detect_install_kind())
    if sys.platform == "win32":
        import platform

        report["machine"] = platform.machine()
        # Loads pythonnet, the .NET runtime and the WebView2 assemblies exactly as opening the
        # window would, without creating one. Catches a bundle that cannot start its interface.
        check("gui_backend", lambda: bool(__import__("webview.platforms.winforms", fromlist=["x"])))
    report["ok"] = ok
    Path(output_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if ok else 1


def main() -> None:
    if "--self-test" in sys.argv[1:]:
        idx = sys.argv.index("--self-test")
        out = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "drivesweep-selftest.json"
        raise SystemExit(run_self_test(out))
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
        # The window is up: confirm a pending in place update and drop the old version's backup.
        confirm_update_started()

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
