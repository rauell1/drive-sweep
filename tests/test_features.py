"""Tests for DriveSweep v0.3.0 features (Steps 1 through 7)."""

from __future__ import annotations

import csv
import json
import os
import struct
import time
from pathlib import Path

from app.api import DriveSweepAPI
from app.duplicates import find_duplicates
from app.ntfs_mft import (
    apply_usa_fixup,
    decode_data_runs,
    parse_ntfs_boot_sector,
    scan_ntfs_mft_with_reader,
    try_ntfs_mft_scan,
)
from app.presets import scan_smart_presets
from app.safety import ScanGuard
from app.scanner import DEV_BLOAT_NAMES, DirNode, DriveScanner
from app.scheduler import build_schtasks_create_command, evaluate_low_disk_alerts
from app.storage import (
    add_custom_preset,
    get_custom_presets,
    get_language,
    load_settings,
    remove_custom_preset,
    set_language,
    set_reminder_settings,
)
from app.system_tools import (
    find_old_download_installers,
    find_wsl_docker_vhdx,
    get_recycle_bin_info,
    parse_dism_analyze_output,
)


def _wait_scan(scanner: DriveScanner) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = scanner.get_status()
        if st["status"] != "scanning":
            return st
        time.sleep(0.02)
    return scanner.get_status()


def test_duplicate_finder_exact_sha256_and_keep_recommendation(tmp_path: Path):
    f1 = tmp_path / "alpha" / "archive_copy1.bin"
    f2 = tmp_path / "beta" / "archive_copy2.bin"
    f3 = tmp_path / "beta" / "same_size_different.bin"
    f1.parent.mkdir(parents=True)
    f2.parent.mkdir(parents=True)

    payload_dup = b"DriveSweepDuplicateTestBlock!" * 4500
    payload_diff = b"AnotherUniqueContentPayload!!" * 4500
    assert len(payload_dup) == len(payload_diff)

    f1.write_bytes(payload_dup)
    time.sleep(0.03)
    f2.write_bytes(payload_dup)
    f3.write_bytes(payload_diff)

    scanner = DriveScanner()
    scanner.start_scan(str(tmp_path), force=True)
    st = _wait_scan(scanner)
    assert st["status"] == "done"

    res = find_duplicates(scanner.get_nodes_snapshot(), min_size_bytes=4096)
    assert res["total_groups"] == 1
    grp = res["groups"][0]
    assert grp["copy_count"] == 2
    assert grp["size_bytes"] == len(payload_dup)
    assert grp["reclaimable_bytes"] == len(payload_dup)
    keep_flags = [c["keep_recommended"] for c in grp["copies"]]
    assert keep_flags.count(True) == 1
    kept = [c for c in grp["copies"] if c["keep_recommended"]][0]
    assert kept["path"] == str(f2)


def _build_boot_sector(
    bytes_per_sector: int = 512,
    sectors_per_cluster: int = 8,
    mft_cluster: int = 100,
    clusters_per_mft_raw: int = 0xF6,  # signed -10 -> 2^10 = 1024 bytes per record
) -> bytes:
    buf = bytearray(512)
    buf[3:11] = b"NTFS    "
    struct.pack_into("<H", buf, 0x0B, bytes_per_sector)
    buf[0x0D] = sectors_per_cluster
    struct.pack_into("<Q", buf, 0x30, mft_cluster)
    buf[0x40] = clusters_per_mft_raw
    return bytes(buf)


