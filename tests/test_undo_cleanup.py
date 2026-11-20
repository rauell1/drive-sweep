"""Undo last cleanup: reading the Recycle Bin and putting items back where they were."""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.recycle_restore import find_cleanup_items, list_recycled, parse_info_file, restore_items

_EPOCH = 116444736000000000


def _filetime(when: datetime) -> int:
    return int(when.timestamp() * 10_000_000) + _EPOCH


def _info_v2(path: str, size: int, when: datetime) -> bytes:
    encoded = (path + "\x00").encode("utf-16-le")
    return struct.pack("<qqqi", 2, size, _filetime(when), len(encoded) // 2) + encoded


def _info_v1(path: str, size: int, when: datetime) -> bytes:
    encoded = path.encode("utf-16-le").ljust(520, b"\x00")
    return struct.pack("<qqq", 1, size, _filetime(when)) + encoded


def _recycle(bin_user: Path, ident: str, original: Path, when: datetime, *, folder: bool = False) -> None:
    """Move ``original`` into a fake Recycle Bin the way Windows does: $R holds it, $I describes it."""
    data = bin_user / f"$R{ident}"
    size = 0
    if folder:
        original.rename(data)
        size = sum(f.stat().st_size for f in data.rglob("*") if f.is_file())
    else:
        size = original.stat().st_size
        original.rename(data)
    (bin_user / f"$I{ident}").write_bytes(_info_v2(str(original), size, when))


def test_parse_info_file_versions():
    when = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    for maker in (_info_v1, _info_v2):
        path, size, deleted = parse_info_file(maker(r"C:\Users\Alex\AppData\Local\Temp\a.tmp", 1234, when))
        assert path == r"C:\Users\Alex\AppData\Local\Temp\a.tmp"
        assert size == 1234
        assert abs((deleted - when).total_seconds()) < 1
    assert parse_info_file(b"") is None
    assert parse_info_file(struct.pack("<qqq", 9, 1, 1) + b"x" * 40) is None
    assert parse_info_file(struct.pack("<qqqi", 2, 1, _filetime(when), 999)) is None  # length past the end


def test_undo_restores_only_this_cleanups_items(tmp_path: Path):
    temp = tmp_path / "Temp"
    temp.mkdir()
    (temp / "a.tmp").write_bytes(b"A" * 100)
    (temp / "sub").mkdir()
    (temp / "sub" / "b.tmp").write_bytes(b"B" * 50)
    other = tmp_path / "Documents"
    other.mkdir()
    (other / "report.docx").write_bytes(b"R" * 10)
    old = tmp_path / "Temp" / "old.tmp"
    old.write_bytes(b"O" * 5)

    bin_user = tmp_path / "$Recycle.Bin" / "S-1-5-21-1000"
    bin_user.mkdir(parents=True)
    start = datetime.now(timezone.utc)
    _recycle(bin_user, "OLD001.tmp", old, start - timedelta(days=3))  # deleted days earlier
    _recycle(bin_user, "AAA001.tmp", temp / "a.tmp", start + timedelta(seconds=1))
    _recycle(bin_user, "AAA002", temp / "sub", start + timedelta(seconds=2), folder=True)
    _recycle(bin_user, "DOC001.docx", other / "report.docx", start + timedelta(seconds=2))  # not in the cleanup
    finish = start + timedelta(seconds=3)

    bins = [tmp_path / "$Recycle.Bin"]
    assert len(list_recycled(bins)) == 4
    items = find_cleanup_items([str(temp)], start, finish, bin_roots=bins)
    assert [Path(i.original_path).name for i in items] == ["sub", "a.tmp"]

    res = restore_items(items)
    assert res["restored_count"] == 2 and res["restored_bytes"] == 150 and res["ok"]
    assert (temp / "a.tmp").read_bytes() == b"A" * 100
    assert (temp / "sub" / "b.tmp").read_bytes() == b"B" * 50
    # Items from other deletions stay in the Recycle Bin.
    assert not (other / "report.docx").exists() and not old.exists()
    assert {p.name for p in bin_user.iterdir()} == {"$IOLD001.tmp", "$ROLD001.tmp", "$IDOC001.docx", "$RDOC001.docx"}


def test_undo_never_overwrites_existing_files(tmp_path: Path):
    temp = tmp_path / "Temp"
    temp.mkdir()
    f = temp / "cache.bin"
    f.write_bytes(b"old")
    bin_user = tmp_path / "$Recycle.Bin" / "S-1"
    bin_user.mkdir(parents=True)
    start = datetime.now(timezone.utc)
    _recycle(bin_user, "X1.bin", f, start)
    f.write_bytes(b"new copy made by the app")  # the app recreated its cache after cleanup

    items = find_cleanup_items([str(temp)], start, start, bin_roots=[tmp_path / "$Recycle.Bin"])
    res = restore_items(items)
    assert res["restored_count"] == 0 and len(res["skipped"]) == 1
    assert f.read_bytes() == b"new copy made by the app"
    assert (bin_user / "$RX1.bin").exists()


def test_undo_api_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    import app.api as api_mod
    from app.storage import append_history, get_lifetime_stats

    monkeypatch.setattr(api_mod, "_undo_supported", lambda: True)
    api = api_mod.DriveSweepAPI()

    assert api.get_undo_candidate()["ok"] is False  # nothing cleaned yet
    temp = tmp_path / "Temp"
    temp.mkdir()
    (temp / "a.tmp").write_bytes(b"A" * 100)
    bin_root = tmp_path / "$Recycle.Bin"
    bin_user = bin_root / "S-1"
    bin_user.mkdir(parents=True)
    start = datetime.now(timezone.utc)
    _recycle(bin_user, "A1.tmp", temp / "a.tmp", start)
    append_history({
        "action": "Cleanup", "mode": "recycle", "freed_bytes": 100, "deleted_count": 1,
        "items": [str(temp)], "started_at": start.isoformat(), "roots": [str(temp)],
    })
    real_find = api_mod.find_cleanup_items
    monkeypatch.setattr(api_mod, "find_cleanup_items", lambda roots, s, f: real_find(roots, s, f, bin_roots=[bin_root]))

    cand = api.get_undo_candidate()
    assert cand["ok"] and cand["item_count"] == 1 and cand["size_bytes"] == 100
    assert api.undo_last_cleanup()["ok"] is False  # needs confirmation
    assert (temp / "a.tmp").exists() is False

    res = api.undo_last_cleanup(True)
    assert res["restored_count"] == 1 and (temp / "a.tmp").exists()
    assert get_lifetime_stats()["lifetime_freed_bytes"] == 0  # the restored space no longer counts
    again = api.get_undo_candidate()
    assert again["ok"] is False and "already" in again["reason"]


def test_permanent_cleanup_cannot_be_undone(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    import app.api as api_mod
    from app.storage import append_history

    monkeypatch.setattr(api_mod, "_undo_supported", lambda: True)
    append_history({"action": "Cleanup", "mode": "permanent", "freed_bytes": 5, "started_at": "x", "roots": ["C:\\x"]})
    cand = api_mod.DriveSweepAPI().get_undo_candidate()
    assert cand["ok"] is False and "permanently" in cand["reason"]


def test_undo_an_earlier_cleanup_by_timestamp(tmp_path: Path, monkeypatch):
    """Each eligible Cleanup Log entry can be undone, not only the latest, and only its own items return."""
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    import app.api as api_mod
    from app.recycle_restore import list_recycled
    from app.storage import append_history, get_history

    monkeypatch.setattr(api_mod, "_undo_supported", lambda: True)
    bin_root = tmp_path / "$Recycle.Bin"
    bin_user = bin_root / "S-1"
    bin_user.mkdir(parents=True)
    real_find = api_mod.find_cleanup_items
    monkeypatch.setattr(api_mod, "find_cleanup_items",
                        lambda roots, s, f, recycled=None: real_find(roots, s, f, bin_roots=[bin_root], recycled=recycled))
    monkeypatch.setattr(api_mod, "list_recycled", lambda: list_recycled([bin_root]))

    first, second = tmp_path / "TempA", tmp_path / "TempB"
    for folder in (first, second):
        folder.mkdir()
        (folder / "x.tmp").write_bytes(b"x" * 10)
    t1 = datetime.now(timezone.utc) - timedelta(hours=2)
    _recycle(bin_user, "A1.tmp", first / "x.tmp", t1)
    append_history({"action": "Cleanup", "mode": "recycle", "freed_bytes": 10, "started_at": t1.isoformat(), "roots": [str(first)]})
    # append_history stamps "now"; move the first record's timestamp back so the windows do not overlap.
    log = tmp_path / "appdata" / "history.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    import json as _json
    rec = _json.loads(lines[0])
    rec["timestamp"] = (t1 + timedelta(seconds=1)).isoformat()
    log.write_text(_json.dumps(rec) + "\n", encoding="utf-8")
    t2 = datetime.now(timezone.utc)
    _recycle(bin_user, "B1.tmp", second / "x.tmp", t2)
    append_history({"action": "Cleanup", "mode": "recycle", "freed_bytes": 10, "started_at": t2.isoformat(), "roots": [str(second)]})

    api = api_mod.DriveSweepAPI()
    cands = api.get_undo_candidates()["candidates"]
    assert set(cands) == {h["timestamp"] for h in get_history(10)}
    older_ts = rec["timestamp"]
    assert api.get_undo_candidate(older_ts)["item_count"] == 1

    res = api.undo_last_cleanup(True, older_ts)
    assert res["restored_count"] == 1
    assert (first / "x.tmp").exists() and not (second / "x.tmp").exists()  # only that cleanup's file
    again = api.get_undo_candidate(older_ts)
    assert again["ok"] is False and "already" in again["reason"]
    assert set(api.get_undo_candidates()["candidates"]) == {get_history(10)[1]["timestamp"]}  # newer one still undoable
    assert api.get_undo_candidate("not-a-timestamp")["ok"] is False
