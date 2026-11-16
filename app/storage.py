"""Persistent user settings (theme, Always Keep exclusions) and cleanup audit history."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.safety import format_bytes


def get_app_data_dir() -> Path:
    """Return platform-appropriate per-user data directory for DriveSweep."""
    # The override exists for tests and development only. Packaged builds ignore it so an
    # environment variable can never point the elevated app at attacker controlled settings.
    override = None if getattr(sys, "frozen", False) else os.environ.get("DRIVESWEEP_DATA_DIR")
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


SUPPORTED_LANGUAGES = ("en", "es", "fr", "de", "pt")
SUPPORTED_REMINDER_FREQS = ("daily", "weekly", "monthly")


def _clean_custom_presets(raw_list: object) -> list[dict]:
    if not isinstance(raw_list, list):
        return []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path", "")).strip()
        if not raw_path:
            continue
        abs_path = os.path.abspath(os.path.normpath(raw_path))
        norm = _norm_path(abs_path)
        if norm in seen:
            continue
        seen.add(norm)
        name = str(item.get("name", "")).strip() or os.path.basename(abs_path) or abs_path
        preset_id = str(item.get("id", "")).strip() or f"custom_{abs(hash(norm)) & 0xFFFFFFFF:08x}"
        cleaned.append(
            {
                "id": preset_id,
                "name": name[:80],
                "path": abs_path,
                "contents_only": bool(item.get("contents_only", True)),
            }
        )
    return cleaned


def load_settings() -> dict:
    path = _settings_path()
    default = {
        "exclusions": [],
        "default_delete_mode": "recycle",
        "theme": "dark",
        "auto_check_updates": False,
        "disclaimer_accepted_version": "",
        "custom_presets": [],
        "language": "en",
        "reminder_enabled": False,
        "reminder_frequency": "weekly",
        "reminder_threshold_pct": 15,
    }
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
        lang = str(data.get("language", "en")).strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"
        rem_freq = str(data.get("reminder_frequency", "weekly")).strip().lower()
        if rem_freq not in SUPPORTED_REMINDER_FREQS:
            rem_freq = "weekly"
        try:
            rem_pct = max(5, min(50, int(data.get("reminder_threshold_pct", 15))))
        except (TypeError, ValueError):
            rem_pct = 15
        return {
            "exclusions": [str(x) for x in exclusions if x],
            "default_delete_mode": mode,
            "theme": theme,
            "auto_check_updates": bool(data.get("auto_check_updates", False)),
            "disclaimer_accepted_version": str(data.get("disclaimer_accepted_version", "") or "")[:32],
            "custom_presets": _clean_custom_presets(data.get("custom_presets", [])),
            "language": lang,
            "reminder_enabled": bool(data.get("reminder_enabled", False)),
            "reminder_frequency": rem_freq,
            "reminder_threshold_pct": rem_pct,
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
    lang = str(settings.get("language", "en")).strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    rem_freq = str(settings.get("reminder_frequency", "weekly")).strip().lower()
    if rem_freq not in SUPPORTED_REMINDER_FREQS:
        rem_freq = "weekly"
    try:
        rem_pct = max(5, min(50, int(settings.get("reminder_threshold_pct", 15))))
    except (TypeError, ValueError):
        rem_pct = 15
    cleaned = {
        "exclusions": list(dict.fromkeys(str(x) for x in settings.get("exclusions", []) if x)),
        "default_delete_mode": mode,
        "theme": theme,
        "auto_check_updates": bool(settings.get("auto_check_updates", False)),
        "disclaimer_accepted_version": str(settings.get("disclaimer_accepted_version", "") or "")[:32],
        "custom_presets": _clean_custom_presets(settings.get("custom_presets", [])),
        "language": lang,
        "reminder_enabled": bool(settings.get("reminder_enabled", False)),
        "reminder_frequency": rem_freq,
        "reminder_threshold_pct": rem_pct,
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


# Bump when the first run notice text changes in a way users must see again.
DISCLAIMER_VERSION = "1"


def accept_disclaimer(auto_check_updates: bool) -> dict:
    settings = load_settings()
    settings["disclaimer_accepted_version"] = DISCLAIMER_VERSION
    settings["auto_check_updates"] = bool(auto_check_updates)
    return save_settings(settings)


def set_auto_check_updates(enabled: bool) -> dict:
    settings = load_settings()
    settings["auto_check_updates"] = bool(enabled)
    return save_settings(settings)


def get_custom_presets() -> list[dict]:
    return load_settings()["custom_presets"]


def add_custom_preset(raw_path: str, name: str = "", contents_only: bool = True) -> list[dict]:
    settings = load_settings()
    abs_path = os.path.abspath(os.path.normpath(raw_path))
    items = list(settings.get("custom_presets", []))
    target_norm = _norm_path(abs_path)
    items = [p for p in items if _norm_path(p.get("path", "")) != target_norm]
    items.append(
        {
            "id": f"custom_{abs(hash(target_norm)) & 0xFFFFFFFF:08x}",
            "name": (name or "").strip() or os.path.basename(abs_path) or abs_path,
            "path": abs_path,
            "contents_only": bool(contents_only),
        }
    )
    settings["custom_presets"] = items
    return save_settings(settings)["custom_presets"]


def remove_custom_preset(raw_path_or_id: str) -> list[dict]:
    settings = load_settings()
    needle = str(raw_path_or_id or "").strip()
    norm_needle = _norm_path(needle) if needle else ""
    settings["custom_presets"] = [
        p
        for p in settings.get("custom_presets", [])
        if p.get("id") != needle and _norm_path(p.get("path", "")) != norm_needle
    ]
    return save_settings(settings)["custom_presets"]


def get_language() -> str:
    return load_settings()["language"]


def set_language(language: str) -> dict:
    settings = load_settings()
    lang = str(language or "en").strip().lower()
    if lang in SUPPORTED_LANGUAGES:
        settings["language"] = lang
    return save_settings(settings)


def set_reminder_settings(
    enabled: bool,
    frequency: str = "weekly",
    threshold_pct: int = 15,
) -> dict:
    settings = load_settings()
    settings["reminder_enabled"] = bool(enabled)
    if str(frequency).strip().lower() in SUPPORTED_REMINDER_FREQS:
        settings["reminder_frequency"] = str(frequency).strip().lower()
    settings["reminder_threshold_pct"] = max(5, min(50, int(threshold_pct)))
    return save_settings(settings)


def append_history(entry: dict) -> dict:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": str(entry.get("action") or "Cleanup"),
        "mode": entry.get("mode", "recycle"),
        "freed_bytes": int(entry.get("freed_bytes", 0)),
        "freed_human": str(entry.get("freed_human", "0 B")),
        "deleted_count": int(entry.get("deleted_count", 0)),
        "failed_count": int(entry.get("failed_count", 0)),
        "cancelled": bool(entry.get("cancelled", False)),
        "items": list(entry.get("items", []))[:50],
        "failed": list(entry.get("failed", []))[:20],
    }
    path = _history_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
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


def get_lifetime_stats() -> dict:
    """Compute total cleanup runs and cumulative freed bytes from local history."""
    path = _history_path()
    if not path.exists():
        return {"total_runs": 0, "lifetime_freed_bytes": 0, "lifetime_freed_human": "0 B"}
    total_runs = 0
    total_freed = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    total_runs += 1
                    total_freed += max(0, int(rec.get("freed_bytes", 0) or 0))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError:
        return {"total_runs": 0, "lifetime_freed_bytes": 0, "lifetime_freed_human": "0 B"}
    return {
        "total_runs": total_runs,
        "lifetime_freed_bytes": total_freed,
        "lifetime_freed_human": format_bytes(total_freed),
    }


def clear_history() -> None:
    path = _history_path()
    if path.exists():
        path.unlink()
