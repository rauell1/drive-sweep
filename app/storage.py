"""Persistent user settings (theme, Always Keep exclusions) and cleanup audit history."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_app_data_dir() -> Path:
    """Return platform-appropriate per-user data directory for DriveSweep."""
    override = os.environ.get("DRIVESWEEP_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        base = Path(local_app) / "DriveSweep"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "DriveSweep"
    else:
        xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        base = Path(xdg) / "drivesweep"

    base.mkdir(parents=True, exist_ok=True)
    return base


def _settings_path() -> Path:
    return get_app_data_dir() / "settings.json"


def _history_path() -> Path:
    return get_app_data_dir() / "history.jsonl"


def _norm_path(raw_path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(raw_path)))


def load_settings() -> dict:
    path = _settings_path()
    default = {"exclusions": [], "default_delete_mode": "recycle", "theme": "dark"}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default
        exclusions = data.get("exclusions", [])
        if not isinstance(exclusions, list):
            exclusions = []
        mode = data.get("default_delete_mode", "recycle")
        if mode not in ("recycle", "permanent"):
            mode = "recycle"
        theme = data.get("theme", "dark")
        if theme not in ("dark", "light"):
            theme = "dark"
        return {
            "exclusions": [str(x) for x in exclusions if x],
            "default_delete_mode": mode,
            "theme": theme,
        }
    except Exception:
        return default


def save_settings(settings: dict) -> dict:
    path = _settings_path()
    theme = settings.get("theme", "dark")
    if theme not in ("dark", "light"):
        theme = "dark"
    mode = settings.get("default_delete_mode", "recycle")
    if mode not in ("recycle", "permanent"):
        mode = "recycle"
    cleaned = {
        "exclusions": list(dict.fromkeys(str(x) for x in settings.get("exclusions", []) if x)),
        "default_delete_mode": mode,
        "theme": theme,
    }
    path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    return cleaned


def get_theme() -> str:
    return load_settings()["theme"]


def set_theme(theme: str) -> dict:
    settings = load_settings()
    if theme in ("dark", "light"):
        settings["theme"] = theme
    return save_settings(settings)


def get_exclusions() -> list[str]:
    return load_settings()["exclusions"]


def add_exclusion(raw_path: str) -> list[str]:
    settings = load_settings()
    target_norm = _norm_path(raw_path)
    existing = settings["exclusions"]
    if not any(_norm_path(p) == target_norm for p in existing):
        existing.append(os.path.abspath(os.path.normpath(raw_path)))
    return save_settings(settings)["exclusions"]


def remove_exclusion(raw_path: str) -> list[str]:
    settings = load_settings()
    target_norm = _norm_path(raw_path)
    settings["exclusions"] = [p for p in settings["exclusions"] if _norm_path(p) != target_norm]
    return save_settings(settings)["exclusions"]


def is_path_excluded(raw_path: str, exclusions: list[str] | None = None) -> bool:
    ex_list = exclusions if exclusions is not None else get_exclusions()
    if not ex_list:
        return False
    p_norm = _norm_path(raw_path)
    for ex in ex_list:
        ex_norm = _norm_path(ex)
        if p_norm == ex_norm or p_norm.startswith(ex_norm.rstrip("\\/") + os.sep):
            return True
    return False


def set_default_delete_mode(mode: str) -> dict:
    settings = load_settings()
    if mode in ("recycle", "permanent"):
        settings["default_delete_mode"] = mode
    return save_settings(settings)


def append_history(entry: dict) -> dict:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": entry.get("mode", "recycle"),
        "freed_bytes": int(entry.get("freed_bytes", 0)),
        "freed_human": str(entry.get("freed_human", "0 B")),
        "deleted_count": int(entry.get("deleted_count", 0)),
        "failed_count": int(entry.get("failed_count", 0)),
        "items": entry.get("items", [])[:50],
        "failed": entry.get("failed", [])[:20],
    }
    path = _history_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def get_history(limit: int = 50) -> list[dict]:
    path = _history_path()
    if not path.exists():
        return []
    entries: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    entries.reverse()
    return entries[:limit]


def clear_history() -> None:
    path = _history_path()
    if path.exists():
        path.unlink()
