const GROUP_COLORS = {
  "Windows & Temp": "#10b981",
  "Web Browsers": "#f59e0b",
  "Desktop Apps": "#ec4899",
  "AI & Coding Tools": "#8b5cf6",
  "Dev Editors & Packages": "#3b82f6",
  "Other App Caches": "#06b6d4",
};

const ICON_FOLDER = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
const ICON_FILE = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;
const ICON_CHEVRON = `<svg class="group-chevron" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="6 9 12 15 18 9"/></svg>`;
const ICON_SUN = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`;
const ICON_MOON = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;

const state = {
  theme: "dark",
  version: "0.2.0",
  dataDir: "",
  installKind: "source",
  autoCheckUpdates: true,
  latestUpdateInfo: null,
  drives: [],
  smartItems: [],
  exclusions: [],
  collapsedGroups: new Set(),
  isAdmin: false,
  osName: "Windows",
  selectedMap: new Map(),
  activeDriveRoot: null,
  scanTimer: null,
  browseState: { path: null, sort: "size", query: "", offset: 0, limit: 250 },
  allFilesState: { query: "", ext: "", minMb: 0, minAgeDays: 0, sort: "size", offset: 0, limit: 200 },
  devBloatMinAgeDays: 0,
};

function api() {
  return window.pywebview.api;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text ?? "";
  return div.innerHTML;
}

function formatBytes(bytes) {
  let size = Math.max(0, Number(bytes || 0));
  const units = ["B", "KB", "MB", "GB", "TB"];
  for (let i = 0; i < units.length; i++) {
    if (size < 1024 || i === units.length - 1) {
      return i === 0 ? `${Math.round(size)} B` : `${size.toFixed(2)} ${units[i]}`;
    }
    size /= 1024;
  }
  return "0 B";
}

function formatModified(mtimeStr, ageDays) {
  if (!mtimeStr) return "-";
  if (ageDays >= 365) {
    const yrs = (ageDays / 365).toFixed(1);
    return `${mtimeStr} (${yrs}y)`;
  }
  return `${mtimeStr} (${ageDays}d)`;
}

function applyTheme(theme) {
  state.theme = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", state.theme);
  document.getElementById("theme-icon").innerHTML = state.theme === "dark" ? ICON_SUN : ICON_MOON;
}

function normPathKey(path) {
  return String(path || "").replace(/[\\/]+$/, "").toLowerCase();
}

function isPathExcludedLocal(path) {
  const target = normPathKey(path);
  return state.exclusions.some((ex) => {
    const exNorm = normPathKey(ex);
    return target === exNorm || target.startsWith(exNorm + "\\") || target.startsWith(exNorm + "/");
  });
}

function getDeleteMode() {
  const checked = document.querySelector('input[name="delete-mode"]:checked');
  return checked ? checked.value : "recycle";
}

function setDeleteMode(mode) {
  const el = document.querySelector(`input[name="delete-mode"][value="${mode}"]`);
  if (el) el.checked = true;
}

function selectionKey(path, contentsOnly = false) {
  return `${contentsOnly ? "C:" : "F:"}${path.toLowerCase()}`;
}

function renderRiskBadge(riskLevel, riskReason) {
  const titleAttr = riskReason ? `title="${escapeHtml(riskReason)}"` : "";
  if (riskLevel === "critical") {
    return `<span class="badge badge-danger" ${titleAttr}>Critical</span>`;
  }
  if (riskLevel === "caution") {
    return `<span class="badge badge-warn" ${titleAttr}>Caution</span>`;
  }
  return `<span class="badge badge-good" ${titleAttr}>Safe</span>`;
}

function buildSvgDonut(segments, centerTop, centerBottom) {
  const total = segments.reduce((acc, s) => acc + Number(s.value || 0), 0);
  if (total <= 0) {
    return `<div class="muted small-text">No data to chart yet.</div>`;
  }

  const r = 46;
  const c = 2 * Math.PI * r;
  let offset = 0;

  const circles = segments
    .filter((s) => s.value > 0)
    .map((s) => {
      const frac = s.value / total;
      const dash = frac * c;
      const seg = `<circle cx="63" cy="63" r="${r}" fill="none" stroke="${s.color}" stroke-width="14" stroke-dasharray="${dash} ${c - dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 63 63)" />`;
      offset += dash;
      return seg;
    })
    .join("");

  const listRows = segments
    .slice(0, 6)
    .map(
      (s) => `
      <div class="donut-list-row">
        <span class="donut-list-name">
          <span class="legend-dot" style="background:${s.color};"></span>
          <span>${escapeHtml(s.label)}</span>
        </span>
        <strong>${escapeHtml(s.valueLabel)}</strong>
      </div>`
    )
    .join("");

  return `
    <svg class="donut-svg" viewBox="0 0 126 126">
      <circle cx="63" cy="63" r="${r}" fill="none" stroke="var(--track-bg)" stroke-width="14" />
      ${circles}
      <text x="63" y="60" text-anchor="middle" fill="var(--text)" font-size="13" font-weight="800">${escapeHtml(centerTop)}</text>
      <text x="63" y="75" text-anchor="middle" fill="var(--muted)" font-size="10">${escapeHtml(centerBottom)}</text>
    </svg>
    <div class="donut-list">${listRows}</div>
  `;
}

function getEffectiveSelectedItems() {
  const all = Array.from(state.selectedMap.values());
  const sorted = [...all].sort((a, b) => a.path.length - b.path.length);
  const kept = [];
  let nestedCount = 0;

  for (const item of sorted) {
    const itemNorm = normPathKey(item.path);
    const covered = kept.some((parent) => {
      const pNorm = normPathKey(parent.path);
      return (
        itemNorm === pNorm ||
        itemNorm.startsWith(pNorm + "\\") ||
        itemNorm.startsWith(pNorm + "/")
      );
    });
    if (covered) {
      nestedCount += 1;
    } else {
      kept.push(item);
    }
  }
  return { items: kept, nestedCount };
}

function updateSelectionBar() {
  const { items, nestedCount } = getEffectiveSelectedItems();
  const count = items.length;
  const totalBytes = items.reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
  const sizeStr = formatBytes(totalBytes);

  document.getElementById("selected-count").textContent = `${count} item${count === 1 ? "" : "s"} selected`;
  document.getElementById("selected-size").textContent = sizeStr;

  const cleanBtn = document.getElementById("btn-clean-now");
  cleanBtn.textContent = count > 0 ? `Clean ${sizeStr}` : "Clean Selected";
  cleanBtn.disabled = count === 0;

  const dedupNote = document.getElementById("dedup-note");
  if (nestedCount > 0) {
    dedupNote.textContent = `${nestedCount} nested child item${nestedCount === 1 ? "" : "s"} covered by parent`;
    dedupNote.classList.remove("hidden");
  } else {
    dedupNote.classList.add("hidden");
  }

  document.getElementById("btn-review-queue").disabled = count === 0;
}

function setItemSelected(item, selected) {
  const key = selectionKey(item.path, !!item.contents_only);
  if (selected) {
    state.selectedMap.set(key, { ...item, key });
  } else {
    state.selectedMap.delete(key);
  }
  updateSelectionBar();
}

function isItemSelected(path, contentsOnly = false) {
  return state.selectedMap.has(selectionKey(path, !!contentsOnly));
}

function switchTab(tabName) {
  document.querySelectorAll(".nav-item[data-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === `tab-${tabName}`);
  });

  const titleEl = document.getElementById("view-title");
  const subEl = document.getElementById("view-subtitle");
  const toolbarEl = document.getElementById("header-toolbar");

  if (tabName === "smart") {
    titleEl.textContent = "Quick Safe Cleanup";
    subEl.textContent = "Clean temporary files, browser caches, and leftover installers without touching your personal folders.";
    toolbarEl.classList.remove("hidden");
  } else {
    titleEl.textContent = "Drive Scanner";
    subEl.textContent = "Scan any drive or folder to see what takes up space, check safety levels, and choose what to keep or delete.";
    toolbarEl.classList.add("hidden");
  }
}

function switchExplorerSubView(subName) {
  document.querySelectorAll(".subtab-btn").forEach((b) => b.classList.toggle("active", b.dataset.subview === subName));
  document.querySelectorAll(".subview").forEach((v) => v.classList.toggle("active", v.id === `subview-${subName}`));
}

function renderDrives(drives, pulse = false) {
  state.drives = drives || [];
  if (state.activeDriveRoot) {
    const stillPresent = state.drives.some((d) => d.path === state.activeDriveRoot);
    if (!stillPresent) {
      state.activeDriveRoot = null;
    }
  }
  const sideEl = document.getElementById("sidebar-drives");
  const cardsEl = document.getElementById("drive-cards");

  const gaugeClass = (pct) => (pct >= 90 ? "danger" : pct >= 75 ? "warn" : "");
  const pulseCls = pulse ? " drive-refreshed" : "";

  sideEl.innerHTML = state.drives
    .map(
      (d) => `
      <button class="side-drive ${state.activeDriveRoot === d.path ? "active" : ""}${pulseCls}" data-drive="${escapeHtml(d.path)}">
        <div class="side-drive-top">
          <span>Drive ${escapeHtml(d.name)}</span>
          <span class="muted">${d.used_percent}%</span>
        </div>
        <div class="side-drive-sub">${escapeHtml(d.free_human)} free of ${escapeHtml(d.total_human)}</div>
        <div class="gauge-track">
          <div class="gauge-fill ${gaugeClass(d.used_percent)}" style="width: ${Math.min(100, d.used_percent)}%"></div>
        </div>
      </button>`
    )
    .join("");

  cardsEl.innerHTML = state.drives
    .map(
      (d) => `
      <button class="drive-card ${state.activeDriveRoot === d.path ? "active" : ""}${pulseCls}" data-drive="${escapeHtml(d.path)}">
        <div class="drive-card-top">
          <span>Drive ${escapeHtml(d.name)}</span>
          <span class="muted small-text">${escapeHtml(d.fstype)}</span>
        </div>
        <div class="drive-card-sub">${escapeHtml(d.free_human)} free of ${escapeHtml(d.total_human)} (${d.used_percent}% used)</div>
        <div class="gauge-track">
          <div class="gauge-fill ${gaugeClass(d.used_percent)}" style="width: ${Math.min(100, d.used_percent)}%"></div>
        </div>
      </button>`
    )
    .join("");

  sideEl.querySelectorAll(".side-drive").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchTab("explorer");
      startDriveScan(btn.dataset.drive);
    });
  });

  cardsEl.querySelectorAll(".drive-card").forEach((btn) => {
    btn.addEventListener("click", () => startDriveScan(btn.dataset.drive));
  });
}

function updateHeaderCounts(exclusions, historyCount) {
  if (Array.isArray(exclusions)) {
    state.exclusions = exclusions;
    document.getElementById("exclusions-count").textContent = String(exclusions.length);
  }
  if (typeof historyCount === "number") {
    document.getElementById("history-count").textContent = String(historyCount);
  }
}

/* ==================== EXCLUSIONS & HISTORY MODALS ==================== */

async function toggleAlwaysKeep(path) {
  if (isPathExcludedLocal(path)) {
    const updated = await api().remove_exclusion(path);
    updateHeaderCounts(updated);
  } else {
    const updated = await api().add_exclusion(path);
    updateHeaderCounts(updated);
    for (const [k, v] of state.selectedMap.entries()) {
      if (normPathKey(v.path) === normPathKey(path)) {
        state.selectedMap.delete(k);
      }
    }
    updateSelectionBar();
  }
  await loadSmartScan();
  if (state.browseState.path) {
    await Promise.all([loadAnalytics(), loadBrowseFolder(), loadAllFiles(), loadLargestFiles(), loadDevArtifacts()]);
  }
}

async function openExclusionsModal() {
  const list = await api().get_exclusions();
  updateHeaderCounts(list);
  const rows = list
    .map(
      (p) => `
      <div class="review-row">
        <div class="item-subpath" style="flex:1;">${escapeHtml(p)}</div>
        <button class="btn btn-soft btn-sm btn-remove-ex" data-path="${escapeHtml(p)}">Remove</button>
      </div>`
    )
    .join("");

  showModal(
    `Always Keep List (${list.length})`,
    `<p class="muted small-text">Paths listed here stay unchecked during Smart Scans and are marked "Always Keep" across DriveSweep.</p>
     <div class="review-list">${rows || "<p class='muted'>No excluded paths yet. Click 'Keep' on any folder or cache to protect it.</p>"}</div>`,
    [{ text: "Close", cls: "btn-primary", onClick: closeModal }]
  );

  document.querySelectorAll(".btn-remove-ex").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const updated = await api().remove_exclusion(btn.dataset.path);
      updateHeaderCounts(updated);
      await loadSmartScan();
      openExclusionsModal();
    });
  });
}

async function openHistoryModal() {
  const entries = await api().get_history(50);
  updateHeaderCounts(undefined, entries.length);

  const rows = entries
    .map((h) => {
      const dateLabel = h.timestamp ? new Date(h.timestamp).toLocaleString() : "Unknown";
      return `
        <div class="review-row">
          <div style="flex:1;min-width:0;">
            <div>
              <strong>${escapeHtml(h.freed_human)}</strong> reclaimed
              <span class="badge ${h.mode === "permanent" ? "badge-danger" : "badge-good"}">${h.mode === "permanent" ? "Permanent" : "Recycle Bin"}</span>
            </div>
            <div class="muted small-text">${escapeHtml(dateLabel)} | ${h.deleted_count} cleaned${h.failed_count ? ` | ${h.failed_count} failed` : ""}</div>
          </div>
        </div>`;
    })
    .join("");

  showModal(
    `Cleanup Log (${entries.length})`,
    `<div class="review-list">${rows || "<p class='muted'>No cleanup runs recorded yet.</p>"}</div>`,
    [
      ...(entries.length
        ? [
            {
              text: "Clear Log",
              cls: "btn-soft",
              onClick: () => {
                showModal(
                  "Permission Required: Clear Cleanup Log",
                  `<div class="caution-box">This will permanently erase your local cleanup history log (${entries.length} entries).</div>`,
                  [
                    { text: "Cancel", cls: "btn-soft", onClick: openHistoryModal },
                    {
                      text: "Yes, Clear Log",
                      cls: "btn-danger",
                      onClick: async () => {
                        await api().clear_history();
                        updateHeaderCounts(undefined, 0);
                        openHistoryModal();
                      },
                    },
                  ]
                );
              },
            },
          ]
        : []),
      { text: "Close", cls: "btn-primary", onClick: closeModal },
    ]
  );
}

async function openUpdatesPrivacyModal(runCheckNow = false) {
  const renderBody = (statusHtml) => `
    <div class="summary-strip" style="margin-bottom:12px;">
      <div>
        <div style="font-weight:700;">100% Local Data &amp; Zero Telemetry</div>
        <div class="muted small-text" style="margin-top:2px;">
          All settings, exclusions, and cleanup history stay on this device at:
        </div>
        <div class="item-subpath" style="margin-top:4px;">${escapeHtml(state.dataDir)}</div>
      </div>
      <button id="btn-open-data-dir" class="btn btn-soft btn-sm">Open Folder</button>
    </div>

    <label class="review-row" style="cursor:pointer;margin-bottom:12px;">
      <div>
        <div style="font-weight:600;font-size:13px;">Check GitHub Releases on startup</div>
        <div class="muted small-text">Uses a read-only GET to public GitHub Releases. Never sends logs or device info.</div>
      </div>
      <label class="toggle-switch">
        <input id="chk-auto-updates" type="checkbox" ${state.autoCheckUpdates ? "checked" : ""} />
        <span class="toggle-slider"></span>
      </label>
    </label>

    <div id="update-status-panel" class="summary-strip">${statusHtml}</div>
  `;

  const formatUpdatePanel = (u) => {
    if (!u) {
      return `<div><strong>Current Version:</strong> v${escapeHtml(state.version)}<div class="muted small-text">Click "Check for Updates" to check GitHub Releases.</div></div>`;
    }
    if (!u.ok) {
      return `<div><strong>Update check failed</strong><div class="muted small-text">${escapeHtml(u.error || "Network error")}</div></div>`;
    }
    if (!u.update_available) {
      return `<div><strong>Up to date (v${escapeHtml(state.version)})</strong><div class="muted small-text">Latest release on GitHub is v${escapeHtml(u.latest_version)}.</div></div>`;
    }
    return `
      <div style="width:100%;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <div>
            <strong>Update Available: v${escapeHtml(u.latest_version)}</strong>
            <span class="badge badge-info">Installed: v${escapeHtml(state.version)}</span>
          </div>
          <span class="muted small-text">${escapeHtml(u.asset_name || "GitHub Release")}</span>
        </div>
        <div class="muted small-text" style="margin-top:6px;">
          Downloads directly from GitHub Releases and verifies SHA-256 against SHA256SUMS.txt before asking Windows to install.
        </div>
      </div>`;
  };

  const buildFooterButtons = () => {
    const btns = [
      {
        text: "Check for Updates",
        cls: "btn-soft",
        onClick: async () => {
          const panel = document.getElementById("update-status-panel");
          if (panel) panel.innerHTML = `<div class="muted">Checking GitHub Releases...</div>`;
          const res = await api().check_for_updates();
          state.latestUpdateInfo = res;
          updateHeaderUpdateBadge(res);
          openUpdatesPrivacyModal(false);
        },
      },
    ];
    const u = state.latestUpdateInfo;
    if (u && u.ok && u.update_available && u.asset_url && u.sha256_url) {
      btns.push({
        text: `Verify SHA-256 & Install v${u.latest_version}`,
        cls: "btn-cta",
        onClick: async () => {
          const panel = document.getElementById("update-status-panel");
          if (panel) panel.innerHTML = `<div class="muted">Downloading and verifying SHA-256 checksum...</div>`;
          const res = await api().download_and_apply_update(u.asset_url, u.asset_name, u.sha256_url);
          if (!res.ok) {
            if (panel) panel.innerHTML = `<div class="warning-box" style="margin:0;width:100%;">${escapeHtml(res.error || "Update failed.")}</div>`;
            return;
          }
          if (panel) panel.innerHTML = `<div class="muted">Verified SHA-256 (${escapeHtml(res.sha256.slice(0, 12))}...). Launching installer...</div>`;
        },
      });
    }
    btns.push({ text: "Close", cls: "btn-primary", onClick: closeModal });
    return btns;
  };

  showModal(
    "Updates & Local Privacy",
    renderBody(formatUpdatePanel(state.latestUpdateInfo)),
    buildFooterButtons()
  );

  document.getElementById("btn-open-data-dir")?.addEventListener("click", () => api().open_data_dir());
  document.getElementById("chk-auto-updates")?.addEventListener("change", async (e) => {
    state.autoCheckUpdates = !!e.target.checked;
    await api().set_auto_check_updates(state.autoCheckUpdates);
  });

  if (runCheckNow) {
    const panel = document.getElementById("update-status-panel");
    if (panel) panel.innerHTML = `<div class="muted">Checking GitHub Releases...</div>`;
    const res = await api().check_for_updates();
    state.latestUpdateInfo = res;
    updateHeaderUpdateBadge(res);
    openUpdatesPrivacyModal(false);
  }
}

function updateHeaderUpdateBadge(u) {
  const chip = document.getElementById("app-version");
  const navBadge = document.getElementById("update-nav-badge");
  if (u && u.ok && u.update_available) {
    chip.classList.add("update-ready");
    chip.title = `Update available: v${u.latest_version}. Click to view.`;
    navBadge?.classList.remove("hidden");
  } else {
    chip.classList.remove("update-ready");
    chip.title = "View updates and local privacy settings";
    navBadge?.classList.add("hidden");
  }
}

/* ==================== TAB 1: SMART CACHE SCAN ==================== */

async function loadSmartScan() {
  const rescanBtn = document.getElementById("btn-smart-scan");
  if (rescanBtn) {
    rescanBtn.disabled = true;
    rescanBtn.textContent = "Scanning...";
  }
  document.getElementById("smart-count-sub").textContent = "Scanning locations...";
  const groupsEl = document.getElementById("smart-groups");
  groupsEl.innerHTML = "";

  try {
    const res = await api().scan_smart_presets();
    state.smartItems = res.items || [];

    for (const [k, v] of state.selectedMap.entries()) {
      if (v.source === "smart") state.selectedMap.delete(k);
    }
    for (const item of state.smartItems) {
      if (item.default_checked && !item.excluded) {
        setItemSelected({ ...item, source: "smart" }, true);
      }
    }

    document.getElementById("smart-total-metric").textContent = res.total_human;
    document.getElementById("smart-rec-metric").textContent = res.recommended_human;
    document.getElementById("smart-count-sub").textContent = `${res.count} cleanup items found`;
    document.getElementById("nav-smart-badge").textContent = res.total_human;

    renderSmartBreakdown(res.total_human);
    renderSmartGroups();
  } catch (err) {
    document.getElementById("smart-count-sub").textContent = `Scan failed: ${String(err)}`;
  } finally {
    if (rescanBtn) {
      rescanBtn.disabled = false;
      rescanBtn.textContent = "Re-scan";
    }
  }
}

function renderSmartBreakdown(totalHuman) {
  const barEl = document.getElementById("smart-breakdown-bar");
  const legendEl = document.getElementById("smart-breakdown-legend");
  const donutEl = document.getElementById("smart-donut-wrap");

  const totals = new Map();
  let grandTotal = 0;
  for (const item of state.smartItems) {
    const sz = Number(item.size_bytes || 0);
    if (sz <= 0) continue;
    totals.set(item.group, (totals.get(item.group) || 0) + sz);
    grandTotal += sz;
  }

  if (grandTotal <= 0) {
    barEl.innerHTML = "";
    legendEl.innerHTML = `<span class="muted">All detected caches are currently empty.</span>`;
    donutEl.innerHTML = `<span class="muted small-text">No caches to visualize.</span>`;
    return;
  }

  const sorted = Array.from(totals.entries()).sort((a, b) => b[1] - a[1]);
  barEl.innerHTML = sorted
    .map(([grp, bytes]) => {
      const pct = Math.max(1.5, (bytes / grandTotal) * 100);
      const color = GROUP_COLORS[grp] || "#64748b";
      return `<div class="breakdown-seg" style="width:${pct}%;background:${color};" title="${escapeHtml(grp)}: ${formatBytes(bytes)}"></div>`;
    })
    .join("");

  legendEl.innerHTML = sorted
    .map(([grp, bytes]) => {
      const color = GROUP_COLORS[grp] || "#64748b";
      return `
        <div class="legend-item">
          <span class="legend-dot" style="background:${color};"></span>
          <span>${escapeHtml(grp)}</span>
          <strong>${formatBytes(bytes)}</strong>
        </div>`;
    })
    .join("");

  const donutSegs = sorted.map(([grp, bytes]) => ({
    label: grp,
    value: bytes,
    valueLabel: formatBytes(bytes),
    color: GROUP_COLORS[grp] || "#64748b",
  }));
  donutEl.innerHTML = buildSvgDonut(donutSegs, totalHuman || formatBytes(grandTotal), "Total Found");
}

function renderSmartGroups() {
  const filter = (document.getElementById("smart-filter").value || "").trim().toLowerCase();
  const container = document.getElementById("smart-groups");

  const filtered = state.smartItems.filter(
    (item) =>
      !filter ||
      item.label.toLowerCase().includes(filter) ||
      item.path.toLowerCase().includes(filter) ||
      item.group.toLowerCase().includes(filter)
  );

  if (filtered.length === 0) {
    container.innerHTML = `<div class="summary-strip">No matching caches found.</div>`;
    return;
  }

  const maxItemBytes = Math.max(1, ...filtered.map((it) => Number(it.size_bytes || 0)));
  const groups = new Map();
  for (const item of filtered) {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  }

  container.innerHTML = "";
  for (const [groupName, items] of groups.entries()) {
    const groupBytes = items.reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
    const color = GROUP_COLORS[groupName] || "#64748b";
    const card = document.createElement("div");
    card.className = `group-card ${state.collapsedGroups.has(groupName) ? "collapsed" : ""}`;

    const header = document.createElement("div");
    header.className = "group-header";
    header.innerHTML = `
      <div class="group-title-wrap">
        ${ICON_CHEVRON}
        <span class="legend-dot" style="background:${color};"></span>
        <span>${escapeHtml(groupName)}</span>
        <span class="ver-chip">${items.length}</span>
      </div>
      <span class="size-pill">${formatBytes(groupBytes)}</span>
    `;
    header.addEventListener("click", () => {
      if (state.collapsedGroups.has(groupName)) {
        state.collapsedGroups.delete(groupName);
      } else {
        state.collapsedGroups.add(groupName);
      }
      card.classList.toggle("collapsed");
    });

    const body = document.createElement("div");
    body.className = "group-body";

    for (const item of items) {
      const excluded = !!item.excluded || isPathExcludedLocal(item.path);
      const checked = !excluded && isItemSelected(item.path, item.contents_only);
      const pct = Math.min(100, (Number(item.size_bytes || 0) / maxItemBytes) * 100);

      const row = document.createElement("div");
      row.className = "preset-row";
      row.innerHTML = `
        <div class="row-size-bg" style="width:${pct}%;"></div>
        <label class="toggle-switch" title="Toggle clean or keep">
          <input type="checkbox" ${checked ? "checked" : ""} ${excluded ? "disabled" : ""} />
          <span class="toggle-slider"></span>
        </label>
        <div class="preset-main">
          <div class="preset-title-line">
            <span class="preset-title">${escapeHtml(item.label)}</span>
            ${renderRiskBadge(item.risk_level || "safe", item.risk_reason || item.safety_note)}
            ${item.running_app ? `<span class="badge badge-warn">${escapeHtml(item.running_app)} running</span>` : ""}
            ${excluded ? `<span class="badge badge-info">Always Keep</span>` : ""}
          </div>
          <div class="preset-path" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</div>
          <div class="preset-note">${escapeHtml(item.safety_note)}</div>
        </div>
        <div class="preset-right">
          <div class="row-hover-actions">
            ${item.is_docker_prune ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>`}
            ${item.is_docker_prune ? "" : `<button class="btn btn-soft btn-xs btn-open">Open Folder</button>`}
          </div>
          <span class="muted small-text">${item.file_count ? `${item.file_count.toLocaleString()} files` : ""}</span>
          <span class="size-pill">${escapeHtml(item.size_human)}</span>
        </div>
      `;

      const cb = row.querySelector('input[type="checkbox"]');
      if (!excluded) {
        cb.addEventListener("change", () => {
          setItemSelected({ ...item, source: "smart" }, cb.checked);
        });
      }

      const keepBtn = row.querySelector(".btn-keep-toggle");
      if (keepBtn) {
        keepBtn.addEventListener("click", () => toggleAlwaysKeep(item.path));
      }

      const openBtn = row.querySelector(".btn-open");
      if (openBtn) {
        openBtn.addEventListener("click", () => api().open_in_explorer(item.path));
      }

      body.appendChild(row);
    }
    card.appendChild(header);
    card.appendChild(body);
    container.appendChild(card);
  }
}

