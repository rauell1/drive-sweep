"""Preview report: the selection is saved as a list and nothing is deleted."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.reports import write_cleanup_preview


def _items(tmp_path: Path) -> list[dict]:
    keep = tmp_path / "Temp"
    keep.mkdir()
    (keep / "a.tmp").write_bytes(b"x" * 10)
    return [
        {"label": "User Temporary Files", "path": str(keep), "size_bytes": 2048, "risk_level": "safe",
         "risk_reason": "Temporary files.", "contents_only": True},
        {"label": "=HYPERLINK(\"http://evil\")", "path": str(tmp_path / "old.iso"), "size_bytes": "1048576",
         "risk_level": "caution"},
        {"path": ""},  # ignored
        "not a dict",  # ignored
    ]


def test_csv_preview_lists_selection_and_deletes_nothing(tmp_path: Path):
    items = _items(tmp_path)
    out = tmp_path / "out" / "preview.csv"
    res = write_cleanup_preview(str(out), items, mode="recycle", fmt="csv")
    assert res["ok"] and res["item_count"] == 2 and res["total_bytes"] == 2048 + 1048576
    assert (tmp_path / "Temp" / "a.tmp").exists()  # nothing touched
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0][0].startswith("DriveSweep cleanup preview")
    header = rows.index(["Name", "Path", "Size (Bytes)", "Size", "Safety", "What is removed", "Note"])
    data = rows[header + 1 :]
    assert data[0][0] == "User Temporary Files" and data[0][5] == "Contents of this folder"
    assert data[1][4] == "Caution"
    assert not data[1][0].startswith("=")  # spreadsheet formulas are neutralized


def test_json_preview(tmp_path: Path):
    out = tmp_path / "preview.json"
    res = write_cleanup_preview(str(out), _items(tmp_path), mode="permanent", fmt="json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert res["format"] == "json" and data["cleanup_mode"] == "Delete Forever" and data["item_count"] == 2
    assert data["items"][1]["size_bytes"] == 1048576


def test_empty_selection_is_refused(tmp_path: Path):
    res = write_cleanup_preview(str(tmp_path / "x.csv"), [], fmt="csv")
    assert res["ok"] is False and not (tmp_path / "x.csv").exists()
