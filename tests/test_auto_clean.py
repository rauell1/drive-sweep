"""Scheduled cleanup of Safe items: off by default, cleans only Safe recommended items, is logged."""

from __future__ import annotations

from pathlib import Path


def _item(path, **kw):
    base = {"path": str(path), "risk_level": "safe", "default_checked": True, "excluded": False,
            "running_app": None, "is_custom": False, "is_docker_prune": False, "size_bytes": 100,
            "contents_only": True}
    base.update(kw)
    return base


def test_pick_targets_only_safe_recommended_items(tmp_path: Path):
    from app.auto_clean import pick_targets

    scan = {"items": [
        _item(tmp_path / "ok"),
        _item(tmp_path / "caution", risk_level="caution"),
        _item(tmp_path / "not-recommended", default_checked=False),
        _item(tmp_path / "kept", excluded=True),
        _item(tmp_path / "running", running_app="Chrome"),
        _item(tmp_path / "custom", is_custom=True),
        _item(tmp_path / "docker", is_docker_prune=True),
        _item(tmp_path / "empty", size_bytes=0),
    ]}
    assert pick_targets(scan) == [{"path": str(tmp_path / "ok"), "contents_only": True}]


def test_setting_is_off_by_default_and_saved(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    from app.auto_clean import is_enabled, set_enabled
    from app.storage import load_settings

    assert is_enabled() is False
    set_enabled(True)
    assert load_settings()["auto_clean_safe"] is True
    set_enabled(False)
    assert is_enabled() is False


def test_scheduled_run_cleans_to_recycle_bin_and_is_undoable(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    import app.auto_clean as ac
    from app.storage import get_history

    temp = tmp_path / "Temp"
    temp.mkdir()
    (temp / "a.tmp").write_bytes(b"x" * 100)
    monkeypatch.setattr(ac, "scan_smart_presets", lambda exclusions=None: {"items": [_item(temp)]})
    calls = {}

    class Result:
        mode = "recycle"
        freed_bytes = 100
        deleted_count = 1
        failed: list = []
        deleted = [{"path": str(temp)}]

    def fake_delete(targets, mode, exclusions):
        calls["mode"], calls["targets"] = mode, targets
        return Result()

    monkeypatch.setattr(ac, "delete_targets", fake_delete)
    res = ac.run_scheduled_cleanup()
    assert res["cleaned"] and calls["mode"] == "recycle"
    rec = get_history(1)[0]
    assert rec["action"] == ac.SCHEDULED_ACTION and rec["action"].startswith("Cleanup")
    assert rec["started_at"] and rec["roots"] == [str(temp)]


def test_reminder_api_keeps_task_for_auto_clean(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DRIVESWEEP_DATA_DIR", str(tmp_path / "appdata"))
    import app.api as api_mod

    seen = []
    monkeypatch.setattr(api_mod, "configure_windows_reminder_task",
                        lambda enabled, frequency="weekly": seen.append(enabled) or {"ok": True, "installed": enabled})
    api = api_mod.DriveSweepAPI()
    res = api.configure_disk_reminder(False, "weekly", 15, True)
    assert seen[-1] is True and res["auto_clean_safe"] is True and res["enabled"] is False
    res = api.configure_disk_reminder(False, "weekly", 15, False)
    assert seen[-1] is False and res["auto_clean_safe"] is False
