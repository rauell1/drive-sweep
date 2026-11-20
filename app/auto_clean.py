"""Optional scheduled cleanup of Safe items (off by default).

When the user turns it on in Settings, each run of the scheduled reminder task also cleans the
Quick Clean items that are marked Safe and recommended, to the Recycle Bin. It never touches:
- items marked Caution or System, or not recommended by default
- items on the Always Keep list
- items whose app is running (their files are in use)
- custom folders the user added (those always need a manual review)

The cleanup is logged like a manual one, so it shows in the Cleanup Log and Undo can reverse it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.presets import scan_smart_presets
from app.safety import delete_targets, format_bytes
from app.storage import append_history, get_exclusions, load_settings, save_settings

SCHEDULED_ACTION = "Cleanup (Scheduled)"


def is_enabled() -> bool:
    return bool(load_settings().get("auto_clean_safe", False))


def set_enabled(enabled: bool) -> dict:
    settings = load_settings()
    settings["auto_clean_safe"] = bool(enabled)
    return save_settings(settings)


def pick_targets(scan: dict) -> list[dict]:
    """The Quick Clean items a scheduled cleanup may remove."""
    targets = []
    for item in scan.get("items", []) or []:
        if item.get("risk_level") != "safe" or not item.get("default_checked"):
            continue
        if item.get("excluded") or item.get("running_app") or item.get("is_custom") or item.get("is_docker_prune"):
            continue
        if int(item.get("size_bytes") or 0) <= 0 or not item.get("path"):
            continue
        targets.append({"path": item["path"], "contents_only": bool(item.get("contents_only"))})
    return targets


def run_scheduled_cleanup() -> dict:
    """Clean the Safe items to the Recycle Bin and log it. Returns a short summary."""
    exclusions = get_exclusions()
    targets = pick_targets(scan_smart_presets(exclusions=exclusions))
    if not targets:
        return {"ok": True, "cleaned": False, "freed_bytes": 0, "freed_human": "0 B", "deleted_count": 0}
    started_at = datetime.now(timezone.utc).isoformat()
    result = delete_targets(targets, mode="recycle", exclusions=exclusions)
    append_history({
        "action": SCHEDULED_ACTION,
        "mode": result.mode,
        "freed_bytes": result.freed_bytes,
        "freed_human": format_bytes(result.freed_bytes),
        "deleted_count": result.deleted_count,
        "failed_count": len(result.failed),
        "items": [d["path"] for d in result.deleted],
        "failed": result.failed,
        "started_at": started_at,
        "roots": [d["path"] for d in result.deleted],
    })
    return {
        "ok": True,
        "cleaned": result.freed_bytes > 0,
        "freed_bytes": result.freed_bytes,
        "freed_human": format_bytes(result.freed_bytes),
        "deleted_count": result.deleted_count,
        "failed_count": len(result.failed),
    }