/* ==================== TAB 2: FULL-DRIVE EXPLORER ==================== */

async function startDriveScan(rootPath, force = false) {
  if (!rootPath) return;
  state.activeDriveRoot = rootPath;
  renderDrives(state.drives);

  document.getElementById("explorer-empty").classList.add("hidden");
  document.getElementById("scan-progress").classList.remove("hidden");
  document.getElementById("btn-cancel-scan").classList.remove("hidden");
  document.getElementById("explorer-workspace").classList.add("hidden");

  await api().start_drive_scan(rootPath, !!force);
  if (state.scanTimer) clearInterval(state.scanTimer);
  state.scanTimer = setInterval(pollScanStatus, 250);
  await pollScanStatus();
}

async function pollScanStatus() {
  const st = await api().get_scan_status();
  const label = document.getElementById("scan-status-label");
  const stats = document.getElementById("scan-stats-text");
  const curPath = document.getElementById("scan-current-path");

  stats.textContent = `${st.files_scanned.toLocaleString()} files | ${st.dirs_scanned.toLocaleString()} folders | ${st.bytes_human} (${st.elapsed_sec}s)`;
  curPath.textContent = st.current_path || "";

  if (st.status === "scanning") {
    label.textContent = `Scanning ${st.root_path}...`;
    return;
  }

  clearInterval(state.scanTimer);
  state.scanTimer = null;
  document.getElementById("btn-cancel-scan").classList.add("hidden");

  if (st.status === "error") {
    label.textContent = `Scan error: ${st.error}`;
    return;
  }

  document.getElementById("scan-progress").classList.add("hidden");
  document.getElementById("explorer-workspace").classList.remove("hidden");
  const prefix = st.cached ? "Cached | " : "";
  document.getElementById("explorer-summary-pill").textContent =
    `${prefix}Indexed ${st.files_scanned.toLocaleString()} files (${st.bytes_human}) in ${st.elapsed_sec}s` +
    (st.skipped_count ? ` | ${st.skipped_count} locked entries skipped` : "");
  document.getElementById("btn-explorer-rescan").classList.remove("hidden");

  state.browseState.path = st.root_path;
  state.browseState.offset = 0;
  await Promise.all([loadAnalytics(), loadBrowseFolder(), loadAllFiles(), loadLargestFiles(), loadDevArtifacts()]);
}

