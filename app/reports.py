"""Preview report: a list of what a cleanup would remove, written before anything is touched.

The interface sends the current selection (the same items the Clean button would remove); this
module writes it as CSV (opens in Excel) or JSON. Nothing is deleted or changed.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from app.phrases import current_language, phrase
from app.safety import format_bytes
from app.scanner import _SafeCsvWriter

MAX_PREVIEW_ITEMS = 20000
_RISK_LABELS = {"safe": "Safe", "caution": "Caution", "critical": "System"}
# Fixed values written into the CSV, translated there (listed so the translation test covers them).
REPORT_PHRASES = ("Safe", "Caution", "System", "Contents of this folder", "This item", "Delete Forever", "Recycle Bin")


def _clean_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    path = str(raw.get("path") or "").strip()
    if not path:
        return None
    try:
        size = max(0, int(raw.get("size_bytes") or 0))
    except (TypeError, ValueError):
        size = 0
    risk = str(raw.get("risk_level") or "safe").lower()
    return {
        "name": str(raw.get("label") or raw.get("name") or Path(path).name)[:500],
        "path": path[:4000],
        "size_bytes": size,
        "size_human": format_bytes(size),
        "safety": _RISK_LABELS.get(risk, "Safe"),
        "what_is_removed": "Contents of this folder" if raw.get("contents_only") else "This item",
        "note": str(raw.get("risk_reason") or raw.get("safety_note") or "")[:2000],
    }


def write_cleanup_preview(output_path: str, items: list, mode: str = "recycle", fmt: str = "csv") -> dict:
    """Write the selection to ``output_path``. Returns counts for the confirmation message."""
    norm_fmt = "json" if str(fmt or "").strip().lower() == "json" else "csv"
    rows = [r for r in (_clean_item(i) for i in list(items or [])[:MAX_PREVIEW_ITEMS]) if r]
    if not rows:
        return {"ok": False, "error": "Nothing is selected, so there is nothing to export."}
    total = sum(r["size_bytes"] for r in rows)
    mode_label = "Delete Forever" if mode == "permanent" else "Recycle Bin"
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec="seconds")

    if norm_fmt == "json":
        payload = {
            "report": "DriveSweep cleanup preview (nothing has been deleted)",
            "generated_at": generated_at,
            "cleanup_mode": mode_label,
            "item_count": len(rows),
            "total_bytes": total,
            "total_human": format_bytes(total),
            "items": rows,
        }
        dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        # The CSV is for people (it opens in Excel), so it uses the language chosen in Settings.
        # JSON stays in English because programs read it.
        lang = current_language()

        def t(text: str) -> str:
            return phrase(text, lang)

        with dest.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = _SafeCsvWriter(csv.writer(fh))
            writer.writerow([t("DriveSweep cleanup preview (nothing has been deleted)")])
            writer.writerow([t("Generated"), generated_at])
            writer.writerow([t("Cleanup mode"), t(mode_label)])
            writer.writerow([t("Items"), len(rows)])
            writer.writerow([t("Total size"), format_bytes(total)])
            writer.writerow([])
            writer.writerow([t("Name"), t("Path"), t("Size (Bytes)"), t("Size"), t("Safety"), t("What is removed"), t("Note")])
            for r in rows:
                writer.writerow([
                    r["name"], r["path"], r["size_bytes"], r["size_human"],
                    t(r["safety"]), t(r["what_is_removed"]), r["note"],
                ])
    return {
        "ok": True,
        "path": str(dest),
        "format": norm_fmt,
        "item_count": len(rows),
        "total_bytes": total,
        "total_human": format_bytes(total),
    }
