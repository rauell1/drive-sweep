"""End-to-end backend lifecycle, NTFS hardening, diagnostics logger, and headless DOM UI tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import time
from pathlib import Path

from app.api import DriveSweepAPI
from app.logger import get_log_path, read_recent_logs, setup_logging
from app.ntfs_mft import (
    _parse_single_record,
    decode_data_runs,
    parse_ntfs_boot_sector,
    scan_ntfs_mft_with_reader,
)
from app.safety import ScanGuard
from app.scanner import DEV_BLOAT_NAMES, DirNode

REPO_ROOT = Path(__file__).resolve().parent.parent


def _wait_dup(api: DriveSweepAPI) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = api.get_duplicate_status()
        if st.get("status") != "running":
            return st
        time.sleep(0.02)
    return api.get_duplicate_status()


def _wait_scan_api(api: DriveSweepAPI) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = api.get_scan_status()
        if st.get("status") != "scanning":
            return st
        time.sleep(0.02)
    return api.get_scan_status()


def _wait_cleanup_api(api: DriveSweepAPI) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        st = api.get_cleanup_status()
        if st.get("status") != "running":
            return st
        time.sleep(0.02)
    return api.get_cleanup_status()


def test_diagnostics_logger_and_api_e2e_workflow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    setup_logging()

    workspace = tmp_path / "sample_drive"
    cache_dir = workspace / "CustomScratch"
    cache_dir.mkdir(parents=True)
    (cache_dir / "temp1.tmp").write_bytes(b"T" * 4096)

    dup_a = workspace / "FolderA" / "pack.zip"
    dup_b = workspace / "FolderB" / "pack_copy.zip"
    dup_a.parent.mkdir()
    dup_b.parent.mkdir()
    dup_payload = b"PK\x03\x04" + (b"Z" * 16384)
    dup_a.write_bytes(dup_payload)
    time.sleep(0.03)
    dup_b.write_bytes(dup_payload)

    api = DriveSweepAPI()
    assert api.add_custom_preset(str(cache_dir), name="Scratch Cache")["ok"] is True

    info = api.get_app_info()
    assert any(p["name"] == "Scratch Cache" for p in info["custom_presets"])

    # Scan workspace -> drill treemap -> find duplicates -> remove extra copy permanently
    api.start_drive_scan(str(workspace), force=True)
    assert _wait_scan_api(api)["status"] == "done"

    tm = api.get_treemap_data()
    assert tm["total_bytes"] == 4096 + 2 * len(dup_payload)

    dup_st = api.start_duplicate_scan(min_size_kb=4)
    assert dup_st["status"] in ("running", "done")
    dup_done = _wait_dup(api)
    assert dup_done["status"] == "done"
    groups = dup_done["result"]["groups"]
    assert len(groups) == 1
    extra = [c for c in groups[0]["copies"] if not c["keep_recommended"]][0]

    api.start_cleanup([{"path": extra["path"], "contents_only": False}], "permanent", False)
    cleanup_done = _wait_cleanup_api(api)
    assert cleanup_done["status"] == "completed"
    assert not Path(extra["path"]).exists()
    assert Path([c for c in groups[0]["copies"] if c["keep_recommended"]][0]["path"]).exists()

    # Export report fallback into Documents / temp home
    report_csv = tmp_path / "e2e_report.csv"
    exp = api.scanner.export_scan_report(str(report_csv), fmt="csv")
    assert exp["ok"] and report_csv.exists()

    # UI error telemetry written locally only
    assert api.report_ui_error("Synthetic button click test error", "app.js:123", "Error\n at fn")["ok"] is True
    diag = api.get_diagnostics_info()
    assert diag["log_path"] == str(get_log_path())
    assert "Synthetic button click test error" in read_recent_logs(50)


def test_ntfs_sparse_runs_4k_boot_and_extension_record_skip():
    # Sparse cluster run (off_size=0, cluster_len=2) + normal run (len=3, lcn=+100)
    runs = decode_data_runs(bytes([0x01, 0x02, 0x11, 0x03, 0x64, 0x00]))
    assert runs == [(-1, 2), (100, 3)]

    # MFT extension record has non-zero base_file_record at 0x20 -> cleanly skipped
    rec = bytearray(1024)
    rec[0:4] = b"FILE"
    struct.pack_into("<H", rec, 4, 48)
    struct.pack_into("<H", rec, 6, 3)
    struct.pack_into("<H", rec, 20, 56)
    struct.pack_into("<H", rec, 22, 0x0001)
    struct.pack_into("<Q", rec, 0x20, 0x0001000000000010)  # base record ref != 0
    struct.pack_into("<H", rec, 48, 0x2222)
    struct.pack_into("<H", rec, 510, 0x2222)
    struct.pack_into("<H", rec, 1022, 0x2222)
    assert _parse_single_record(rec, 512) is None

    # 4096-byte boot buffer read cleanly by scan_ntfs_mft_with_reader
    boot = bytearray(512)
    boot[3:11] = b"NTFS    "
    struct.pack_into("<H", boot, 0x0B, 512)
    boot[0x0D] = 8
    struct.pack_into("<Q", boot, 0x30, 50)
    boot[0x40] = 0xF6
    geom = parse_ntfs_boot_sector(bytes(boot))
    assert geom is not None and geom.mft_lcn == 50

    seen_reads: list[tuple[int, int]] = []

    def reader(offset: int, length: int) -> bytes:
        seen_reads.append((offset, length))
        if offset == 0:
            return bytes(boot) + (b"\x00" * max(0, length - 512))
        return b"\x00" * length

    res = scan_ntfs_mft_with_reader(
        "Z:\\",
        reader,
        guard=ScanGuard(),
        dev_bloat_names=DEV_BLOAT_NAMES,
        dir_node_cls=DirNode,
    )
    assert res is None
    assert seen_reads[0] == (0, 4096)


def test_headless_ui_i18n_and_interaction_smoke(tmp_path: Path):
    node_exe = shutil.which("node")
    assert node_exe, "Node.js is required to validate frontend JS & i18n integrity"

    html = (REPO_ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
    html_keys = sorted(set(re.findall(r'data-i18n(?:-[a-z]+)?="([^"]+)"', html)))
    assert len(html_keys) >= 25

    runner = tmp_path / "ui_harness.js"
    runner.write_text(
        f"""
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const i18nSrc = fs.readFileSync({json.dumps(str(REPO_ROOT / "app" / "ui" / "i18n.js"))}, "utf8");
const appSrc = fs.readFileSync({json.dumps(str(REPO_ROOT / "app" / "ui" / "app.js"))}, "utf8");
const htmlKeys = {json.dumps(html_keys)};