async function loadAnalytics() {
  const data = await api().get_drive_analytics(state.browseState.path);
  const risk = data.risk_summary || {};
  const crit = risk.critical || { size_human: "0 B", file_count: 0, percent: 0 };
  const caut = risk.caution || { size_human: "0 B", file_count: 0, percent: 0 };
  const safe = risk.safe || { size_human: "0 B", file_count: 0, percent: 0 };

  document.getElementById("risk-cards-row").innerHTML = `
    <div class="risk-card">
      <div class="risk-card-title">
        <span class="risk-card-label"><span class="risk-dot risk-dot-critical"></span>System Files (Locked)</span>
        <span class="muted">${crit.percent}%</span>
      </div>
      <div class="risk-card-val">${escapeHtml(crit.size_human)}</div>
      <div class="risk-card-desc">${crit.file_count.toLocaleString()} Windows and program files locked so they cannot be deleted by mistake.</div>
    </div>
    <div class="risk-card">
      <div class="risk-card-title">
        <span class="risk-card-label"><span class="risk-dot risk-dot-caution"></span>Important Files (Review First)</span>
        <span class="muted">${caut.percent}%</span>
      </div>
      <div class="risk-card-val">${escapeHtml(caut.size_human)}</div>
      <div class="risk-card-desc">${caut.file_count.toLocaleString()} personal, database, app, or project files. DriveSweep asks before cleaning.</div>
    </div>
    <div class="risk-card">
      <div class="risk-card-title">
        <span class="risk-card-label"><span class="risk-dot risk-dot-safe"></span>Standard Files</span>
        <span class="muted">${safe.percent}%</span>
      </div>
      <div class="risk-card-val">${escapeHtml(safe.size_human)}</div>
      <div class="risk-card-desc">${safe.file_count.toLocaleString()} regular files and temporary caches you can safely review or remove.</div>
    </div>
  `;

  // Treemap tiles
  const treemapEl = document.getElementById("treemap-grid");
  const topFolders = data.top_folders || [];
  if (topFolders.length === 0) {
    treemapEl.innerHTML = `<div class="muted small-text">No subfolders in this location.</div>`;
  } else {
    const maxPct = Math.max(1, ...topFolders.map((f) => f.percent || 0));
    treemapEl.innerHTML = topFolders
      .map(
        (f) => `
        <button class="treemap-tile risk-${escapeHtml(f.risk_level)}" data-path="${escapeHtml(f.path)}">
          <div class="treemap-name">${escapeHtml(f.name)}</div>
          <div class="treemap-meta">
            <strong>${escapeHtml(f.size_human)}</strong>
            <span>${f.percent}%</span>
          </div>
          <div class="treemap-tile-fill" style="width:${Math.min(100, (f.percent / maxPct) * 100)}%;"></div>
        </button>`
      )
      .join("");
    treemapEl.querySelectorAll(".treemap-tile").forEach((tile) => {
      tile.addEventListener("click", () => {
        state.browseState.path = tile.dataset.path;
        state.browseState.offset = 0;
        switchExplorerSubView("browse");
        loadBrowseFolder();
      });
    });
  }

  // Category Donut Chart
  const catSegs = (data.by_category || []).map((c) => ({
    label: `${c.name} (${c.percent}%)`,
    value: c.size_bytes,
    valueLabel: c.size_human,
    color: c.color,
  }));
  document.getElementById("category-chart-wrap").innerHTML = buildSvgDonut(
    catSegs,
    data.total_human || "0 B",
    "Total"
  );

  // Age Bar Chart
  const ageList = data.by_age || [];
  const maxAgeBytes = Math.max(1, ...ageList.map((a) => Number(a.size_bytes || 0)));
  document.getElementById("age-chart-wrap").innerHTML = ageList
    .map((a) => {
      const w = Math.min(100, (Number(a.size_bytes || 0) / maxAgeBytes) * 100);
      return `
        <div class="bar-row">
          <div class="bar-row-top">
            <span><strong>${escapeHtml(a.name)}</strong> <span class="muted">(${a.file_count.toLocaleString()} files)</span></span>
            <span><strong>${escapeHtml(a.size_human)}</strong> <span class="muted">(${a.percent}%)</span></span>
          </div>
          <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${a.color};"></div></div>
        </div>`;
    })
    .join("");

  // Simple Summary Table
  const tableEl = document.getElementById("top-folders-table-wrap");
  if (topFolders.length === 0) {
    tableEl.innerHTML = `<div class="muted small-text">No folders to summarize.</div>`;
  } else {
    tableEl.innerHTML = `
      <table class="mini-table">
        <thead>
          <tr><th>Folder</th><th>Safety</th><th>Files</th><th>Size</th></tr>
        </thead>
        <tbody>
          ${topFolders
            .slice(0, 7)
            .map(
              (f) => `
              <tr class="clickable-row" data-path="${escapeHtml(f.path)}">
                <td><strong>${escapeHtml(f.name)}</strong></td>
                <td>${renderRiskBadge(f.risk_level, "")}</td>
                <td>${f.file_count.toLocaleString()}</td>
                <td><strong>${escapeHtml(f.size_human)}</strong> (${f.percent}%)</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    tableEl.querySelectorAll("tr.clickable-row").forEach((row) => {
      row.addEventListener("click", () => {
        state.browseState.path = row.dataset.path;
        state.browseState.offset = 0;
        switchExplorerSubView("browse");
        loadBrowseFolder();
      });
    });
  }
}

