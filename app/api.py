"""PyWebView JS-to-Python API bridge for DriveSweep."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import webview

from app import __version__
from app.duplicates import find_duplicates
from app.logger import get_log_path, get_logger, open_log_file, read_recent_logs, setup_logging
from app.presets import scan_smart_presets
from app.safety import (
    delete_targets,
    format_bytes,
    is_admin,
    is_os_protected_path,
    relaunch_as_admin,
    run_docker_builder_prune,
    sanitized_subprocess_env,
)
from app.scanner import DriveScanner, list_drives
from app.scheduler import (
    configure_windows_reminder_task,
    evaluate_low_disk_alerts,
    query_scheduled_task,
    show_low_disk_notification,
)
from app.storage import (
    add_custom_preset,
    add_exclusion,
    append_history,
    clear_history,
    get_app_data_dir,
    get_custom_presets,
    get_exclusions,
    get_history,
    get_theme,
    load_settings,
    remove_custom_preset,
    remove_exclusion,
    set_auto_check_updates,
    set_language,
    set_reminder_settings,
    set_theme,
)
from app.system_tools import (
    analyze_winsxs,
    empty_recycle_bin,
    inspect_system_space,
    open_recycle_bin_folder,
    run_winsxs_cleanup,
)
from app.updater import (
    check_for_updates as updater_check,
    detect_install_kind,
    download_and_verify_update,
    launch_downloaded_update,
)


class DriveSweepAPI:
    """Exposed to the frontend UI as `window.pywebview.api`."""

    def __init__(self) -> None:
        setup_logging()
        self.scanner = DriveScanner()
        self._window: webview.Window | None = None
        self._cleanup_lock = threading.Lock()
        self._cleanup_cancel = threading.Event()
        self._cleanup_thread: threading.Thread | None = None
        self._cleanup_state: dict = {
            "status": "idle",
            "done": 0,
            "total": 0,
            "current_path": "",
            "freed_bytes": 0,
            "freed_human": "0 B",
            "result": None,
            "error": None,
        }
        self._update_lock = threading.Lock()
        self._update_thread: threading.Thread | None = None
        self._update_state: dict = {
            "status": "idle",
            "stage": "idle",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "percent": 0,
            "message": "",
            "sha256": "",
            "mode": "",
            "error": None,
        }
        self._dup_lock = threading.Lock()
        self._dup_cancel = threading.Event()
        self._dup_thread: threading.Thread | None = None
        self._dup_state: dict = {
            "status": "idle",
            "stage": "idle",
            "progress": 0,
            "total": 0,
            "result": None,
            "error": None,
        }

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    def get_app_info(self) -> dict:
        settings = load_settings()
        rem_pct = int(settings.get("reminder_threshold_pct", 15))
        return {
            "version": __version__,
            "os": platform.system(),
            "home": str(Path.home()),
            "drives": list_drives(),
            "is_admin": is_admin(),
            "exclusions": settings["exclusions"],
            "custom_presets": settings["custom_presets"],
            "history_count": len(get_history(limit=200)),
            "theme": settings["theme"],
            "language": settings["language"],
            "auto_check_updates": settings["auto_check_updates"],
            "reminder_enabled": settings["reminder_enabled"],
            "reminder_frequency": settings["reminder_frequency"],
            "reminder_threshold_pct": rem_pct,
            "low_disk_alerts": evaluate_low_disk_alerts(threshold_free_pct=rem_pct),
            "install_kind": detect_install_kind(),
            "data_dir": str(get_app_data_dir()),
        }

    def set_theme(self, theme: str) -> dict:
        return set_theme(theme)

    def set_language(self, language: str) -> dict:
        return set_language(language)

    def set_auto_check_updates(self, enabled: bool) -> dict:
        return set_auto_check_updates(bool(enabled))

    def check_for_updates(self) -> dict:
        return updater_check(current_version=__version__)

    def _schedule_clean_exit(self, delay: float = 0.1) -> None:
        win = self._window
        if win is None:
            return

        def _close_win() -> None:
            try:
                win.destroy()
            except Exception:
                os._exit(0)

        t_close = threading.Timer(delay, _close_win)
        t_close.daemon = True
        t_close.start()

        t_watchdog = threading.Timer(delay + 0.65, lambda: os._exit(0))
        t_watchdog.daemon = True
        t_watchdog.start()

    def download_and_apply_update(self, asset_url: str, asset_name: str, sha256_url: str) -> dict:
        dl = download_and_verify_update(asset_url, asset_name, sha256_url)
        if not dl.get("ok"):
            return dl
        launch = launch_downloaded_update(dl["file_path"])
        if not launch.get("ok"):
            return launch
        if launch.get("should_exit"):
            self._schedule_clean_exit(0.1)
        return {**launch, "sha256": dl.get("sha256", "")}

    def start_update_install(
        self,
        asset_url: str,
        asset_name: str,
        sha256_url: str,
        expected_size: int = 0,
    ) -> dict:
        with self._update_lock:
            if self._update_state["status"] in ("downloading", "verifying", "launching"):
                return dict(self._update_state)
            total = max(0, int(expected_size or 0))
            self._update_state = {
                "status": "downloading",
                "stage": "checksum",
                "downloaded_bytes": 0,
                "total_bytes": total,
                "percent": 0,
                "message": "Preparing update package download...",
                "sha256": "",
                "mode": "",
                "error": None,
            }

        def _worker() -> None:
            def on_progress(stage: str, downloaded: int, total_bytes: int, message: str) -> None:
                pct = 0
                if total_bytes > 0:
                    pct = min(99 if stage == "downloading" else 100, int((downloaded / total_bytes) * 100))
                status = "verifying" if stage == "verifying" else "downloading"
                with self._update_lock:
                    self._update_state["status"] = status
                    self._update_state["stage"] = stage
                    self._update_state["downloaded_bytes"] = downloaded
                    self._update_state["total_bytes"] = total_bytes
                    self._update_state["percent"] = pct
                    self._update_state["message"] = message

            try:
                dl = download_and_verify_update(
                    asset_url,
                    asset_name,
                    sha256_url,
                    progress_cb=on_progress,
                    expected_size=expected_size,
                )
                if not dl.get("ok"):
                    with self._update_lock:
                        self._update_state["status"] = "error"
                        self._update_state["stage"] = "error"
                        self._update_state["error"] = dl.get("error") or "Update download failed."
                    return

                with self._update_lock:
                    self._update_state["status"] = "launching"
                    self._update_state["stage"] = "launching"
                    self._update_state["percent"] = 100
                    self._update_state["sha256"] = dl.get("sha256", "")
                    self._update_state["message"] = "Verified checksum. Opening Windows installer..."

                launch = launch_downloaded_update(dl["file_path"])
                if not launch.get("ok"):
                    with self._update_lock:
                        self._update_state["status"] = "error"
                        self._update_state["stage"] = "error"
                        self._update_state["error"] = launch.get("error") or "Could not start installer."
                    return

                with self._update_lock:
                    self._update_state["mode"] = launch.get("mode", "setup")
                    self._update_state["message"] = "Installer started. Closing DriveSweep to upgrade..."

                if launch.get("should_exit"):
                    self._schedule_clean_exit(0.1)
            except Exception as exc:
                with self._update_lock:
                    self._update_state["status"] = "error"
                    self._update_state["stage"] = "error"
                    self._update_state["error"] = str(exc)

        self._update_thread = threading.Thread(target=_worker, daemon=True)
        self._update_thread.start()
        return self.get_update_status()

    def get_update_status(self) -> dict:
        with self._update_lock:
            return dict(self._update_state)

    def open_data_dir(self) -> dict:
        return self.open_in_explorer(str(get_app_data_dir()))

    def refresh_drives(self) -> list[dict]:
        return list_drives()

    def relaunch_as_admin(self) -> dict:
        res = relaunch_as_admin()
        if res.get("launching") and self._window:
            self._window.destroy()
        return res

    def get_exclusions(self) -> list[str]:
        return get_exclusions()

    def add_exclusion(self, raw_path: str) -> list[str]:
        return add_exclusion(raw_path)

    def remove_exclusion(self, raw_path: str) -> list[str]:
        return remove_exclusion(raw_path)

    def get_history(self, limit: int = 50) -> list[dict]:
        return get_history(limit=limit)

    def clear_history(self) -> list[dict]:
        clear_history()
        return []

    def scan_smart_presets(self) -> dict:
        return scan_smart_presets(exclusions=get_exclusions())

    def start_drive_scan(self, root_path: str, force: bool = False) -> dict:
        return self.scanner.start_scan(root_path, force=bool(force))

    def get_scan_status(self) -> dict:
        return self.scanner.get_status()

    def cancel_drive_scan(self) -> dict:
        self.scanner.cancel_scan()
        return self.scanner.get_status()

    def pick_folder(self) -> str | None:
        if not self._window:
            return None
        result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            return result[0]
        return None

    def browse_folder(
        self,
        folder_path: str | None = None,
        sort_by: str = "size",
        query: str = "",
        offset: int = 0,
        limit: int = 250,
    ) -> dict:
        return self.scanner.browse_folder(
            folder_path,
            sort_by=sort_by,
            query=query,
            offset=offset,
            limit=limit,
        )

    def search_all_files(
        self,
        query: str = "",
        min_size_mb: float = 0.0,
        min_age_days: int = 0,
        ext: str = "",
        sort_by: str = "size",
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        return self.scanner.search_all_files(
            query=query,
            min_size_mb=float(min_size_mb or 0),
            min_age_days=int(min_age_days or 0),
            ext=ext,
            sort_by=sort_by,
            offset=offset,
            limit=limit,
        )

    def get_largest_files(self, limit: int = 200) -> list[dict]:
        return self.scanner.get_largest_files(limit=limit)

    def get_dev_artifacts(self, limit: int = 200, min_age_days: int = 0) -> list[dict]:
        return self.scanner.get_dev_artifacts(limit=limit, min_age_days=int(min_age_days or 0))

    def get_drive_analytics(self, folder_path: str | None = None) -> dict:
        return self.scanner.get_analytics(folder_path=folder_path)

    def _finalize_cleanup(
        self,
        targets: list[dict],
        result,
        docker_result: dict | None,
        drives_before: dict[str, int],
    ) -> dict:
        contents_only_paths = {
            os.path.normcase(os.path.normpath(t["path"]))
            for t in targets
            if t.get("path") and t.get("contents_only")
        }
        deleted_full_paths = [
            d["path"]
            for d in result.deleted
            if os.path.normcase(os.path.normpath(d["path"])) not in contents_only_paths
        ]
        cleared_contents_paths = [
            d["path"]
            for d in result.deleted
            if os.path.normcase(os.path.normpath(d["path"])) in contents_only_paths and not d.get("partial")
        ]
        if deleted_full_paths or cleared_contents_paths:
            self.scanner.remove_deleted_paths(deleted_full_paths, cleared_contents_paths)

        append_history({
            "mode": result.mode,
            "freed_bytes": result.freed_bytes,
            "freed_human": format_bytes(result.freed_bytes),
            "deleted_count": result.deleted_count,
            "failed_count": len(result.failed),
            "cancelled": bool(result.cancelled),
            "items": [d["path"] for d in result.deleted],
            "failed": result.failed,
        })

        drives_after = list_drives()
        return {
            "mode": result.mode,
            "freed_bytes": result.freed_bytes,
            "freed_human": format_bytes(result.freed_bytes),
            "deleted_count": result.deleted_count,
            "deleted": result.deleted,
            "failed": result.failed,
            "cancelled": bool(result.cancelled),
            "docker_result": docker_result,
            "drives_after": drives_after,
            "drives_before": drives_before,
        }

    def execute_cleanup(
        self,
        targets: list[dict],
        mode: str = "recycle",
        include_docker_prune: bool = False,
    ) -> dict:
        drives_before = {d["path"]: d["free_bytes"] for d in list_drives()}
        result = delete_targets(targets, mode=mode)
        docker_result = run_docker_builder_prune() if include_docker_prune else None
        return self._finalize_cleanup(targets, result, docker_result, drives_before)

    def start_cleanup(
        self,
        targets: list[dict],
        mode: str = "recycle",
        include_docker_prune: bool = False,
    ) -> dict:
        with self._cleanup_lock:
            if self._cleanup_state["status"] == "running":
                return dict(self._cleanup_state)
            self._cleanup_cancel.clear()
            total = len(targets) + (1 if include_docker_prune else 0)
            self._cleanup_state = {
                "status": "running",
                "done": 0,
                "total": max(1, total),
                "current_path": targets[0].get("path", "") if targets else "Docker build cache",
                "freed_bytes": 0,
                "freed_human": "0 B",
                "result": None,
                "error": None,
            }

        def _worker() -> None:
            drives_before = {d["path"]: d["free_bytes"] for d in list_drives()}

            def on_progress(done: int, total_items: int, current_path: str, freed_bytes: int) -> None:
                with self._cleanup_lock:
                    self._cleanup_state["done"] = done
                    self._cleanup_state["total"] = max(1, total_items + (1 if include_docker_prune else 0))
                    self._cleanup_state["current_path"] = current_path
                    self._cleanup_state["freed_bytes"] = freed_bytes
                    self._cleanup_state["freed_human"] = format_bytes(freed_bytes)

            try:
                result = delete_targets(
                    targets,
                    mode=mode,
                    progress_cb=on_progress,
                    cancel_event=self._cleanup_cancel,
                )
                docker_result = None
                if include_docker_prune and not self._cleanup_cancel.is_set():
                    with self._cleanup_lock:
                        self._cleanup_state["current_path"] = "Docker builder cache"
                    docker_result = run_docker_builder_prune()

                payload = self._finalize_cleanup(targets, result, docker_result, drives_before)
                with self._cleanup_lock:
                    self._cleanup_state["status"] = "cancelled" if result.cancelled else "completed"
                    self._cleanup_state["done"] = self._cleanup_state["total"]
                    self._cleanup_state["freed_bytes"] = payload["freed_bytes"]
                    self._cleanup_state["freed_human"] = payload["freed_human"]
                    self._cleanup_state["result"] = payload
            except Exception as exc:
                with self._cleanup_lock:
                    self._cleanup_state["status"] = "error"
                    self._cleanup_state["error"] = str(exc)

        self._cleanup_thread = threading.Thread(target=_worker, daemon=True)
        self._cleanup_thread.start()
        return self.get_cleanup_status()

    def get_cleanup_status(self) -> dict:
        with self._cleanup_lock:
            return dict(self._cleanup_state)

    def cancel_cleanup(self) -> dict:
        self._cleanup_cancel.set()
        return self.get_cleanup_status()

    def open_in_explorer(self, raw_path: str) -> dict:
        p = Path(raw_path)
        if not p.exists():
            return {"ok": False, "error": "Path does not exist."}
        try:
            if os.name == "nt":
                if p.is_file():
                    subprocess.Popen(["explorer", "/select,", str(p)], env=sanitized_subprocess_env())
                else:
                    os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(
                    ["open", "-R", str(p)] if p.is_file() else ["open", str(p)],
                    env=sanitized_subprocess_env(),
                )
            else:
                target = str(p.parent if p.is_file() else p)
                subprocess.Popen(["xdg-open", target], env=sanitized_subprocess_env())
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_treemap_data(self, folder_path: str | None = None) -> dict:
        return self.scanner.get_treemap_data(folder_path=folder_path)

    def export_scan_report(self, fmt: str = "csv") -> dict:
        norm_fmt = "json" if str(fmt or "").strip().lower() == "json" else "csv"
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_name = f"DriveSweep-Report-{ts}.{norm_fmt}"
        output_path = ""

        if self._window is not None:
            try:
                file_types = (
                    ("JSON Report (*.json)",)
                    if norm_fmt == "json"
                    else ("CSV Spreadsheet (*.csv)",)
                )
                picked = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=default_name,
                    file_types=file_types,
                )
                if not picked:
                    return {"ok": False, "cancelled": True}
                output_path = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
            except Exception:
                output_path = ""

        if not output_path:
            docs = Path.home() / "Documents"
            base_dir = docs if docs.exists() else get_app_data_dir()
            output_path = str(base_dir / default_name)

        return self.scanner.export_scan_report(output_path, fmt=norm_fmt)

    def start_duplicate_scan(self, min_size_kb: int = 100) -> dict:
        nodes = self.scanner.get_nodes_snapshot()
        if not nodes:
            return {"status": "error", "error": "Scan a drive or folder first before finding duplicates."}

        with self._dup_lock:
            if self._dup_state.get("status") == "running":
                return dict(self._dup_state)
            self._dup_cancel.clear()
            self._dup_state = {
                "status": "running",
                "stage": "grouping",
                "progress": 0,
                "total": 0,
                "result": None,
                "error": None,
            }

        min_bytes = max(1024, int(min_size_kb) * 1024)
        exclusions = get_exclusions()

        def _dup_worker() -> None:
            def on_prog(stage: str, done: int, total: int) -> None:
                with self._dup_lock:
                    self._dup_state["stage"] = stage
                    self._dup_state["progress"] = done
                    self._dup_state["total"] = total

            try:
                res = find_duplicates(
                    nodes,
                    min_size_bytes=min_bytes,
                    exclusions=exclusions,
                    cancel_event=self._dup_cancel,
                    progress_cb=on_prog,
                )
                with self._dup_lock:
                    self._dup_state["status"] = "cancelled" if res.get("cancelled") else "done"
                    self._dup_state["stage"] = "done"
                    self._dup_state["result"] = res
            except Exception as exc:
                with self._dup_lock:
                    self._dup_state["status"] = "error"
                    self._dup_state["error"] = str(exc)

        self._dup_thread = threading.Thread(target=_dup_worker, daemon=True)
        self._dup_thread.start()
        return self.get_duplicate_status()

    def get_duplicate_status(self) -> dict:
        with self._dup_lock:
            return dict(self._dup_state)

    def cancel_duplicate_scan(self) -> dict:
        self._dup_cancel.set()
        return self.get_duplicate_status()

    def inspect_system_space(self, max_age_days: int = 30) -> dict:
        return inspect_system_space(max_installer_age_days=int(max_age_days or 30))

    def empty_recycle_bin(self, drive_root: str | None = None) -> dict:
        res = empty_recycle_bin(root_path=drive_root)
        res["drives_after"] = list_drives()
        return res

    def open_recycle_bin(self) -> dict:
        return open_recycle_bin_folder()

    def analyze_winsxs(self) -> dict:
        return analyze_winsxs()

    def run_winsxs_cleanup(self) -> dict:
        res = run_winsxs_cleanup()
        res["drives_after"] = list_drives()
        return res

    def get_custom_presets(self) -> list[dict]:
        return get_custom_presets()

    def add_custom_preset(
        self,
        raw_path: str = "",
        name: str = "",
        contents_only: bool = True,
    ) -> dict:
        target_path = str(raw_path or "").strip()
        if not target_path and self._window is not None:
            try:
                picked = self._window.create_file_dialog(webview.FOLDER_DIALOG)
                if not picked:
                    return {"ok": False, "cancelled": True}
                target_path = picked[0] if isinstance(picked, (list, tuple)) else str(picked)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if not target_path:
            return {"ok": False, "error": "No folder selected."}

        p = Path(target_path)
        if not p.exists() or not p.is_dir():
            return {"ok": False, "error": f"Folder does not exist: {target_path}"}
        if is_os_protected_path(p, allow_temp_contents=bool(contents_only)):
            return {
                "ok": False,
                "error": "Cannot add critical Windows system folders as cleanup presets.",
            }
        items = add_custom_preset(str(p), name=name, contents_only=bool(contents_only))
        return {"ok": True, "custom_presets": items}

    def remove_custom_preset(self, preset_id_or_path: str) -> dict:
        items = remove_custom_preset(preset_id_or_path)
        return {"ok": True, "custom_presets": items}

    def get_reminder_status(self) -> dict:
        settings = load_settings()
        task_info = query_scheduled_task()
        threshold = int(settings.get("reminder_threshold_pct", 15))
        return {
            "enabled": bool(settings.get("reminder_enabled", False)),
            "frequency": settings.get("reminder_frequency", "weekly"),
            "threshold_pct": threshold,
            "task": task_info,
            "alerts": evaluate_low_disk_alerts(threshold_free_pct=threshold),
        }

    def configure_disk_reminder(
        self,
        enabled: bool,
        frequency: str = "weekly",
        threshold_pct: int = 15,
    ) -> dict:
        task_res = configure_windows_reminder_task(bool(enabled), frequency=frequency)
        settings = set_reminder_settings(
            enabled=bool(enabled) and bool(task_res.get("ok", False)),
            frequency=frequency,
            threshold_pct=int(threshold_pct),
        )
        return {
            **task_res,
            "enabled": settings["reminder_enabled"],
            "frequency": settings["reminder_frequency"],
            "threshold_pct": settings["reminder_threshold_pct"],
            "alerts": evaluate_low_disk_alerts(threshold_free_pct=settings["reminder_threshold_pct"]),
        }

    def test_low_disk_notification(self) -> dict:
        settings = load_settings()
        threshold = int(settings.get("reminder_threshold_pct", 15))
        alerts = evaluate_low_disk_alerts(threshold_free_pct=threshold)
        target_alerts = alerts["alerts"] or [
            {"drive": "C:\\", "free_human": "Test Alert", "free_pct": threshold}
        ]
        return show_low_disk_notification(target_alerts)

    def report_ui_error(self, message: str, source: str = "", stack: str = "") -> dict:
        msg = str(message or "").strip()[:500]
        src = str(source or "").strip()[:200]
        stk = str(stack or "").strip()[:1500]
        get_logger().error("UI error (%s): %s\n%s", src or "renderer", msg, stk)
        return {"ok": True}

    def get_diagnostics_info(self) -> dict:
        return {
            "version": __version__,
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": platform.python_version(),
            "is_admin": is_admin(),
            "install_kind": detect_install_kind(),
            "scan_engine": self.scanner.scan_engine,
            "data_dir": str(get_app_data_dir()),
            "log_path": str(get_log_path()),
            "log_tail": read_recent_logs(max_lines=100),
        }

    def open_log_file(self) -> dict:
        return open_log_file()