const elementMap = new Map();
function makeEl(id, tag = "div", attrs = {{}}) {{
  const el = {{
    id: id || "",
    tagName: tag.toUpperCase(),
    textContent: "",
    innerHTML: "",
    value: attrs.value || "",
    checked: !!attrs.checked,
    disabled: false,
    style: {{}},
    dataset: Object.assign({{}}, attrs.dataset || {{}}),
    children: [],
    classList: {{
      _set: new Set(attrs.active ? ["active"] : []),
      add(...xs) {{ xs.forEach((x) => this._set.add(x)); }},
      remove(...xs) {{ xs.forEach((x) => this._set.delete(x)); }},
      toggle(x, force) {{
        if (force === true) this._set.add(x);
        else if (force === false) this._set.delete(x);
        else if (this._set.has(x)) this._set.delete(x);
        else this._set.add(x);
      }},
      contains(x) {{ return this._set.has(x); }},
    }},
    _listeners: new Map(),
    addEventListener(evt, fn) {{
      if (!this._listeners.has(evt)) this._listeners.set(evt, []);
      this._listeners.get(evt).push(fn);
    }},
    getAttribute(k) {{ return attrs[k] || null; }},
    setAttribute(k, v) {{ attrs[k] = String(v); }},
    appendChild(child) {{ this.children.push(child); return child; }},
    querySelector() {{ return makeEl(""); }},
    querySelectorAll() {{ return []; }},
    focus() {{}},
    select() {{}},
  }};
  if (id) elementMap.set(id, el);
  return el;
}}

const requiredIds = [
  "view-title","view-subtitle","header-toolbar","smart-filter","btn-smart-scan",
  "btn-add-custom-preset","smart-total-metric","smart-rec-metric","smart-selected-metric",
  "smart-selected-sub","smart-count-sub","smart-breakdown-bar","smart-donut-wrap",
  "smart-cat-hint","smart-groups","nav-smart-badge","btn-smart-recommended","btn-smart-all",
  "btn-smart-none","btn-smart-collapse-toggle","btn-theme-toggle","theme-icon",
  "btn-refresh-drives","sidebar-drives","drive-cards","btn-exclusions","btn-history",
  "btn-updates-privacy","btn-system-tools","exclusions-count","history-count","app-version",
  "update-nav-badge","priv-title","priv-sub","btn-elevate","btn-pick-folder","btn-cancel-scan",
  "explorer-empty","scan-progress","explorer-workspace","explorer-summary-pill","scan-engine-badge",
  "btn-export-csv","btn-export-json","btn-explorer-rescan","risk-cards-row","treemap-controls",
  "treemap-grid","category-chart-wrap","age-chart-wrap","top-folders-table-wrap",
  "breadcrumbs","browse-query","browse-sort","browse-tbody","browse-pager","allfiles-query",
  "allfiles-ext","allfiles-minmb","allfiles-age","allfiles-sort","btn-allfiles-search",
  "allfiles-meta","allfiles-tbody","allfiles-pager","devbloat-age","devbloat-meta","devbloat-tbody",
  "dup-min-size","btn-find-dups","btn-cancel-dups","btn-dup-select-extra","dup-meta",
  "dup-progress","dup-status-label","dup-stats-text","dup-progress-fill","dup-groups",
  "selected-size","selected-count","dedup-note","btn-review-queue","btn-clean-now",
  "modal-backdrop","modal-title","modal-body","modal-footer","modal-close","low-disk-banner",
];
for (const id of requiredIds) makeEl(id);