def _build_file_record(
    record_size: int,
    rec_idx: int,
    parent_ref_idx: int,
    name: str,
    *,
    is_dir: bool = False,
    data_size: int | None = None,
    reparse: bool = False,
) -> bytes:
    rec = bytearray(record_size)
    rec[0:4] = b"FILE"
    usa_offset = 48
    usa_count = 3  # header + 2 x 512B sectors
    struct.pack_into("<H", rec, 4, usa_offset)
    struct.pack_into("<H", rec, 6, usa_count)
    struct.pack_into("<H", rec, 20, 56)  # first_attr_off
    flags = 0x0001 | (0x0002 if is_dir else 0x0000)
    struct.pack_into("<H", rec, 22, flags)
    struct.pack_into("<I", rec, 44, rec_idx)

    # USA sequence value + original sector tail bytes
    seq = 0x1122
    struct.pack_into("<H", rec, usa_offset, seq)
    struct.pack_into("<H", rec, usa_offset + 2, 0x0000)
    struct.pack_into("<H", rec, usa_offset + 4, 0x0000)

    off = 56
    # $STANDARD_INFORMATION (0x10)
    si_len = 24 + 48
    struct.pack_into("<II", rec, off, 0x10, si_len)
    rec[off + 8] = 0  # resident
    struct.pack_into("<I", rec, off + 16, 48)
    struct.pack_into("<H", rec, off + 20, 24)
    # Windows FILETIME for 2025-01-01 (~133800000000000000)
    struct.pack_into("<Q", rec, off + 24 + 8, 133800000000000000)
    file_attrs = 0x0400 if reparse else 0x0000
    struct.pack_into("<I", rec, off + 24 + 32, file_attrs)
    off += si_len

    # $FILE_NAME (0x30)
    name_utf16 = name.encode("utf-16-le")
    fn_val_len = 66 + len(name_utf16)
    fn_attr_len = ((24 + fn_val_len + 7) // 8) * 8
    struct.pack_into("<II", rec, off, 0x30, fn_attr_len)
    rec[off + 8] = 0
    struct.pack_into("<I", rec, off + 16, fn_val_len)
    struct.pack_into("<H", rec, off + 20, 24)
    struct.pack_into("<Q", rec, off + 24, parent_ref_idx)
    rec[off + 24 + 64] = len(name)
    rec[off + 24 + 65] = 1  # Win32 namespace
    rec[off + 24 + 66 : off + 24 + 66 + len(name_utf16)] = name_utf16
    off += fn_attr_len

    # Optional resident $DATA (0x80)
    if data_size is not None and not is_dir:
        data_attr_len = 24
        struct.pack_into("<II", rec, off, 0x80, data_attr_len)
        rec[off + 8] = 0  # resident
        struct.pack_into("<I", rec, off + 16, data_size)
        struct.pack_into("<H", rec, off + 20, 24)
        off += data_attr_len

    struct.pack_into("<I", rec, off, 0xFFFFFFFF)

    # Stamp USA fixup markers at sector boundaries (510 and 1022)
    struct.pack_into("<H", rec, usa_offset + 2, struct.unpack_from("<H", rec, 510)[0])
    struct.pack_into("<H", rec, usa_offset + 4, struct.unpack_from("<H", rec, 1022)[0])
    struct.pack_into("<H", rec, 510, seq)
    struct.pack_into("<H", rec, 1022, seq)
    return bytes(rec)


def test_ntfs_boot_runs_usa_and_synthetic_mft_scan(tmp_path: Path):
    boot = _build_boot_sector()
    geom = parse_ntfs_boot_sector(boot)
    assert geom is not None
    assert geom.bytes_per_sector == 512
    assert geom.cluster_size == 4096
    assert geom.mft_record_size == 1024
    assert geom.mft_lcn == 100

    # Data run: len_field=1, off_field=1 -> header 0x11, len=4, lcn=+100 -> [(100, 4)]
    runs = decode_data_runs(bytes([0x11, 0x04, 0x64, 0x11, 0x02, 0xF0, 0x00]))
    assert runs == [(100, 4), (84, 2)]

    # Build synthetic 19-record MFT (root idx = 5, user entries start at idx >= 16)
    rsize = geom.mft_record_size
    empty = bytearray(rsize)
    rec5 = _build_file_record(rsize, 5, 5, ".", is_dir=True)
    rec16 = _build_file_record(rsize, 16, 5, "node_modules", is_dir=True)
    rec17 = _build_file_record(rsize, 17, 16, "bundle.js", is_dir=False, data_size=4096)
    rec18 = _build_file_record(rsize, 18, 5, "LinkDir", is_dir=True, reparse=True)

    # Record 0 = $MFT self-record with non-resident $DATA describing 19 records (5 clusters)
    rec0 = bytearray(_build_file_record(rsize, 0, 5, "$MFT", is_dir=False))
    # Append non-resident $DATA right before 0xFFFFFFFF
    end_idx = rec0.index(b"\xFF\xFF\xFF\xFF")
    mft_data_run = bytes([0x11, 0x05, 0x64, 0x00])  # 5 clusters starting at cluster 100
    attr_off = end_idx
    struct.pack_into("<II", rec0, attr_off, 0x80, 72)
    rec0[attr_off + 8] = 1  # non-resident
    struct.pack_into("<H", rec0, attr_off + 32, 64)  # run_offset
    struct.pack_into("<Q", rec0, attr_off + 48, 19 * rsize)  # data_size
    rec0[attr_off + 64 : attr_off + 64 + len(mft_data_run)] = mft_data_run
    struct.pack_into("<I", rec0, attr_off + 72, 0xFFFFFFFF)
    # Re-apply USA fixup markers on rec0
    seq0 = struct.unpack_from("<H", rec0, 48)[0]
    struct.pack_into("<H", rec0, 50, struct.unpack_from("<H", rec0, 510)[0])
    struct.pack_into("<H", rec0, 52, struct.unpack_from("<H", rec0, 1022)[0])
    struct.pack_into("<H", rec0, 510, seq0)
    struct.pack_into("<H", rec0, 1022, seq0)

    fixed_test = apply_usa_fixup(bytearray(rec17), 512)
    assert fixed_test is not None

    mft_blob = bytes(rec0) + (bytes(empty) * 4) + rec5 + (bytes(empty) * 10) + rec16 + rec17 + rec18
    mft_base = geom.mft_lcn * geom.cluster_size

    def fake_read_at(offset: int, length: int) -> bytes:
        if offset == 0:
            return (boot + (b"\x00" * max(0, length - 512)))[:length]
        rel = offset - mft_base
        if rel < 0 or rel >= len(mft_blob):
            return b"\x00" * length
        chunk = mft_blob[rel : rel + length]
        if len(chunk) < length:
            chunk += b"\x00" * (length - len(chunk))
        return chunk

    res_mft = scan_ntfs_mft_with_reader(
        "Z:\\",
        fake_read_at,
        guard=ScanGuard(),
        dev_bloat_names=DEV_BLOAT_NAMES,
        dir_node_cls=DirNode,
    )
    assert res_mft is not None
    nodes, dev_paths, files_scanned, dirs_scanned, total_bytes = res_mft
    assert dirs_scanned == 2  # Z:\ and Z:\node_modules (reparse LinkDir skipped)
    assert files_scanned == 1
    assert total_bytes == 4096
    assert "Z:\\node_modules" in dev_paths
    assert nodes["Z:\\node_modules"].files[0][0] == "bundle.js"

    # Non-root paths cleanly skip MFT path and return None for fast_scandir fallback
    assert try_ntfs_mft_scan(
        str(tmp_path),
        guard=ScanGuard(),
        dev_bloat_names=DEV_BLOAT_NAMES,
        dir_node_cls=DirNode,
    ) is None


def test_system_tools_installers_vhdx_and_dism_parser(tmp_path: Path):
    dl = tmp_path / "Downloads"
    dl.mkdir()
    old_exe = dl / "old-installer.exe"
    recent_exe = dl / "fresh-installer.exe"
    old_note = dl / "old-readme.txt"
    old_exe.write_bytes(b"MZ" + b"0" * 4096)
    recent_exe.write_bytes(b"MZ" + b"1" * 2048)
    old_note.write_bytes(b"ignore text files")

    past = time.time() - (45 * 86400)
    os.utime(old_exe, (past, past))
    os.utime(old_note, (past, past))

    report = find_old_download_installers(max_age_days=30, downloads_dir=dl)
    assert report["exists"] is True
    assert report["count"] == 1
    assert report["items"][0]["name"] == "old-installer.exe"

    local = tmp_path / "Local"
    vhdx_file = local / "Docker" / "wsl" / "disk" / "docker_data.vhdx"
    vhdx_file.parent.mkdir(parents=True)
    vhdx_file.write_bytes(b"vhdx" * 1024)
    vhdx_rep = find_wsl_docker_vhdx(local_app_data=local, program_data=tmp_path / "None")
    assert vhdx_rep["count"] == 1
    assert vhdx_rep["items"][0]["name"] == "docker_data.vhdx"

    sample_dism = """
    Deployment Image Servicing and Management tool
    Windows Explorer Reported Size of Component Store : 8.42 GB
    Backups and Disabled Features : 1.15 GB
    Cache and Temporary Data : 240.00 MB
    Number of Reclaimable Packages : 3
    Component Store Cleanup Recommended : Yes
    """
    parsed = parse_dism_analyze_output(sample_dism)
    assert parsed["component_store_size"] == "8.42 GB"
    assert parsed["reclaimable_packages"] == "3"
    assert parsed["cleanup_recommended"] is True

    rb = get_recycle_bin_info()
    assert "size_bytes" in rb and "item_count" in rb


def test_treemap_drilldown_and_csv_json_exports(tmp_path: Path):
    sub_a = tmp_path / "Media"
    sub_a_nested = sub_a / "Clips"
    sub_a_nested.mkdir(parents=True)
    (sub_a_nested / "video.mp4").write_bytes(b"V" * 8000)
    (tmp_path / "root.log").write_bytes(b"L" * 1000)

    scanner = DriveScanner()
    scanner.start_scan(str(tmp_path), force=True)
    assert _wait_scan(scanner)["status"] == "done"

    tm_root = scanner.get_treemap_data()
    assert tm_root["total_bytes"] == 9000
    assert len(tm_root["breadcrumbs"]) == 1
    names = [it["name"] for it in tm_root["items"]]
    assert "Media" in names
    assert any(n.startswith("Direct Files") for n in names)

    tm_sub = scanner.get_treemap_data(str(sub_a))
    assert len(tm_sub["breadcrumbs"]) == 2
    assert tm_sub["items"][0]["name"] == "Clips"

    csv_path = tmp_path / "exports" / "report.csv"
    json_path = tmp_path / "exports" / "report.json"
    res_csv = scanner.export_scan_report(str(csv_path), fmt="csv")
    res_json = scanner.export_scan_report(str(json_path), fmt="json")

    assert res_csv["ok"] and csv_path.exists()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0] == "Type"
    assert any("video.mp4" in r for r in rows)

    assert res_json["ok"] and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total_bytes"] == 9000
    assert payload["largest_files"][0]["name"] == "video.mp4"