async function loadBrowseFolder() {
  const b = state.browseState;
  const res = await api().browse_folder(b.path, b.sort, b.query, b.offset, b.limit);
  if (res.error) return;

  const crumbsEl = document.getElementById("breadcrumbs");
  crumbsEl.innerHTML = (res.breadcrumbs || [])
    .map((c) => `<button class="crumb-btn" data-path="${escapeHtml(c.path)}">${escapeHtml(c.name)}</button>`)
    .join(`<span class="muted">/</span>`);
  crumbsEl.querySelectorAll(".crumb-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.browseState.path = btn.dataset.path;
      state.browseState.offset = 0;
      loadBrowseFolder();
    });
  });

  const items = res.items || [];
  const maxBytes = Math.max(1, ...items.map((it) => Number(it.size_bytes || 0)));
  const tbody = document.getElementById("browse-tbody");
  tbody.innerHTML = "";

  for (const item of items) {
    const tr = document.createElement("tr");
    const excluded = isPathExcludedLocal(item.path);
    const disabled = item.is_protected || excluded;
    const checked = !disabled && isItemSelected(item.path, false);
    const pct = Math.min(100, (Number(item.size_bytes || 0) / maxBytes) * 100);

    const extraBadges = [
      excluded ? `<span class="badge badge-info">Always Keep</span>` : "",
      item.is_dev_bloat ? `<span class="badge badge-info">Project Cache</span>` : "",
    ]
      .filter(Boolean)
      .join(" ");

    tr.innerHTML = `
      <td class="col-check">
        <input class="chk-box" type="checkbox" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
      </td>
      <td>
        <div class="item-cell-wrap">
          <div class="item-name-line">
            ${item.kind === "dir" ? ICON_FOLDER : ICON_FILE}
            ${
              item.kind === "dir"
                ? `<button class="folder-link">${escapeHtml(item.name)}</button>`
                : `<span>${escapeHtml(item.name)}</span>`
            }
            ${extraBadges}
          </div>
          <div class="inline-bar-track"><div class="inline-bar-fill" style="width:${pct}%"></div></div>
        </div>
      </td>
      <td class="col-risk">${renderRiskBadge(item.risk_level || (item.is_protected ? "critical" : "safe"), item.risk_reason)}</td>
      <td class="col-date">${escapeHtml(formatModified(item.mtime_str, item.age_days))}</td>
      <td class="col-count">${item.kind === "dir" ? item.file_count.toLocaleString() : "1"}</td>
      <td class="col-size">${escapeHtml(item.size_human)}</td>
      <td class="col-actions">
        <div class="row-actions">
          ${item.is_protected ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>`}
          <button class="btn btn-soft btn-xs btn-open">Open Folder</button>
        </div>
      </td>
    `;

    const cb = tr.querySelector('input[type="checkbox"]');
    if (!disabled) {
      cb.addEventListener("change", () => {
        setItemSelected(
          {
            path: item.path,
            label: item.name,
            size_bytes: item.size_bytes,
            size_human: item.size_human,
            contents_only: false,
            risk_level: item.risk_level || "safe",
            risk_reason: item.risk_reason || "",
            source: "explorer",
          },
          cb.checked
        );
      });
    }

    const folderBtn = tr.querySelector(".folder-link");
    if (folderBtn) {
      folderBtn.addEventListener("click", () => {
        state.browseState.path = item.path;
        state.browseState.offset = 0;
        loadBrowseFolder();
      });
    }

    const keepBtn = tr.querySelector(".btn-keep-toggle");
    if (keepBtn) {
      keepBtn.addEventListener("click", () => toggleAlwaysKeep(item.path));
    }

    tr.querySelector(".btn-open").addEventListener("click", () => api().open_in_explorer(item.path));
    tbody.appendChild(tr);
  }

  renderPager("browse-pager", res.total_items, b.offset, b.limit, (newOffset) => {
    state.browseState.offset = newOffset;
    loadBrowseFolder();
  });
}

async function loadAllFiles() {
  const a = state.allFilesState;
  const res = await api().search_all_files(a.query, a.minMb, a.minAgeDays, a.ext, a.sort, a.offset, a.limit);
  document.getElementById("allfiles-meta").textContent =
    `${res.total_matches.toLocaleString()} files matched (${res.total_matched_human})`;

  renderFileRows(document.getElementById("allfiles-tbody"), res.items || []);
  renderPager("allfiles-pager", res.total_matches, a.offset, a.limit, (newOffset) => {
    state.allFilesState.offset = newOffset;
    loadAllFiles();
  });
}

async function loadLargestFiles() {
  const items = await api().get_largest_files(200);
  renderFileRows(document.getElementById("largest-tbody"), items || []);
}

async function loadDevArtifacts() {
  const items = await api().get_dev_artifacts(200, state.devBloatMinAgeDays);
  const totalBytes = items.reduce((acc, i) => acc + Number(i.size_bytes || 0), 0);
  document.getElementById("devbloat-meta").textContent =
    `${items.length} project cache folder(s) | ${formatBytes(totalBytes)}`;

  const maxBytes = Math.max(1, ...items.map((it) => Number(it.size_bytes || 0)));
  const tbody = document.getElementById("devbloat-tbody");
  tbody.innerHTML = "";

  for (const item of items || []) {
    const tr = document.createElement("tr");
    const excluded = isPathExcludedLocal(item.path);
    const disabled = item.is_protected || excluded;
    const checked = !disabled && isItemSelected(item.path, false);
    const pct = Math.min(100, (Number(item.size_bytes || 0) / maxBytes) * 100);

    tr.innerHTML = `
      <td class="col-check">
        <input class="chk-box" type="checkbox" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
      </td>
      <td>
        <div class="item-name-line">
          ${ICON_FOLDER}
          <strong>${escapeHtml(item.name)}</strong>
          <span class="muted">in ${escapeHtml(item.parent_name)}</span>
          ${excluded ? `<span class="badge badge-info">Always Keep</span>` : ""}
        </div>
        <div class="item-subpath">${escapeHtml(item.path)}</div>
        <div class="inline-bar-track"><div class="inline-bar-fill" style="width:${pct}%"></div></div>
      </td>
      <td class="col-risk">${renderRiskBadge(item.risk_level || "safe", item.risk_reason)}</td>
      <td class="col-date">${escapeHtml(formatModified(item.mtime_str, item.age_days))}</td>
      <td class="col-count">${item.file_count.toLocaleString()}</td>
      <td class="col-size">${escapeHtml(item.size_human)}</td>
      <td class="col-actions">
        <div class="row-actions">
          <button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>
          <button class="btn btn-soft btn-xs btn-open">Open Folder</button>
        </div>
      </td>
    `;
    const cb = tr.querySelector('input[type="checkbox"]');
    if (!disabled) {
      cb.addEventListener("change", () => {
        setItemSelected(
          {
            path: item.path,
            label: `${item.parent_name}/${item.name}`,
            size_bytes: item.size_bytes,
            size_human: item.size_human,
            contents_only: false,
            risk_level: item.risk_level || "safe",
            risk_reason: item.risk_reason || "",
            source: "explorer",
          },
          cb.checked
        );
      });
    }
    tr.querySelector(".btn-keep-toggle").addEventListener("click", () => toggleAlwaysKeep(item.path));
    tr.querySelector(".btn-open").addEventListener("click", () => api().open_in_explorer(item.path));
    tbody.appendChild(tr);
  }
}

function renderFileRows(tbody, items) {
  tbody.innerHTML = "";
  const maxBytes = Math.max(1, ...items.map((it) => Number(it.size_bytes || 0)));

  for (const item of items) {
    const tr = document.createElement("tr");
    const excluded = isPathExcludedLocal(item.path);
    const disabled = item.is_protected || excluded;
    const checked = !disabled && isItemSelected(item.path, false);
    const pct = Math.min(100, (Number(item.size_bytes || 0) / maxBytes) * 100);

    tr.innerHTML = `
      <td class="col-check">
        <input class="chk-box" type="checkbox" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
      </td>
      <td>
        <div class="item-name-line">
          ${ICON_FILE}
          <strong>${escapeHtml(item.name)}</strong>
          ${excluded ? `<span class="badge badge-info">Always Keep</span>` : ""}
        </div>
        <div class="item-subpath">${escapeHtml(item.dir_path || item.path)}</div>
        <div class="inline-bar-track"><div class="inline-bar-fill" style="width:${pct}%"></div></div>
      </td>
      <td class="col-risk">${renderRiskBadge(item.risk_level || (item.is_protected ? "critical" : "safe"), item.risk_reason)}</td>
      <td class="col-date">${escapeHtml(formatModified(item.mtime_str, item.age_days))}</td>
      <td class="col-size">${escapeHtml(item.size_human)}</td>
      <td class="col-actions">
        <div class="row-actions">
          ${item.is_protected ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>`}
          <button class="btn btn-soft btn-xs btn-open">Open Folder</button>
        </div>
      </td>
    `;
    const cb = tr.querySelector('input[type="checkbox"]');
    if (!disabled) {
      cb.addEventListener("change", () => {
        setItemSelected(
          {
            path: item.path,
            label: item.name,
            size_bytes: item.size_bytes,
            size_human: item.size_human,
            contents_only: false,
            risk_level: item.risk_level || "safe",
            risk_reason: item.risk_reason || "",
            source: "explorer",
          },
          cb.checked
        );
      });
    }
    const keepBtn = tr.querySelector(".btn-keep-toggle");
    if (keepBtn) {
      keepBtn.addEventListener("click", () => toggleAlwaysKeep(item.path));
    }
    tr.querySelector(".btn-open").addEventListener("click", () => api().open_in_explorer(item.path));
    tbody.appendChild(tr);
  }
}

