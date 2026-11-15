"""PyWebView JS-to-Python API bridge for DriveSweep."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
from pathlib import Path

import webview

from app import __version__
from app.presets import scan_smart_presets
from app.safety import (
    delete_targets,
    format_bytes,
    is_admin,
    relaunch_as_admin,
    run_docker_builder_prune,
)
from app.scanner import DriveScanner, list_drives
from app.storage import (
    add_exclusion,
    append_history,
    clear_history,
    get_app_data_dir,
    get_exclusions,
    get_history,
    get_theme,
    load_settings,
    remove_exclusion,
    set_auto_check_updates,
    set_theme,
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

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    def get_app_info(self) -> dict:
        settings = load_settings()
        return {
            "version": __version__,
            "os": platform.system(),
            "home": str(Path.home()),
            "drives": list_drives(),
            "is_admin": is_admin(),
            "exclusions": settings["exclusions"],
            "history_count": len(get_history(limit=200)),
            "theme": settings["theme"],
            "auto_check_updates": settings["auto_check_updates"],
            "install_kind": detect_install_kind(),
            "data_dir": str(get_app_data_dir()),
        }

    def set_theme(self, theme: str) -> dict:
        return set_theme(theme)

    def set_auto_check_updates(self, enabled: bool) -> dict:
        return set_auto_check_updates(bool(enabled))

    def check_for_updates(self) -> dict:
        return updater_check(current_version=__version__)

    def download_and_apply_update(self, asset_url: str, asset_name: str, sha256_url: str) -> dict:
        dl = download_and_verify_update(asset_url, asset_name, sha256_url)
        if not dl.get("ok"):
            return dl
        launch = launch_downloaded_update(dl["file_path"])
        if not launch.get("ok"):
            return launch
        if launch.get("should_exit") and self._window:
            threading.Timer(0.25, self._window.destroy).start()
        return {**launch, "sha256": dl.get("sha256", "")}

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
                    subprocess.Popen(["explorer", "/select,", str(p)])
                else:
                    os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
            else:
                target = str(p.parent if p.is_file() else p)
                subprocess.Popen(["xdg-open", target])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
