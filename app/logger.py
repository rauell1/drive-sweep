"""Local rotating diagnostics logger and crash hook for DriveSweep."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .safety import sanitized_subprocess_env
from .storage import get_app_data_dir

_LOGGER_NAME = "drivesweep"
_HOOKS_INSTALLED = False


def get_log_path() -> Path:
    """Return the local diagnostics log file path inside the app data folder."""
    return get_app_data_dir() / "drivesweep.log"


def setup_logging() -> logging.Logger:
    """Configure local rotating file logging and uncaught exception hooks."""
    global _HOOKS_INSTALLED
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        log_path = get_log_path()
        target_norm = os.path.normcase(os.path.abspath(str(log_path)))
        already_attached = any(
            isinstance(h, RotatingFileHandler)
            and os.path.normcase(os.path.abspath(getattr(h, "baseFilename", ""))) == target_norm
            for h in logger.handlers
        )
        if not already_attached:
            for h in list(logger.handlers):
                logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                str(log_path),
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    except OSError:
        # Never block app startup if log folder is read-only
        pass

    if _HOOKS_INSTALLED:
        return logger

    prev_excepthook = sys.excepthook

    def _sys_excepthook(exc_type, exc_value, exc_tb) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            logger.exception("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        prev_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _sys_excepthook

    if hasattr(threading, "excepthook"):
        prev_thread_hook = threading.excepthook

        def _thread_excepthook(args) -> None:
            if not issubclass(args.exc_type, SystemExit):
                logger.exception(
                    "Unhandled exception in thread %s",
                    getattr(args.thread, "name", "unknown"),
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
            prev_thread_hook(args)

        threading.excepthook = _thread_excepthook

    _HOOKS_INSTALLED = True
    return logger


def get_logger() -> logging.Logger:
    """Return the configured DriveSweep logger."""
    return logging.getLogger(_LOGGER_NAME)


def read_recent_logs(max_lines: int = 120) -> str:
    """Read the last N lines of the local diagnostics log cleanly."""
    path = get_log_path()
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max(1, int(max_lines)) :])
    except OSError:
        return ""


def open_log_file() -> dict:
    """Open the local diagnostics log file or folder cleanly."""
    path = get_log_path()
    target = path if path.exists() else path.parent
    try:
        if os.name == "nt":
            if target.is_file():
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", str(target)], env=sanitized_subprocess_env())
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)], env=sanitized_subprocess_env())
        else:
            subprocess.Popen(["xdg-open", str(target)], env=sanitized_subprocess_env())
        return {"ok": True, "path": str(path)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "path": str(path)}


def clear_logs() -> dict:
    """Erase the diagnostics log and its rotated backups (they can contain file paths)."""
    logger = logging.getLogger(_LOGGER_NAME)
    for h in list(logger.handlers):
        if isinstance(h, RotatingFileHandler):
            try:
                h.acquire()
                if h.stream:
                    h.stream.seek(0)
                    h.stream.truncate()
                    h.stream.flush()
            except Exception:
                pass
            finally:
                h.release()
    log_path = get_log_path()
    removed = 0
    for idx in range(1, 10):
        backup = Path(f"{log_path}.{idx}")
        try:
            if backup.exists():
                backup.unlink()
                removed += 1
        except OSError:
            pass
    try:
        if log_path.exists() and not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
            log_path.write_text("", encoding="utf-8")
    except OSError:
        pass
    return {"ok": True, "removed_backups": removed}