function renderPager(elId, total, offset, limit, onPage) {
  const el = document.getElementById(elId);
  if (total <= limit) {
    el.innerHTML = `<span>Showing ${total} item${total === 1 ? "" : "s"}</span><span></span>`;
    return;
  }
  const start = offset + 1;
  const end = Math.min(total, offset + limit);
  el.innerHTML = `
    <span>Showing ${start.toLocaleString()} to ${end.toLocaleString()} of ${total.toLocaleString()}</span>
    <div style="display:flex;gap:8px;">
      <button class="btn btn-soft btn-sm btn-prev" ${offset === 0 ? "disabled" : ""}>Prev</button>
      <button class="btn btn-soft btn-sm btn-next" ${end >= total ? "disabled" : ""}>Next</button>
    </div>
  `;
  const prev = el.querySelector(".btn-prev");
  const next = el.querySelector(".btn-next");
  if (prev) prev.addEventListener("click", () => onPage(Math.max(0, offset - limit)));
  if (next) next.addEventListener("click", () => onPage(offset + limit));
}

/* ==================== MODALS & SAFETY PERMISSION GATES ==================== */

function showModal(title, bodyHtml, footerButtons) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  const footer = document.getElementById("modal-footer");
  footer.innerHTML = "";
  for (const btnCfg of footerButtons) {
    const btn = document.createElement("button");
    btn.id = btnCfg.id || "";
    btn.className = `btn ${btnCfg.cls || "btn-soft"}`;
    btn.textContent = btnCfg.text;
    btn.disabled = !!btnCfg.disabled;
    btn.addEventListener("click", btnCfg.onClick);
    footer.appendChild(btn);
  }
  document.getElementById("modal-backdrop").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal-backdrop").classList.add("hidden");
}

