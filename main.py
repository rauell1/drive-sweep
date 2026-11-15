"""Entry point for DriveSweep desktop application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from app.api import DriveSweepAPI
from app.safety import is_admin, relaunch_as_admin


def ensure_admin_or_relaunch(argv: list[str] | None = None) -> bool:
    """Ensure DriveSweep runs elevated on Windows unless explicitly bypassed for testing.

    Returns True if the current process should continue running, or False if an
    elevated child process was launched and this parent process should exit.
    """
    args = sys.argv[1:] if argv is None else argv
    if "--no-elevate" in args or os.environ.get("DRIVESWEEP_NO_ELEVATE") == "1":
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


def main() -> None:
    if not ensure_admin_or_relaunch():
        return
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
    debug_mode = os.environ.get("DRIVESWEEP_DEBUG") == "1"
    icon_path = get_icon_path()
    # pywebview supports icon= on GTK/QT/WinForms depending on version; pass safely
    if icon_path and sys.platform != "win32":
        webview.start(debug=debug_mode, icon=icon_path)
    else:
        webview.start(debug=debug_mode)


if __name__ == "__main__":
    main()
