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


def test_csv_uses_the_language_from_settings(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    from app.storage import load_settings, save_settings

    settings = load_settings()
    settings["language"] = "de"
    save_settings(settings)
    items = _items(tmp_path)
    out = tmp_path / "vorschau.csv"
    write_cleanup_preview(str(out), items, mode="recycle", fmt="csv")
    rows = list(csv.reader(out.open(encoding="utf-8-sig")))
    assert rows[0][0] == "DriveSweep-Bereinigungsvorschau (es wurde nichts gelöscht)"
    assert ["Bereinigungsmodus", "Papierkorb"] in rows
    header = next(r for r in rows if r and r[0] == "Name")
    assert header[1] == "Pfad" and "Was entfernt wird" in header
    data = rows[rows.index(header) + 1]
    assert data[4] == "Sicher" and data[5] == "Inhalt dieses Ordners"
    # JSON stays English for programs.
    res = write_cleanup_preview(str(tmp_path / "p.json"), items, fmt="json")
    assert json.loads(Path(res["path"]).read_text(encoding="utf-8"))["items"][0]["safety"] == "Safe"


def test_python_phrases_match_the_interface_table():
    from app.phrases import _tables, phrase

    tables = _tables()
    assert set(tables) == {"es", "fr", "de", "pt"} and all(len(t) > 500 for t in tables.values())
    assert phrase("Recycle Bin", "es") == "Papelera"
    assert phrase("Moved {size} of temporary files to the Recycle Bin. Open DriveSweep's Cleanup Log to see them or undo.",
                  "pt", size="2 GB").startswith("2 GB de arquivos")
    assert phrase("Not a phrase in the table", "fr") == "Not a phrase in the table"
    assert phrase("Recycle Bin", "en") == "Recycle Bin"