function openReviewModal() {
  const { items } = getEffectiveSelectedItems();
  const rowsHtml = items
    .map(
      (it) => `
      <div class="review-row">
        <div style="min-width:0;flex:1;">
          <div style="display:flex;gap:8px;align-items:center;">
            <strong>${escapeHtml(it.label)}</strong>
            ${renderRiskBadge(it.risk_level || "safe", it.risk_reason)}
          </div>
          <div class="item-subpath">${escapeHtml(it.path)}</div>
        </div>
        <span class="size-pill">${escapeHtml(it.size_human || formatBytes(it.size_bytes))}</span>
        <button class="btn btn-soft btn-sm btn-keep" data-key="${escapeHtml(it.key)}">Keep</button>
      </div>`
    )
    .join("");

  showModal(
    `Selected for Cleanup (${items.length})`,
    `<div class="review-list">${rowsHtml || "<p class='muted'>No items selected.</p>"}</div>`,
    [{ text: "Done", cls: "btn-primary", onClick: closeModal }]
  );

  document.querySelectorAll(".btn-keep").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.selectedMap.delete(btn.dataset.key);
      updateSelectionBar();
      renderSmartGroups();
      openReviewModal();
    });
  });
}

function openConfirmCleanModal() {
  const { items } = getEffectiveSelectedItems();
  if (items.length === 0) return;

  const mode = getDeleteMode();
  const totalBytes = items.reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
  const isPerm = mode === "permanent";
  const cautionItems = items.filter((it) => it.risk_level === "caution");
  const isDangerous = isPerm || cautionItems.length > 0;

  const warningHtml = isPerm
    ? `<div class="warning-box"><strong>Permission Required (Permanent Delete):</strong> Selected items will bypass the Recycle Bin and cannot be recovered.</div>`
    : `<div class="summary-strip">Safe mode: Items will be moved to your <strong>Recycle Bin / Trash</strong> so you can restore them if needed.</div>`;

  const cautionHtml = cautionItems.length
    ? `<div class="caution-box"><strong>Caution Items Flagged (${cautionItems.length}):</strong> You selected personal, active project, or sensitive files. Please verify you intend to remove them.</div>`
    : "";

  const ackHtml = isDangerous
    ? `<label class="ack-box"><input id="danger-ack" type="checkbox" /><span>I give permission to proceed with this ${isPerm ? "permanent deletion" : "caution cleanup"}.</span></label>`
    : "";

  showModal(
    isDangerous ? "Permission Required: Confirm Cleanup" : "Confirm Move to Recycle Bin",
    `
      ${warningHtml}
      ${cautionHtml}
      <p>Ready to clean <strong>${items.length}</strong> selected item(s) totaling <strong>${formatBytes(totalBytes)}</strong>.</p>
      <div class="review-list">
        ${items
          .slice(0, 40)
          .map(
            (it) => `
          <div class="review-row">
            <div style="min-width:0;flex:1;">
              <div style="display:flex;gap:8px;align-items:center;">
                <strong>${escapeHtml(it.label)}</strong>
                ${renderRiskBadge(it.risk_level || "safe", it.risk_reason)}
              </div>
              <div class="item-subpath">${escapeHtml(it.path)}</div>
              ${it.risk_level === "caution" && it.risk_reason ? `<div class="muted small-text">${escapeHtml(it.risk_reason)}</div>` : ""}
            </div>
            <span class="size-pill">${escapeHtml(it.size_human || formatBytes(it.size_bytes))}</span>
          </div>`
          )
          .join("")}
        ${items.length > 40 ? `<div class="muted small-text">...and ${items.length - 40} more item(s).</div>` : ""}
      </div>
      ${ackHtml}
    `,
    [
      { text: "Cancel", cls: "btn-soft", onClick: closeModal },
      {
        id: "btn-confirm-execute",
        text: isPerm ? "Permanently Delete" : "Move to Recycle Bin",
        cls: isPerm ? "btn-danger" : "btn-primary",
        disabled: isDangerous,
        onClick: () => runCleanup(items, mode),
      },
    ]
  );

  if (isDangerous) {
    const ackBox = document.getElementById("danger-ack");
    const execBtn = document.getElementById("btn-confirm-execute");
    ackBox.addEventListener("change", () => {
      execBtn.disabled = !ackBox.checked;
    });
  }
}