def test_custom_presets_language_and_scheduler(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))

    custom_dir = tmp_path / "MyBuildScratch"
    custom_dir.mkdir()
    (custom_dir / "temp.bin").write_bytes(b"X" * 2048)

    items = add_custom_preset(str(custom_dir), name="Build Scratch")
    assert len(items) == 1
    assert get_custom_presets()[0]["name"] == "Build Scratch"

    # API blocks adding critical Windows OS folder as a custom preset
    api = DriveSweepAPI()
    blocked = api.add_custom_preset("C:\\Windows\\System32", name="Unsafe")
    assert blocked["ok"] is False

    smart = scan_smart_presets(exclusions=[], custom_presets=get_custom_presets())
    custom_hits = [it for it in smart["items"] if it.get("group") == "Custom Folders"]
    assert len(custom_hits) == 1
    assert custom_hits[0]["is_custom"] is True
    assert custom_hits[0]["size_bytes"] == 2048
    assert custom_hits[0]["default_checked"] is False

    assert remove_custom_preset(items[0]["id"]) == []

    # Language & reminder settings persistence + clamping
    set_language("es")
    assert get_language() == "es"
    set_language("xx")  # unsupported value ignored
    assert get_language() == "es"

    set_reminder_settings(True, frequency="daily", threshold_pct=99)
    st = load_settings()
    assert st["reminder_enabled"] is True
    assert st["reminder_frequency"] == "daily"
    assert st["reminder_threshold_pct"] == 50

    info = api.get_app_info()
    assert info["language"] == "es"
    assert "low_disk_alerts" in info

    # Low disk evaluation + schtasks command builder
    alerts = evaluate_low_disk_alerts(
        threshold_free_pct=15,
        drives=[
            {"drive": "C:\\", "total_bytes": 1000, "free_bytes": 50},
            {"drive": "D:\\", "total_bytes": 1000, "free_bytes": 400},
        ],
    )
    assert alerts["has_alerts"] is True
    assert len(alerts["alerts"]) == 1
    assert alerts["alerts"][0]["drive"] == "C:\\"
    assert alerts["alerts"][0]["severity"] == "critical"

    cmd = build_schtasks_create_command(frequency="weekly")
    assert "schtasks.exe" in cmd and "WEEKLY" in cmd and "/Create" in cmd