const docListeners = new Map();
const document = {{
  documentElement: makeEl("html"),
  getElementById(id) {{ return elementMap.get(id) || null; }},
  createElement(tag) {{ return makeEl("", tag); }},
  querySelector(sel) {{
    if (sel.includes("delete-mode")) return {{ value: "recycle", checked: true }};
    return null;
  }},
  querySelectorAll() {{ return []; }},
  addEventListener(evt, fn) {{ docListeners.set(evt, fn); }},
}};

const apiCalls = [];
const sandbox = {{
  window: null,
  document,
  console,
  setTimeout,
  clearTimeout,
  setInterval: () => 1,
  clearInterval: () => {{}},
  addEventListener: () => {{}},
  navigator: {{ language: "en-US" }},
}};
sandbox.window = sandbox;
sandbox.window.addEventListener = () => {{}};
sandbox.window.pywebview = {{
  api: new Proxy({{}}, {{
    get(_t, prop) {{
      return async (...args) => {{
        apiCalls.push([String(prop), args]);
        if (prop === "get_app_info") {{
          return {{
            version: "0.3.0", os: "Windows", is_admin: true, theme: "dark", language: "es",
            auto_check_updates: false, exclusions: [], custom_presets: [], history_count: 0,
            drives: [{{ path: "C:\\\\", name: "C:", fstype: "NTFS", total_human: "500 GB", free_human: "50 GB", used_percent: 90 }}],
            low_disk_alerts: {{ has_alerts: true, threshold_free_pct: 15, alerts: [{{ drive: "C:\\\\", free_human: "50 GB", free_pct: 10, severity: "warning" }}] }},
          }};
        }}
        if (prop === "scan_smart_presets") {{
          return {{ items: [], total_human: "0 B", recommended_human: "0 B", count: 0 }};
        }}
        if (prop === "get_reminder_status") {{
          return {{ enabled: false, frequency: "weekly", threshold_pct: 15, task: {{ installed: false }} }};
        }}
        return {{ ok: true, alerts: {{ has_alerts: false, alerts: [] }} }};
      }};
    }},
  }}),
}};

vm.createContext(sandbox);
vm.runInContext(i18nSrc, sandbox);
vm.runInContext(appSrc, sandbox);

// Verify all data-i18n keys in index.html exist across every supported language
const i18n = sandbox.window.DriveSweepI18n;
for (const lang of ["en", "es", "fr", "de", "pt"]) {{
  const dict = i18n.STRINGS[lang];
  assert(dict, "Missing language pack: " + lang);
  for (const k of htmlKeys) {{
    assert(typeof dict[k] === "string" && dict[k].length > 0, `Missing ${{lang}}.${{k}}`);
  }}
  assert.strictEqual(i18n.setLanguage(lang), lang);
}}

(async () => {{
  await new Promise((r) => setTimeout(r, 40));
  assert(apiCalls.some((c) => c[0] === "get_app_info"), "initApp did not call get_app_info");
  assert(apiCalls.some((c) => c[0] === "scan_smart_presets"), "initApp did not call scan_smart_presets");
  sandbox.switchTab("explorer");
  sandbox.switchExplorerSubView("duplicates");
  await sandbox.openUpdatesPrivacyModal(false);
  assert(elementMap.get("modal-title").textContent.length > 0);
  console.log("UI_HARNESS_OK");
}})().catch((e) => {{
  console.error(e);
  process.exit(1);
}});
""",
        encoding="utf-8",
    )

    proc = subprocess.run([node_exe, str(runner)], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, f"Node UI harness failed:\n{proc.stdout}\n{proc.stderr}"
    assert "UI_HARNESS_OK" in proc.stdout