async function runCleanup(items, mode) {
  showModal("Cleaning Selected Items...", `<p class="muted">Removing selected items, please wait...</p>`, []);

  const includeDocker = items.some((it) => it.is_docker_prune);
  const targets = items
    .filter((it) => !it.is_docker_prune)
    .map((it) => ({ path: it.path, contents_only: !!it.contents_only }));

  const res = await api().execute_cleanup(targets, mode, includeDocker);
  renderDrives(res.drives_after);

  const hist = await api().get_history(50);
  updateHeaderCounts(undefined, hist.length);

  state.selectedMap.clear();
  updateSelectionBar();

  const failedHtml = (res.failed || []).length
    ? `<div class="warning-box" style="margin-top:12px;">
         <strong>Skipped / Locked (${res.failed.length}):</strong>
         <ul>${res.failed.slice(0, 15).map((f) => `<li><code>${escapeHtml(f.path)}</code>: ${escapeHtml(f.error)}</li>`).join("")}</ul>
       </div>`
    : "";

  const dockerHtml = res.docker_result
    ? `<p class="small-text"><strong>Docker Prune:</strong> ${escapeHtml(res.docker_result.message)}</p>`
    : "";

  showModal(
    "Cleanup Complete",
    `
      <div class="summary-strip">
        <div>Reclaimed: <strong class="accent-good">${escapeHtml(res.freed_human)}</strong></div>
        <div>Items cleaned: <strong>${res.deleted_count}</strong></div>
        <div>Mode: <strong>${res.mode === "permanent" ? "Permanent Delete" : "Recycle Bin"}</strong></div>
      </div>
      ${dockerHtml}
      ${failedHtml}
    `,
    [
      {
        text: "Done",
        cls: "btn-primary",
        onClick: async () => {
          closeModal();
          await loadSmartScan();
          if (state.browseState.path) {
            await Promise.all([loadAnalytics(), loadBrowseFolder(), loadAllFiles(), loadLargestFiles(), loadDevArtifacts()]);
          }
        },
      },
    ]
  );
}

let refreshResetTimer = null;

async function handleRefreshDrives() {
  const btn = document.getElementById("btn-refresh-drives");
  if (!btn || btn.disabled) return;
  if (refreshResetTimer) {
    clearTimeout(refreshResetTimer);
    refreshResetTimer = null;
  }

  btn.disabled = true;
  btn.classList.remove("is-done", "is-error");
  btn.classList.add("is-busy");
  btn.textContent = "Refreshing...";

  try {
    const [drives] = await Promise.all([
      api().refresh_drives(),
      new Promise((resolve) => setTimeout(resolve, 240)),
    ]);
    renderDrives(drives, true);
    btn.classList.remove("is-busy");
    btn.classList.add("is-done");
    btn.textContent = "Updated";
  } catch (_err) {
    btn.classList.remove("is-busy");
    btn.classList.add("is-error");
    btn.textContent = "Failed";
  } finally {
    btn.disabled = false;
    refreshResetTimer = setTimeout(() => {
      btn.classList.remove("is-busy", "is-done", "is-error");
      btn.textContent = "Refresh";
      refreshResetTimer = null;
    }, 1600);
  }
}

/* ==================== BOOTSTRAP & EVENT LISTENERS ==================== */

function bindEvents() {
  document.querySelectorAll(".nav-item[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.querySelectorAll(".subtab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchExplorerSubView(btn.dataset.subview));
  });

  document.getElementById("btn-theme-toggle").addEventListener("click", async () => {
    const next = state.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    await api().set_theme(next);
  });

  document.querySelectorAll('input[name="delete-mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      if (radio.value === "permanent" && radio.checked) {
        showModal(
          "Permission Required: Permanent Delete Mode",
          `<div class="warning-box"><strong>Warning:</strong> In Permanent Delete mode, cleaned files bypass the Recycle Bin and cannot be restored.</div>
           <p>Do you want to switch to Permanent Delete mode?</p>`,
          [
            {
              text: "Keep Safe Recycle Bin",
              cls: "btn-soft",
              onClick: () => {
                setDeleteMode("recycle");
                closeModal();
              },
            },
            {
              text: "Allow Permanent Delete",
              cls: "btn-danger",
              onClick: closeModal,
            },
          ]
        );
      }
    });
  });

  document.getElementById("btn-refresh-drives").addEventListener("click", handleRefreshDrives);

  document.getElementById("btn-exclusions").addEventListener("click", openExclusionsModal);
  document.getElementById("btn-history").addEventListener("click", openHistoryModal);

  document.getElementById("btn-elevate").addEventListener("click", () => {
    showModal(
      "Permission Required: Restart as Administrator",
      `<div class="caution-box">Windows UAC will prompt to relaunch DriveSweep with Administrator privileges so it can clean protected system temp folders.</div>`,
      [
        { text: "Cancel", cls: "btn-soft", onClick: closeModal },
        {
          text: "Continue & Relaunch",
          cls: "btn-primary",
          onClick: async () => {
            closeModal();
            const res = await api().relaunch_as_admin();
            if (!res.ok) {
              showModal("Elevation Failed", `<p>${escapeHtml(res.error || "Could not elevate.")}</p>`, [
                { text: "Close", cls: "btn-primary", onClick: closeModal },
              ]);
            }
          },
        },
      ]
    );
  });

  document.getElementById("btn-smart-scan").addEventListener("click", loadSmartScan);
  document.getElementById("smart-filter").addEventListener("input", renderSmartGroups);

  document.getElementById("btn-smart-recommended").addEventListener("click", () => {
    for (const item of state.smartItems) {
      const excluded = !!item.excluded || isPathExcludedLocal(item.path);
      setItemSelected({ ...item, source: "smart" }, !excluded && !!item.default_checked);
    }
    renderSmartGroups();
  });

  document.getElementById("btn-smart-all").addEventListener("click", () => {
    for (const item of state.smartItems) {
      const excluded = !!item.excluded || isPathExcludedLocal(item.path);
      if (!excluded) setItemSelected({ ...item, source: "smart" }, true);
    }
    renderSmartGroups();
  });

  document.getElementById("btn-smart-none").addEventListener("click", () => {
    for (const item of state.smartItems) {
      setItemSelected({ ...item, source: "smart" }, false);
    }
    renderSmartGroups();
  });

  document.getElementById("btn-pick-folder").addEventListener("click", async () => {
    const folder = await api().pick_folder();
    if (folder) startDriveScan(folder);
  });

  document.getElementById("btn-explorer-rescan").addEventListener("click", () => {
    if (state.activeDriveRoot) startDriveScan(state.activeDriveRoot, true);
  });

  document.getElementById("btn-cancel-scan").addEventListener("click", () => api().cancel_drive_scan());

  document.getElementById("browse-query").addEventListener("input", (e) => {
    state.browseState.query = e.target.value;
    state.browseState.offset = 0;
    loadBrowseFolder();
  });

  document.getElementById("browse-sort").addEventListener("change", (e) => {
    state.browseState.sort = e.target.value;
    state.browseState.offset = 0;
    loadBrowseFolder();
  });

  document.getElementById("btn-allfiles-search").addEventListener("click", () => {
    state.allFilesState.query = document.getElementById("allfiles-query").value;
    state.allFilesState.ext = document.getElementById("allfiles-ext").value;
    state.allFilesState.minMb = Number(document.getElementById("allfiles-minmb").value || 0);
    state.allFilesState.minAgeDays = Number(document.getElementById("allfiles-age").value || 0);
    state.allFilesState.sort = document.getElementById("allfiles-sort").value;
    state.allFilesState.offset = 0;
    loadAllFiles();
  });

  document.getElementById("devbloat-age").addEventListener("change", (e) => {
    state.devBloatMinAgeDays = Number(e.target.value || 0);
    loadDevArtifacts();
  });

  document.getElementById("btn-review-queue").addEventListener("click", openReviewModal);
  document.getElementById("btn-clean-now").addEventListener("click", openConfirmCleanModal);
  document.getElementById("btn-updates-privacy").addEventListener("click", () => openUpdatesPrivacyModal(false));
  document.getElementById("app-version").addEventListener("click", () => openUpdatesPrivacyModal(false));
  document.getElementById("modal-close").addEventListener("click", closeModal);
}

async function initApp() {
  bindEvents();
  const info = await api().get_app_info();
  applyTheme(info.theme || "dark");
  state.isAdmin = !!info.is_admin;
  state.osName = info.os || "Windows";
  state.version = info.version || "0.2.0";
  state.dataDir = info.data_dir || "";
  state.installKind = info.install_kind || "source";
  state.autoCheckUpdates = info.auto_check_updates !== false;
  document.getElementById("app-version").textContent = `v${state.version}`;
  updateHeaderCounts(info.exclusions || [], info.history_count || 0);

  if (state.isAdmin) {
    document.getElementById("priv-title").textContent = "Administrator";
    document.getElementById("priv-title").classList.add("accent-good");
    document.getElementById("priv-sub").textContent = "Full drive & system temp access";
  } else if (state.osName === "Windows") {
    document.getElementById("btn-elevate").classList.remove("hidden");
  }

  renderDrives(info.drives);
  await loadSmartScan();

  if (state.autoCheckUpdates) {
    api().check_for_updates().then((u) => {
      state.latestUpdateInfo = u;
      updateHeaderUpdateBadge(u);
    }).catch(() => {});
  }
}

if (window.pywebview && window.pywebview.api) {
  initApp();
} else {
  window.addEventListener("pywebviewready", initApp);
}
