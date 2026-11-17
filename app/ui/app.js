const GROUP_COLORS = {
  "Windows & Temp": "#10b981",
  "Web Browsers": "#f59e0b",
  "Desktop Apps": "#ec4899",
  "AI & Coding Tools": "#8b5cf6",
  "Dev Editors & Packages": "#3b82f6",
  "Custom Folders": "#14b8a6",
  "Other App Caches": "#06b6d4",
};

const ICON_FOLDER = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
const ICON_FILE = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>`;
const ICON_CHEVRON = `<svg class="group-chevron" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="6 9 12 15 18 9"/></svg>`;
const ICON_SUN = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`;
const ICON_MOON = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;

const state = {
  theme: "dark",
  language: "en",
  version: "0.7.2",
  activeTab: "smart",
  dataDir: "",
  installKind: "source",
  autoCheckUpdates: false,
  reminderEnabled: false,
  reminderFrequency: "weekly",
  reminderThresholdPct: 15,
  lowDiskAlerts: null,
  lowDiskBannerDismissed: false,
  latestUpdateInfo: null,
  drives: [],
  smartItems: [],
  largeData: null,
  largeMode: "files",
  largestMode: "files",
  windowsData: null,
  windowsAgeDays: 30,
  winsxsAnalysis: null,
  exclusions: [],
  collapsedGroups: new Set(),
  activeCategoryFilter: null,
  isAdmin: false,
  osName: "Windows",
  selectedMap: new Map(),
  activeDriveRoot: null,
  treemapPath: null,
  scanTimer: null,
  dupTimer: null,
  dupResult: null,
  isCleaning: false,
  isUpdating: false,
  isCheckingUpdates: false,
  modalToken: 0,
  lifetimeStats: { total_runs: 0, lifetime_freed_bytes: 0, lifetime_freed_human: "0 B" },
  browseState: { path: null, sort: "size", query: "", offset: 0, limit: 250 },
  allFilesState: { query: "", category: "", ext: "", minMb: 0, minAgeDays: 0, sort: "size", offset: 0, limit: 200 },
  devBloatMinAgeDays: 0,
  devBloatQuery: "",
  devBloatItems: [],
  dupQuery: "",
  dupKeepStrategy: "newest",
};

function api() {
  return window.pywebview.api;
}

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" };

// Escapes text for both element content and quoted attribute values (data-path="...", title="...").
function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"'`]/g, (ch) => HTML_ESCAPES[ch]);
}

// Translate an English interface sentence for the current language. Unknown sentences fall
// back to English. {name} placeholders are filled from vars.
function L(text, vars) {
  const i18n = window.DriveSweepI18n;
  let out = i18n && typeof i18n.phrase === "function" ? i18n.phrase(text) : text;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
  return out;
}

// Same as L, but HTML escaped for use inside markup. vars are inserted as given, so callers
// pass values that are already escaped (or deliberate markup such as <strong>).
function LH(text, vars) {
  const i18n = window.DriveSweepI18n;
  let out = escapeHtml(i18n && typeof i18n.phrase === "function" ? i18n.phrase(text) : text);
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
  return out;
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

function tr(key, fallback) {
  if (window.DriveSweepI18n && typeof window.DriveSweepI18n.t === "function") {
    const val = window.DriveSweepI18n.t(key);
    if (val && val !== key) return val;
  }
  return fallback || key;
}

function renderRiskBadge(riskLevel, riskReason) {
  const titleAttr = riskReason ? `title="${LH(riskReason)}"` : "";
  if (riskLevel === "critical") {
    return `<span class="badge badge-danger" ${titleAttr}>${escapeHtml(tr("badge_critical", "System"))}</span>`;
  }
  if (riskLevel === "caution") {
    return `<span class="badge badge-warn" ${titleAttr}>${escapeHtml(tr("badge_caution", "Caution"))}</span>`;
  }
  return `<span class="badge badge-good" ${titleAttr}>${escapeHtml(tr("badge_safe", "Safe"))}</span>`;
}

function buildSvgDonut(segments, centerTop, centerBottom, activeLabel = null, clickable = false) {
  const total = segments.reduce((acc, s) => acc + Number(s.value || 0), 0);
  if (total <= 0) {
    return `<div class="muted small-text">${LH("No data to chart yet.")}</div>`;
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
      <div class="donut-list-row ${clickable ? "is-clickable" : ""} ${activeLabel === (s.rawCategory || s.label) ? "is-active" : ""}" data-cat="${escapeHtml(s.rawCategory || s.label)}">
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

  document.getElementById("selected-count").textContent = count === 1 ? L("1 item selected") : L("{count} items selected", { count });
  document.getElementById("selected-size").textContent = sizeStr;

  const heroSel = document.getElementById("smart-selected-metric");
  const heroSub = document.getElementById("smart-selected-sub");
  if (heroSel) heroSel.textContent = sizeStr;
  if (heroSub) heroSub.textContent = count === 1 ? L("1 item queued") : L("{count} items queued", { count });

  document.querySelectorAll(".group-card[data-group]").forEach((card) => {
    const grp = card.dataset.group;
    const chip = card.querySelector(".group-selected-chip");
    if (!chip) return;
    const grpItems = state.smartItems.filter((it) => it.group === grp);
    const selCount = grpItems.filter((it) => !isPathExcludedLocal(it.path) && isItemSelected(it.path, !!it.contents_only)).length;
    chip.textContent = L("{done}/{total} selected", { done: selCount, total: grpItems.length });
  });

  const cleanBtn = document.getElementById("btn-clean-now");
  cleanBtn.textContent = count > 0 ? L("Clean {size}", { size: sizeStr }) : tr("clean_selected", "Clean Selected");
  cleanBtn.disabled = count === 0;

  const dedupNote = document.getElementById("dedup-note");
  if (nestedCount > 0) {
    dedupNote.textContent = nestedCount === 1 ? L("1 nested item covered by its parent folder") : L("{count} nested items covered by their parent folders", { count: nestedCount });
    dedupNote.classList.remove("hidden");
  } else {
    dedupNote.classList.add("hidden");
  }

  document.getElementById("btn-review-queue").disabled = count === 0;
  updateDockVisibility();
}

function updateDockVisibility() {
  const dock = document.getElementById("dock-bar");
  if (!dock) return;
  const { items } = getEffectiveSelectedItems();
  const hasExplorerSelected = items.some((it) => it.source !== "smart");
  const shouldShow = state.activeTab === "smart" || hasExplorerSelected;
  dock.classList.toggle("hidden", !shouldShow);
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

function showToast(message, tone = "info") {
  const host = document.getElementById("toast-container");
  if (!host || typeof document.createElement !== "function") return;
  const el = document.createElement("div");
  el.className = `toast toast-${tone}`;
  el.textContent = message;
  host.appendChild(el);
  setTimeout(() => {
    if (typeof el.remove === "function") el.remove();
  }, 2600);
}

async function copyCommandText(cmd, btnEl) {
  let ok = false;
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(cmd);
      ok = true;
    }
  } catch {
    ok = false;
  }
  if (!ok && typeof document.createElement === "function" && document.body) {
    try {
      const ta = document.createElement("textarea");
      ta.value = cmd;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ok = document.execCommand ? document.execCommand("copy") : false;
      ta.remove();
    } catch {
      ok = false;
    }
  }
  if (btnEl) {
    const prev = btnEl.textContent;
    btnEl.textContent = ok ? "Copied" : "Ready";
    setTimeout(() => {
      btnEl.textContent = prev;
    }, 1500);
  }
  showToast(ok ? L("Command copied to clipboard") : L("Command: {cmd}", { cmd }), ok ? "good" : "info");
}

function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll(".nav-item[data-tab]").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === `tab-${tabName}`);
  });

  const titleEl = document.getElementById("view-title");
  const subEl = document.getElementById("view-subtitle");
  const toolbarEl = document.getElementById("header-toolbar");
  const largeToolbarEl = document.getElementById("large-header-toolbar");
  const explorerToolbarEl = document.getElementById("explorer-header-toolbar");
  const windowsToolbarEl = document.getElementById("windows-header-toolbar");

  toolbarEl?.classList.add("hidden");
  largeToolbarEl?.classList.add("hidden");
  explorerToolbarEl?.classList.add("hidden");
  windowsToolbarEl?.classList.add("hidden");

  if (tabName === "smart") {
    titleEl.textContent = window.DriveSweepI18n ? window.DriveSweepI18n.t("smart_title") : "Quick Safe Cleanup";
    subEl.textContent = window.DriveSweepI18n ? window.DriveSweepI18n.t("smart_subtitle") : "Clean temporary files, browser caches, and leftover installers without touching your personal folders.";
    toolbarEl?.classList.remove("hidden");
  } else if (tabName === "large") {
    titleEl.textContent = window.DriveSweepI18n ? window.DriveSweepI18n.t("large_title") : "Large Files & Folders";
    subEl.textContent = window.DriveSweepI18n
      ? window.DriveSweepI18n.t("large_subtitle")
      : "Review large files and folders in Downloads, user spaces, and all drives. Nothing is selected unless you check it.";
    largeToolbarEl?.classList.remove("hidden");
    if (state.largeData === null) {
      loadLargeSpaces();
    } else {
      renderLargeSpacesTable();
    }
  } else if (tabName === "windows") {
    titleEl.textContent = window.DriveSweepI18n ? window.DriveSweepI18n.t("windows_title") : "Windows Space & Tools";
    subEl.textContent = window.DriveSweepI18n
      ? window.DriveSweepI18n.t("windows_subtitle")
      : "Inspect and reclaim Windows system storage including Recycle Bin, old Download installers, WinSxS updates, hibernation, and virtual disks.";
    windowsToolbarEl?.classList.remove("hidden");
    if (state.windowsData === null) {
      loadWindowsToolsView(false);
    } else {
      renderWindowsToolsView();
    }
  } else {
    titleEl.textContent = window.DriveSweepI18n ? window.DriveSweepI18n.t("explorer_title") : "Drive Scanner";
    subEl.textContent = window.DriveSweepI18n ? window.DriveSweepI18n.t("explorer_subtitle") : "Scan any drive or folder to see what takes up space, check safety levels, and find duplicates.";
    explorerToolbarEl?.classList.remove("hidden");
  }
  updateDockVisibility();
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
      <button class="side-drive ${state.activeDriveRoot === d.path ? "active" : ""}${pulseCls}" data-drive="${escapeHtml(d.path)}" title="${LH("{free} free of {total}", { free: escapeHtml(d.free_human), total: escapeHtml(d.total_human) })}">
        <div class="side-drive-top">
          <span>${LH("Drive {name}", { name: escapeHtml(d.name) })}</span>
          <span class="muted">${LH("{free} free", { free: escapeHtml(d.free_human) })}</span>
        </div>
        <div class="gauge-track">
          <div class="gauge-fill ${gaugeClass(d.used_percent)}" style="width: ${Math.min(100, d.used_percent)}%"></div>
        </div>
      </button>`
    )
    .join("");

  if (cardsEl) {
    cardsEl.innerHTML = state.drives
      .map(
        (d) => `
        <button class="drive-card ${state.activeDriveRoot === d.path ? "active" : ""}${pulseCls}" data-drive="${escapeHtml(d.path)}" title="${LH("Scan Drive {name}: {free} free of {total} ({pct}% used)", { name: escapeHtml(d.name), free: escapeHtml(d.free_human), total: escapeHtml(d.total_human), pct: d.used_percent })}">
          <span class="drive-pill-dot ${gaugeClass(d.used_percent)}"></span>
          <span class="drive-pill-name">${LH("Drive {name}", { name: escapeHtml(d.name) })}</span>
          <span class="drive-pill-meta">${LH("{free} free", { free: escapeHtml(d.free_human) })}</span>
        </button>`
      )
      .join("");
    cardsEl.querySelectorAll(".drive-card").forEach((btn) => {
      btn.addEventListener("click", () => startDriveScan(btn.dataset.drive));
    });
  }

  sideEl.querySelectorAll(".side-drive").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchTab("explorer");
      startDriveScan(btn.dataset.drive);
    });
  });

  updateDriveHealthPill();
}

function updateDriveHealthPill() {
  const pill = document.getElementById("drive-health-pill");
  const dot = document.getElementById("drive-health-dot");
  const badge = document.getElementById("drive-health-badge");
  const text = document.getElementById("drive-health-text");
  if (!pill || !dot || !badge || !text) return;

  const drives = Array.isArray(state.drives) ? state.drives : [];
  if (!drives.length) {
    pill.classList.remove("is-attention", "is-critical");
    pill.classList.add("is-healthy");
    dot.classList.remove("risk-dot-caution", "risk-dot-critical");
    dot.classList.add("risk-dot-safe");
    badge.textContent = tr("health_healthy", "Healthy");
    text.textContent = L("Checking drives...");
    return;
  }

  let totalFreeBytes = 0;
  let worstUsedPct = 0;
  for (const d of drives) {
    totalFreeBytes += Number(d.free_bytes || 0);
    const usedPct = Number(d.used_percent || 0);
    if (usedPct > worstUsedPct) worstUsedPct = usedPct;
  }

  const reclaimBytes = (state.smartItems || []).reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
  let level = "healthy";
  if (worstUsedPct >= 90) {
    level = "critical";
  } else if (worstUsedPct >= 80 || reclaimBytes >= 5 * 1024 * 1024 * 1024) {
    level = "attention";
  }

  pill.classList.remove("is-healthy", "is-attention", "is-critical");
  dot.classList.remove("risk-dot-safe", "risk-dot-caution", "risk-dot-critical");

  if (level === "critical") {
    pill.classList.add("is-critical");
    dot.classList.add("risk-dot-critical");
    badge.textContent = tr("health_low_space", "Low Space");
  } else if (level === "attention") {
    pill.classList.add("is-attention");
    dot.classList.add("risk-dot-caution");
    badge.textContent = tr("health_attention", "Attention");
  } else {
    pill.classList.add("is-healthy");
    dot.classList.add("risk-dot-safe");
    badge.textContent = tr("health_healthy", "Healthy");
  }

  const freeLabel = drives.length === 1 ? L("{size} free on 1 drive", { size: formatBytes(totalFreeBytes) }) : L("{size} total free across {count} drives", { size: formatBytes(totalFreeBytes), count: drives.length });
  const lifeBytes = Number(state.lifetimeStats?.lifetime_freed_bytes || 0);
  const parts = [freeLabel];
  if (reclaimBytes > 0) parts.push(L("{size} safe caches found", { size: formatBytes(reclaimBytes) }));
  if (lifeBytes > 0) parts.push(L("{size} reclaimed total", { size: formatBytes(lifeBytes) }));
  text.textContent = parts.join(" | ");
}

function recordLifetimeCleanup(freedBytes) {
  const b = Math.max(0, Number(freedBytes || 0));
  if (!state.lifetimeStats) {
    state.lifetimeStats = { total_runs: 0, lifetime_freed_bytes: 0, lifetime_freed_human: "0 B" };
  }
  if (b > 0) {
    state.lifetimeStats.total_runs = Number(state.lifetimeStats.total_runs || 0) + 1;
    state.lifetimeStats.lifetime_freed_bytes = Number(state.lifetimeStats.lifetime_freed_bytes || 0) + b;
    state.lifetimeStats.lifetime_freed_human = formatBytes(state.lifetimeStats.lifetime_freed_bytes);
    updateDriveHealthPill();
  }
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
  if (state.largeData) {
    renderLargeSpacesTable();
  }
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
        <button class="btn btn-soft btn-sm btn-remove-ex" data-path="${escapeHtml(p)}">${LH("Remove")}</button>
      </div>`
    )
    .join("");

  showModal(
    L("Always Keep List ({count})", { count: list.length }),
    `<p class="muted small-text">${LH('Paths listed here stay unchecked during Smart Scans and are marked "Always Keep" across DriveSweep.')}</p>
     <div class="review-list">${rows || `<p class='muted'>${LH("No excluded paths yet. Click '+ Add Folder...' below, or click 'Keep' on any folder or cache row to protect it.")}</p>`}</div>`,
    [
      {
        text: L("+ Add Folder..."),
        cls: "btn-soft",
        id: "btn-add-exclusion-folder",
        onClick: async () => {
          const folder = await api().pick_folder();
          if (!folder) return;
          const updated = await api().add_exclusion(folder);
          updateHeaderCounts(updated);
          await loadSmartScan();
          if (state.largeData) {
            renderLargeSpacesTable();
          }
          if (state.currentBrowse && typeof renderFoldersView === "function") {
            renderFoldersView();
          }
          await openExclusionsModal();
        },
      },
      { text: L("Close"), cls: "btn-primary", onClick: closeModal },
    ]
  );

  document.querySelectorAll(".btn-remove-ex").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const updated = await api().remove_exclusion(btn.dataset.path);
      updateHeaderCounts(updated);
      await loadSmartScan();
      if (state.largeData) {
        renderLargeSpacesTable();
      }
      if (state.currentBrowse && typeof renderFoldersView === "function") {
        renderFoldersView();
      }
      await openExclusionsModal();
    });
  });
}

async function openHistoryModal() {
  const entries = await api().get_history(50);
  updateHeaderCounts(undefined, entries.length);

  const entrySum = entries.reduce((acc, h) => acc + Math.max(0, Number(h.freed_bytes || 0)), 0);
  const lifeBytes = Math.max(entrySum, Number(state.lifetimeStats?.lifetime_freed_bytes || 0));
  const lifeRuns = Math.max(entries.length, Number(state.lifetimeStats?.total_runs || 0));
  const summaryHtml =
    lifeRuns > 0
      ? `<div class="summary-strip" style="margin-bottom:10px;">
           <div>${LH("Lifetime reclaimed:")} <strong class="accent-good">${escapeHtml(formatBytes(lifeBytes))}</strong></div>
           <div class="muted small-text">${lifeRuns === 1 ? LH("Across 1 cleanup run") : LH("Across {count} cleanup runs", { count: lifeRuns.toLocaleString() })}</div>
         </div>`
      : "";

  const rows = entries
    .map((h) => {
      const dateLabel = h.timestamp ? new Date(h.timestamp).toLocaleString() : "Unknown";
      const actionLabel = h.action || "Cleanup";
      const itemList = Array.isArray(h.items) ? h.items : [];
      const itemPreview = itemList.length
        ? `<div class="item-subpath" style="margin-top:3px;" title="${escapeHtml(itemList.join("\n"))}">${escapeHtml(itemList.slice(0, 3).join(", "))}${itemList.length > 3 ? ` ${LH("(+{count} more)", { count: itemList.length - 3 })}` : ""}</div>`
        : "";
      const modeClass = h.mode === "permanent" ? "badge-danger" : h.mode === "system" ? "badge-info" : "badge-good";
      const modeLabel = h.mode === "permanent" ? L("Permanent") : h.mode === "system" ? L("System Tool") : L("Recycle Bin");
      return `
        <div class="review-row">
          <div style="flex:1;min-width:0;">
            <div>
              <strong>${escapeHtml(h.freed_human)}</strong> reclaimed
              <span class="badge badge-info">${escapeHtml(actionLabel)}</span>
              <span class="badge ${modeClass}">${modeLabel}</span>
            </div>
            <div class="muted small-text">${escapeHtml(dateLabel)} | ${LH("{count} cleaned", { count: h.deleted_count })}${h.failed_count ? ` | ${LH("{count} failed", { count: h.failed_count })}` : ""}</div>
            ${itemPreview}
          </div>
        </div>`;
    })
    .join("");

  showModal(
    L("Cleanup Log ({count})", { count: entries.length }),
    `${summaryHtml}<div class="review-list">${rows || `<p class='muted'>${LH("No cleanup runs recorded yet.")}</p>`}</div>`,
    [
      {
        text: tr("open_recycle_bin", "Open Recycle Bin"),
        cls: "btn-soft",
        onClick: async () => {
          await api().open_recycle_bin();
        },
      },
      ...(entries.length
        ? [
            {
              text: L("Clear Log"),
              cls: "btn-soft",
              onClick: () => {
                showModal(
                  L("Permission Required: Clear Cleanup Log"),
                  `<div class="caution-box">${LH("This will permanently erase your local cleanup history log ({count} entries).", { count: entries.length })}</div>`,
                  [
                    { text: L("Cancel"), cls: "btn-soft", onClick: openHistoryModal },
                    {
                      text: L("Yes, Clear Log"),
                      cls: "btn-danger",
                      onClick: async () => {
                        await api().clear_history();
                        state.lifetimeStats = { total_runs: 0, lifetime_freed_bytes: 0, lifetime_freed_human: "0 B" };
                        updateDriveHealthPill();
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
      { text: L("Close"), cls: "btn-primary", onClick: closeModal },
    ]
  );
}

async function openUpdatesPrivacyModal(runCheckNow = false) {
  if (state.isUpdating && !document.getElementById("modal-backdrop")?.classList.contains("hidden")) {
    return;
  }
  let remStatus = {
    enabled: !!state.reminderEnabled,
    frequency: state.reminderFrequency || "weekly",
    threshold_pct: state.reminderThresholdPct || 15,
    task: { installed: false, next_run: "" },
  };
  try {
    remStatus = await api().get_reminder_status();
  } catch (_err) {}

  const langOptions = (window.DriveSweepI18n ? window.DriveSweepI18n.SUPPORTED : [{ code: "en", label: "English" }])
    .map((l) => `<option value="${l.code}" ${state.language === l.code ? "selected" : ""}>${escapeHtml(l.label)}</option>`)
    .join("");

  const renderBody = (statusHtml) => `
    <div class="settings-section">
      <h4>${LH("Language & Privacy")}</h4>
      <div class="settings-row">
        <div>
          <div style="font-weight:600;font-size:13px;">${LH("Interface Language")}</div>
          <div class="muted small-text">${LH("Changes menus and headings offline without restart.")}</div>
        </div>
        <select id="sel-ui-language" class="select">${langOptions}</select>
      </div>
      <div class="settings-row" style="margin-top:10px;">
        <div style="flex:1;min-width:0;">
          <div style="font-weight:600;font-size:13px;">${LH("Local Data & No Telemetry")}</div>
          <div class="item-subpath" style="margin-top:2px;">${escapeHtml(state.dataDir)}</div>
        </div>
        <button id="btn-open-data-dir" class="btn btn-soft btn-sm">${LH("Open Folder")}</button>
      </div>
    </div>

    <div class="settings-section">
      <h4>${LH("Optional Low-Disk Space Reminder (Windows Task Scheduler)")}</h4>
      <div class="settings-row">
        <label style="display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:600;">
          <input id="chk-reminder-enabled" type="checkbox" ${remStatus.enabled ? "checked" : ""} />
          <span>${LH("Notify me when a drive drops below")}</span>
        </label>
        <div style="display:flex;align-items:center;gap:6px;">
          <input id="inp-reminder-pct" type="number" min="5" max="50" class="input input-sm" style="width:68px;" value="${Number(remStatus.threshold_pct || 15)}" />
          <span class="small-text muted">${LH("% free")}</span>
          <select id="sel-reminder-freq" class="select">
            <option value="daily" ${remStatus.frequency === "daily" ? "selected" : ""}>${LH("Daily")}</option>
            <option value="weekly" ${remStatus.frequency === "weekly" ? "selected" : ""}>${LH("Weekly")}</option>
            <option value="monthly" ${remStatus.frequency === "monthly" ? "selected" : ""}>${LH("Monthly")}</option>
          </select>
          <button id="btn-save-reminder" class="btn btn-primary btn-xs">${LH("Save")}</button>
          <button id="btn-test-reminder" class="btn btn-soft btn-xs">${LH("Test Alert")}</button>
        </div>
      </div>
      <div id="reminder-status-msg" class="muted small-text" style="margin-top:6px;">
        ${remStatus.task?.installed ? (remStatus.task.next_run ? LH("Scheduled task active (Next run: {when}).", { when: escapeHtml(remStatus.task.next_run) }) : LH("Scheduled task active.")) : LH("Not scheduled (disabled by default).")}
      </div>
    </div>

    <label class="review-row" style="cursor:pointer;margin-bottom:12px;">
      <div>
        <div style="font-weight:600;font-size:13px;">${escapeHtml(tr("upd_check_label"))}</div>
        <div class="muted small-text">${escapeHtml(tr("upd_check_desc"))}</div>
      </div>
      <label class="toggle-switch">
        <input id="chk-auto-updates" type="checkbox" ${state.autoCheckUpdates ? "checked" : ""} />
        <span class="toggle-slider"></span>
      </label>
    </label>

    <div class="settings-section">
      <h4>${LH("Diagnostics & Crash Log")}</h4>
      <div class="settings-row">
        <div class="muted small-text">${LH("Version {version}", { version: "v" + escapeHtml(state.version) })} | ${escapeHtml(state.osName)} | ${state.isAdmin ? LH("Administrator") : LH("Standard Mode")}</div>
        <div style="display:flex;gap:6px;">
          <button id="btn-open-diag-log" class="btn btn-soft btn-xs">${escapeHtml(tr("view_log_file", "Open Diagnostics Log"))}</button>
          <button id="btn-clear-diag-log" class="btn btn-ghost btn-xs" title="${escapeHtml(tr("clear_logs_tip"))}">${escapeHtml(tr("clear_logs"))}</button>
        </div>
      </div>
    </div>

    <div id="update-status-panel" class="summary-strip">${statusHtml}</div>
  `;

  const formatUpdatePanel = (u) => {
    if (!u) {
      return `<div><strong>${LH("Current Version:")}</strong> v${escapeHtml(state.version)}<div class="muted small-text">${LH('Click "Check for Updates" to check GitHub Releases.')}</div></div>`;
    }
    if (!u.ok) {
      return `<div><strong>${LH("Update check failed")}</strong><div class="muted small-text">${escapeHtml(u.error || L("Network error"))}</div></div>`;
    }
    if (!u.update_available) {
      return `<div><strong>${LH("Up to date (v{version})", { version: escapeHtml(state.version) })}</strong><div class="muted small-text">${LH("Latest release on GitHub is v{version}.", { version: escapeHtml(u.latest_version) })}</div></div>`;
    }
    const pkgSize = u.asset_size > 0 ? ` (${formatBytes(u.asset_size)})` : "";
    return `
      <div style="width:100%;">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
          <div>
            <strong>${LH("Update Available: v{version}", { version: escapeHtml(u.latest_version) })}</strong>
            <span class="badge badge-info">${LH("Installed: v{version}", { version: escapeHtml(state.version) })}</span>
          </div>
          <span class="muted small-text">${escapeHtml(u.asset_name || "GitHub Release")}${escapeHtml(pkgSize)}</span>
        </div>
        <div class="muted small-text" style="margin-top:6px;">
          ${escapeHtml(describeUpdateMethod(u))}
        </div>
      </div>`;
  };

  const setUpdateModalBusy = (busy) => {
    state.isUpdating = busy;
    for (const id of ["btn-update-check", "btn-update-install", "btn-update-close"]) {
      const el = document.getElementById(id);
      if (el) el.disabled = busy;
    }
  };

  const renderUpdateProgress = (panel, msg, bytesText, pct) => {
    if (!panel) return;
    const width = Math.min(100, Math.max(4, pct || 4));
    let msgEl = document.getElementById("upd-stage-msg");
    if (!msgEl) {
      panel.innerHTML = `
        <div style="width:100%;">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;font-size:12.5px;">
            <strong id="upd-stage-msg"></strong>
            <span id="upd-bytes-label" class="muted"></span>
          </div>
          <div class="progress-track">
            <div id="upd-prog-fill" class="progress-fill" style="width:${width}%;transition:width 0.15s ease;"></div>
          </div>
        </div>`;
      msgEl = document.getElementById("upd-stage-msg");
    }
    const bytesEl = document.getElementById("upd-bytes-label");
    const fillEl = document.getElementById("upd-prog-fill");
    if (msgEl) msgEl.textContent = msg;
    if (bytesEl) bytesEl.textContent = bytesText;
    if (fillEl) fillEl.style.width = `${width}%`;
  };

  const runGuidedUpdate = async (u) => {
    const panel = document.getElementById("update-status-panel");
    setUpdateModalBusy(true);
    renderUpdateProgress(panel, L("Starting download of {name}...", { name: u.asset_name }), "0%", 4);
    try {
      await api().start_update_install(u.asset_url, u.asset_name, u.sha256_url, Number(u.asset_size || 0));
      while (true) {
        await new Promise((resolve) => setTimeout(resolve, 140));
        const st = await api().get_update_status();
        if (st.status === "error") {
          setUpdateModalBusy(false);
          if (panel) panel.innerHTML = `<div class="warning-box" style="margin:0;width:100%;">${escapeHtml(st.error || L("Update failed."))}</div>`;
          return;
        }
        const total = Number(st.total_bytes || 0);
        const dlBytes = Number(st.downloaded_bytes || 0);
        const pct = Number(st.percent || 0);
        const bytesLabel =
          st.status === "launching"
            ? "100%"
            : total > 0
              ? `${formatBytes(dlBytes)} / ${formatBytes(total)} (${pct}%)`
              : dlBytes > 0
                ? formatBytes(dlBytes)
                : "...";
        renderUpdateProgress(panel, st.message || L("Updating DriveSweep..."), bytesLabel, pct);
        if (st.status === "launching") {
          break;
        }
      }
    } catch (err) {
      setUpdateModalBusy(false);
      if (panel) panel.innerHTML = `<div class="warning-box" style="margin:0;width:100%;">${escapeHtml(String(err))}</div>`;
    }
  };

  const buildFooterButtons = () => {
    const btns = [
      {
        id: "btn-update-check",
        text: state.isCheckingUpdates ? L("Checking...") : L("Check for Updates"),
        cls: "btn-soft",
        disabled: state.isCheckingUpdates || state.isUpdating,
        onClick: () => runCheckInModal(modalToken),
      },
    ];
    const u = state.latestUpdateInfo;
    if (u && u.ok && u.update_available && u.asset_url && u.sha256_url) {
      btns.push({
        id: "btn-update-install",
        text: L("Download & Update v{version}", { version: u.latest_version }),
        cls: "btn-cta",
        disabled: state.isCheckingUpdates || state.isUpdating,
        onClick: () => runGuidedUpdate(u),
      });
    }
    btns.push({
      id: "btn-update-close",
      text: L("Close"),
      cls: "btn-primary",
      disabled: state.isUpdating,
      onClick: closeModal,
    });
    return btns;
  };

  let modalToken = 0;

  const runCheckInModal = async (expectedToken) => {
    if (state.isCheckingUpdates || state.isUpdating) return;
    state.isCheckingUpdates = true;
    setModalFooterButtons(buildFooterButtons());
    const panel = document.getElementById("update-status-panel");
    if (panel) panel.innerHTML = `<div class="muted">${LH("Checking GitHub Releases...")}</div>`;
    try {
      const res = await api().check_for_updates();
      state.latestUpdateInfo = res;
      updateHeaderUpdateBadge(res);
      if (state.modalToken !== expectedToken) return;
      const curPanel = document.getElementById("update-status-panel");
      if (curPanel) curPanel.innerHTML = formatUpdatePanel(res);
    } catch (err) {
      if (state.modalToken !== expectedToken) return;
      const curPanel = document.getElementById("update-status-panel");
      if (curPanel) curPanel.innerHTML = `<div class="warning-box" style="margin:0;width:100%;">${escapeHtml(String(err))}</div>`;
    } finally {
      state.isCheckingUpdates = false;
      if (state.modalToken === expectedToken && !state.isUpdating) {
        setModalFooterButtons(buildFooterButtons());
      }
    }
  };

  modalToken = showModal(
    tr("settings_modal_title", "Settings, Schedule & Updates"),
    renderBody(formatUpdatePanel(state.latestUpdateInfo)),
    buildFooterButtons()
  );

  document.getElementById("btn-open-data-dir")?.addEventListener("click", () => api().open_data_dir());
  document.getElementById("btn-open-diag-log")?.addEventListener("click", () => api().open_log_file());
  document.getElementById("btn-clear-diag-log")?.addEventListener("click", async () => {
    try {
      await api().clear_logs();
      showToast(tr("logs_cleared"), "good");
    } catch (err) {
      showToast(String(err), "danger");
    }
  });
  document.getElementById("chk-auto-updates")?.addEventListener("change", async (e) => {
    state.autoCheckUpdates = !!e.target.checked;
    await api().set_auto_check_updates(state.autoCheckUpdates);
  });
  document.getElementById("sel-ui-language")?.addEventListener("change", async (e) => {
    const lang = e.target.value || "en";
    state.language = lang;
    await api().set_language(lang);
    if (window.DriveSweepI18n) {
      window.DriveSweepI18n.setLanguage(lang);
    }
    const activeTabBtn = document.querySelector(".nav-item.active[data-tab]");
    if (activeTabBtn) switchTab(activeTabBtn.dataset.tab);
    updateSelectionBar();
    renderSmartGroups();
    updateCollapseToggleBtn();
    renderPrivilegeLabels();
    updateDriveHealthPill();
    if (state.dupResult) renderDuplicateResults();
  });
  document.getElementById("btn-save-reminder")?.addEventListener("click", async () => {
    const enabled = !!document.getElementById("chk-reminder-enabled")?.checked;
    const freq = document.getElementById("sel-reminder-freq")?.value || "weekly";
    const pct = Number(document.getElementById("inp-reminder-pct")?.value || 15);
    const msgEl = document.getElementById("reminder-status-msg");
    if (msgEl) msgEl.textContent = L("Saving Windows schedule...");
    const res = await api().configure_disk_reminder(enabled, freq, pct);
    state.reminderEnabled = !!res.enabled;
    state.reminderFrequency = res.frequency || freq;
    state.reminderThresholdPct = Number(res.threshold_pct || pct);
    state.lowDiskAlerts = res.alerts || null;
    renderLowDiskBanner();
    if (msgEl) {
      msgEl.textContent = res.ok
        ? (res.enabled ? L("Scheduled {frequency} reminder saved.", { frequency: L(res.frequency === "daily" ? "Daily" : res.frequency === "monthly" ? "Monthly" : "Weekly").toLowerCase() }) : L("Scheduled reminder disabled."))
        : L("Could not update Task Scheduler: {error}", { error: res.error || L("Unknown error") });
    }
  });
  document.getElementById("btn-test-reminder")?.addEventListener("click", async () => {
    const msgEl = document.getElementById("reminder-status-msg");
    const res = await api().test_low_disk_notification();
    if (msgEl) {
      msgEl.textContent = res.ok ? L("Test notification sent to Windows tray.") : L("Notification error: {error}", { error: res.error || L("Failed") });
    }
  });

  if (runCheckNow && !state.isUpdating) {
    await runCheckInModal(modalToken);
  }
}

function updateHeaderUpdateBadge(u) {
  const chip = document.getElementById("app-version");
  const navBadge = document.getElementById("update-nav-badge");
  if (u && u.ok && u.update_available) {
    chip.classList.add("update-ready");
    chip.title = L("Update available: v{version}. Click to view.", { version: u.latest_version });
    navBadge?.classList.remove("hidden");
  } else {
    chip.classList.remove("update-ready");
    chip.title = L("View updates and local privacy settings");
    navBadge?.classList.add("hidden");
  }
}

function renderLowDiskBanner() {
  const banner = document.getElementById("low-disk-banner");
  if (!banner) return;
  const info = state.lowDiskAlerts;
  const alerts = (info && info.alerts) || [];
  if (!alerts.length || state.lowDiskBannerDismissed) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
    return;
  }
  const hasCritical = alerts.some((a) => a.severity === "critical");
  banner.classList.toggle("is-critical", hasCritical);
  banner.classList.remove("hidden");
  const visible = alerts.slice(0, 2);
  const extraCount = Math.max(0, alerts.length - visible.length);
  const summary =
    visible
      .map((a) => `<strong>${escapeHtml(a.drive.replace(/\\+$/, ""))}</strong> (${LH("{free} free", { free: escapeHtml(a.free_human) })}, ${a.free_pct}%)`)
      .join(" \u00b7 ") + (extraCount > 0 ? ` <span class="muted">${LH("(+{count} more)", { count: extraCount })}</span>` : "");
  banner.innerHTML = `
    <div style="font-size:12.5px;display:flex;align-items:center;gap:8px;min-width:0;">
      <span class="risk-dot ${hasCritical ? "risk-dot-critical" : "risk-dot-caution"}"></span>
      <span><strong>${LH("Low Disk Space:")}</strong> ${summary}</span>
    </div>
    <div style="display:flex;gap:6px;align-items:center;">
      <button id="btn-banner-scan" class="btn btn-soft btn-xs">${LH("Scan {drive}", { drive: escapeHtml(alerts[0].drive.replace(/\\+$/, "")) })}</button>
      <button id="btn-banner-tools" class="btn btn-soft btn-xs">${LH("Windows Tools")}</button>
      <button id="btn-banner-dismiss" class="btn-icon-quiet" title="${LH("Dismiss")}" aria-label="${LH("Dismiss")}">&times;</button>
    </div>
  `;
  document.getElementById("btn-banner-scan")?.addEventListener("click", () => {
    switchTab("explorer");
    startDriveScan(alerts[0].drive);
  });
  document.getElementById("btn-banner-tools")?.addEventListener("click", () => switchTab("windows"));
  document.getElementById("btn-banner-dismiss")?.addEventListener("click", () => {
    state.lowDiskBannerDismissed = true;
    renderLowDiskBanner();
  });
}

async function promptAddCustomPreset() {
  const res = await api().add_custom_preset("", "", true);
  if (res.cancelled) return;
  if (!res.ok) {
    showModal(
      L("Could Not Add Custom Folder"),
      `<div class="warning-box">${escapeHtml(res.error || L("Invalid folder."))}</div>`,
      [{ text: L("Close"), cls: "btn-primary", onClick: closeModal }]
    );
    return;
  }
  await loadSmartScan();
}

function buildWindowsToolsHtml(data, isPageView = true) {
  const rb = data.recycle_bin || {};
  const rbDrives = Array.isArray(data.recycle_bin_drives) ? data.recycle_bin_drives : [];
  const oldInst = data.old_installers || { count: 0, total_human: "0 B", items: [] };
  const winOld = data.windows_old || { present: false, path: "C:\\Windows.old", size_bytes: 0, size_human: "0 B" };
  const hib = data.hibernation || {};
  const vhdx = data.virtual_disks || { count: 0, total_human: "0 B", items: [] };
  const ageDays = Number(state.windowsAgeDays || 30);

  const totalKnownBytes =
    Number(rb.size_bytes || 0) +
    Number(oldInst.total_bytes || 0) +
    Number(winOld.size_bytes || 0) +
    Number(hib.size_bytes || 0) +
    Number(vhdx.total_bytes || 0);

  const rbEmpty = (rb.size_bytes || 0) === 0 && (rb.item_count || 0) === 0;
  const rbDriveChips = rbDrives
    .map(
      (d) =>
        `<span class="drive-chip"><strong>${escapeHtml(String(d.drive || "").replace(/\\+$/, ""))}</strong> ${escapeHtml(d.size_human || "0 B")} (${Number(d.item_count || 0)})</span>`
    )
    .join("");

  const instRows = (oldInst.items || [])
    .slice(0, 12)
    .map(
      (it) => `
      <div class="review-row">
        <div style="flex:1;min-width:0;">
          <div style="font-weight:600;font-size:12.5px;">${escapeHtml(it.name)}</div>
          <div class="item-subpath">${LH("{days} days old", { days: it.age_days })} | ${escapeHtml(it.path)}</div>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
          <strong>${escapeHtml(it.size_human)}</strong>
          <button class="btn btn-soft btn-xs btn-queue-inst" data-path="${escapeHtml(it.path)}" data-name="${escapeHtml(it.name)}" data-size="${it.size_bytes}" data-human="${escapeHtml(it.size_human)}">${LH("Queue")}</button>
        </div>
      </div>`
    )
    .join("");

  const maxVhdx = Math.max(1, ...(vhdx.items || []).map((v) => Number(v.size_bytes || 0)));
  const vhdxRows = (vhdx.items || [])
    .slice(0, 6)
    .map((v) => {
      const pct = Math.min(100, Math.max(4, Math.round((Number(v.size_bytes || 0) / maxVhdx) * 100)));
      const compactCmd = `wsl --shutdown; Optimize-VHD -Path "${v.path}" -Mode Full`;
      return `
      <div class="vhdx-row">
        <div class="vhdx-row-top">
          <div style="min-width:0;flex:1;">
            <div style="font-weight:600;font-size:12.5px;">${escapeHtml(v.name)} <span class="muted">(${escapeHtml(v.parent)})</span></div>
            <div class="item-subpath">${escapeHtml(v.path)}</div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;">
            <strong>${escapeHtml(v.size_human)}</strong>
            <button class="btn btn-primary btn-xs btn-compact-vhdx" data-path="${escapeHtml(v.path)}" data-name="${escapeHtml(v.name)}">${LH("Shrink Disk")}</button>
            <button class="btn btn-soft btn-xs btn-open-vhdx" data-path="${escapeHtml(v.path)}">${LH("Reveal")}</button>
            <button class="btn btn-ghost btn-xs btn-copy-cmd" data-cmd="${escapeHtml(compactCmd)}">${LH("Copy Cmd")}</button>
          </div>
        </div>
        <div class="space-map-bar-wrap">
          <div class="space-map-bar-fill" style="width:${pct}%;background:var(--accent-2);"></div>
        </div>
      </div>`;
    })
    .join("");

  const winsxsHtml = state.winsxsAnalysis
    ? `
      <div class="kpi-mini-grid">
        <div class="kpi-mini-cell">
          <div class="kpi-mini-label">${LH("Component Store")}</div>
          <div class="kpi-mini-val">${escapeHtml(state.winsxsAnalysis.component_store_size || "Unknown")}</div>
        </div>
        <div class="kpi-mini-cell">
          <div class="kpi-mini-label">${LH("Backups & Disabled")}</div>
          <div class="kpi-mini-val">${escapeHtml(state.winsxsAnalysis.backups_and_disabled || "0")}</div>
        </div>
        <div class="kpi-mini-cell">
          <div class="kpi-mini-label">${LH("Reclaimable")}</div>
          <div class="kpi-mini-val">${escapeHtml(state.winsxsAnalysis.reclaimable_packages || "0")} packages</div>
        </div>
        <div class="kpi-mini-cell">
          <div class="kpi-mini-label">${LH("Cleanup Needed")}</div>
          <div class="kpi-mini-val">${state.winsxsAnalysis.cleanup_recommended ? `<span class="badge badge-warn">${LH("Recommended")}</span>` : `<span class="badge badge-good">${LH("Optimal")}</span>`}</div>
        </div>
      </div>`
    : "";

  const summaryBanner = isPageView
    ? `
    <div class="windows-summary-strip">
      <div class="windows-summary-metrics">
        <span>${LH("Inspectable Windows space:")} <strong>${escapeHtml(formatBytes(totalKnownBytes))}</strong></span>
        <span class="risk-quiet-sep">|</span>
        <span>${LH("Recycle Bin:")} <strong>${escapeHtml(rb.size_human || "0 B")}</strong></span>
        <span class="risk-quiet-sep">|</span>
        <span>${LH("Old Downloads:")} <strong>${escapeHtml(oldInst.total_human || "0 B")}</strong></span>
        <span class="risk-quiet-sep">|</span>
        <span>${LH("Virtual Disks:")} <strong>${escapeHtml(vhdx.total_human || "0 B")}</strong></span>
      </div>
      <span class="badge ${data.is_admin ? "badge-good" : "badge-warn"}">${data.is_admin ? LH("Administrator Active") : LH("Admin Needed for DISM")}</span>
    </div>`
    : "";

  return `
    ${summaryBanner}
    <div class="${isPageView ? "windows-tools-grid" : ""}">
      <div class="${isPageView ? "tool-card" : "settings-section"}">
        <div class="tool-card-header">
          <div>
            <h4 class="tool-card-title">${LH("Windows Recycle Bin")}</h4>
            <p class="tool-card-desc">${LH("Inspect or permanently clear trashed files across all attached drives.")}</p>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0;">
            <button id="btn-sys-open-rb" class="btn btn-soft btn-xs">${LH("Open Recycle Bin")}</button>
            <button id="btn-sys-empty-rb" class="btn btn-danger btn-xs" ${rbEmpty ? "disabled" : ""}>${LH("Empty Recycle Bin")}</button>
          </div>
        </div>
        <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;">
          <span id="rb-size-label" class="tool-kpi-value">${escapeHtml(rb.size_human || "0 B")}</span>
          <span class="muted small-text">${LH("{count} items waiting in Recycle Bin", { count: Number(rb.item_count || 0).toLocaleString() })}</span>
        </div>
        ${rbDriveChips ? `<div class="tool-drive-chips">${rbDriveChips}</div>` : ""}
        <div id="rb-status-msg" class="muted small-text"></div>
      </div>

      <div class="${isPageView ? "tool-card" : "settings-section"}">
        <div class="tool-card-header">
          <div>
            <h4 class="tool-card-title">${LH("Old Installers & Archives in Downloads")}</h4>
            <p class="tool-card-desc">${LH("Untouched installers older than {days} days ({size} found).", { days: ageDays, size: escapeHtml(oldInst.total_human || "0 B") })}</p>
          </div>
          ${oldInst.count > 0 ? `<button id="btn-sys-queue-all-inst" class="btn btn-primary btn-xs">${LH("Queue All ({count})", { count: oldInst.count })}</button>` : ""}
        </div>
        <div class="review-list">${instRows || `<div class="tool-empty-note">${LH("Clean: no installers or archives older than {days} days in Downloads.", { days: ageDays })}</div>`}</div>
      </div>

      <div class="${isPageView ? "tool-card" : "settings-section"}">
        <div class="tool-card-header">
          <div>
            <h4 class="tool-card-title">${LH("Windows Update Store (WinSxS / DISM)")}</h4>
            <p class="tool-card-desc">${LH("Analyze or safely remove superseded Windows Update component backups.")}</p>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0;">
            <button id="btn-sys-winsxs-analyze" class="btn btn-soft btn-xs">${LH("Analyze WinSxS")}</button>
            <button id="btn-sys-winsxs-clean" class="btn btn-primary btn-xs">${LH("Clean Old Updates")}</button>
          </div>
        </div>
        <div class="summary-strip" style="padding:8px 11px;">
          <div class="small-text">
            ${LH("Previous Windows backup ({name}):", { name: "<code>Windows.old</code>" })}
            <strong>${winOld.present ? escapeHtml(winOld.size_human || "0 B") : LH("Not present (0 B)")}</strong>
          </div>
          ${winOld.present ? `<div style="display:flex;gap:6px;"><button id="btn-sys-queue-winold" class="btn btn-primary btn-xs" data-path="${escapeHtml(winOld.path)}" data-size="${winOld.size_bytes || 0}" data-human="${escapeHtml(winOld.size_human || "0 B")}">${LH("Queue")}</button><button id="btn-sys-open-winold" class="btn btn-soft btn-xs" data-path="${escapeHtml(winOld.path)}">${LH("Reveal")}</button></div>` : `<span class="badge badge-good">${LH("Clean")}</span>`}
        </div>
        <div id="winsxs-output" class="tool-output-box ${state.winsxsAnalysis ? "" : "hidden"}">${winsxsHtml}</div>
      </div>

      <div class="${isPageView ? "tool-card" : "settings-section"}">
        <div class="tool-card-header">
          <div>
            <h4 class="tool-card-title">${LH("Hibernation & WSL2 / Docker Virtual Disks")}</h4>
            <p class="tool-card-desc">${LH("Virtual disks grow over time and do not shrink automatically when containers are removed.")}</p>
          </div>
        </div>
        <div class="summary-strip" style="padding:8px 11px;">
          <div class="small-text">
            ${LH("Hibernation file ({name}):", { name: "<code>hiberfil.sys</code>" })}
            <strong>${hib.present ? escapeHtml(hib.size_human) : LH("Not active (0 B)")}</strong>
          </div>
          ${hib.present ? `<button id="btn-sys-hiber-toggle" class="btn btn-primary btn-xs" data-enable="0">${LH("Disable Hibernation (Free {size})", { size: escapeHtml(hib.size_human) })}</button>` : `<div style="display:flex;align-items:center;gap:8px;"><span class="badge badge-good">${LH("Off")}</span><button id="btn-sys-hiber-toggle" class="btn btn-soft btn-xs" data-enable="1">${LH("Enable Hibernation")}</button></div>`}
        </div>
        <div class="small-text muted">${vhdx.count === 1 ? LH("1 virtual disk detected ({size} total)", { size: escapeHtml(vhdx.total_human || "0 B") }) : LH("{count} virtual disks detected ({size} total)", { count: vhdx.count, size: escapeHtml(vhdx.total_human || "0 B") })}</div>
        <div class="review-list">${vhdxRows || `<div class="tool-empty-note">${LH("No WSL2 or Docker .vhdx virtual disks detected.")}</div>`}</div>
        <div id="sys-hiber-vhdx-output" class="tool-output-box hidden"></div>
      </div>
    </div>
  `;
}

function bindWindowsToolsEvents(data, { inModal = false } = {}) {
  const oldInst = data.old_installers || { items: [] };

  document.getElementById("btn-sys-open-rb")?.addEventListener("click", () => api().open_recycle_bin());
  document.getElementById("btn-sys-empty-rb")?.addEventListener("click", async () => {
    const rbBtn = document.getElementById("btn-sys-empty-rb");
    const msgEl = document.getElementById("rb-status-msg");
    if (rbBtn) rbBtn.disabled = true;
    if (msgEl) msgEl.textContent = L("Emptying Windows Recycle Bin...");
    const res = await api().empty_recycle_bin(null);
    if (res.ok) {
      if (res.freed_bytes) recordLifetimeCleanup(res.freed_bytes);
      if (res.drives_after) renderDrives(res.drives_after);
      if (typeof res.history_count === "number") updateHeaderCounts(undefined, res.history_count);
      const lbl = document.getElementById("rb-size-label");
      if (lbl) lbl.textContent = "0 B";
      const summaryMsg = res.already_empty ? L("Recycle Bin is already empty.") : L("Freed {size} from Recycle Bin.", { size: res.freed_human });
      if (msgEl) msgEl.textContent = summaryMsg;
      showToast(summaryMsg, "good");
      state.windowsData = null;
    } else {
      if (msgEl) msgEl.textContent = res.error || L("Could not empty Recycle Bin.");
      if (rbBtn) rbBtn.disabled = false;
    }
  });

  document.querySelectorAll(".btn-queue-inst").forEach((b) => {
    b.addEventListener("click", () => {
      setItemSelected(
        {
          path: b.dataset.path,
          label: b.dataset.name,
          size_bytes: Number(b.dataset.size || 0),
          size_human: b.dataset.human,
          contents_only: false,
          risk_level: "caution",
          risk_reason: L("Old installer package in Downloads."),
          source: "explorer",
        },
        true
      );
      b.textContent = L("Queued");
      b.disabled = true;
      showToast(L("Queued {name} for cleanup", { name: b.dataset.name }), "info");
    });
  });

  document.getElementById("btn-sys-queue-all-inst")?.addEventListener("click", () => {
    for (const it of oldInst.items || []) {
      setItemSelected(
        {
          path: it.path,
          label: it.name,
          size_bytes: it.size_bytes,
          size_human: it.size_human,
          contents_only: false,
          risk_level: "caution",
          risk_reason: L("Old installer ({days} days old) in Downloads.", { days: it.age_days }),
          source: "explorer",
        },
        true
      );
    }
    if (inModal) closeModal();
    openReviewModal();
  });

  document.getElementById("btn-sys-open-winold")?.addEventListener("click", (e) => {
    api().open_in_explorer(e.currentTarget.dataset.path || "C:\\Windows.old");
  });
  document.getElementById("btn-sys-queue-winold")?.addEventListener("click", (e) => {
    const btn = e.currentTarget;
    setItemSelected(
      {
        path: btn.dataset.path || "C:\\Windows.old",
        label: L("Windows.old (Previous Windows Backup)"),
        size_bytes: Number(btn.dataset.size || 0),
        size_human: btn.dataset.human || "0 B",
        contents_only: false,
        risk_level: "caution",
        risk_reason: L("Previous Windows version backup. Safe to remove if your current Windows update is working well."),
        source: "explorer",
      },
      true
    );
    btn.textContent = L("Queued");
    btn.disabled = true;
    showToast(L("Queued Windows.old for cleanup"), "info");
  });

  document.querySelectorAll(".btn-open-vhdx").forEach((b) => {
    b.addEventListener("click", () => api().open_in_explorer(b.dataset.path));
  });

  document.querySelectorAll(".btn-copy-cmd").forEach((b) => {
    b.addEventListener("click", () => copyCommandText(b.dataset.cmd || "", b));
  });

  const hibOut = document.getElementById("sys-hiber-vhdx-output");
  const hibBtn = document.getElementById("btn-sys-hiber-toggle");
  hibBtn?.addEventListener("click", async () => {
    const enable = hibBtn.dataset.enable === "1";
    if (!data.is_admin) {
      showToast(L("Administrator rights required to change Windows hibernation"), "warn");
      if (hibOut) {
        hibOut.classList.remove("hidden");
        hibOut.textContent = L("Restart DriveSweep as Administrator to toggle Windows hibernation.");
      }
      return;
    }
    hibBtn.disabled = true;
    const prevLabel = hibBtn.textContent;
    hibBtn.textContent = enable ? "Enabling..." : "Disabling...";
    if (hibOut) {
      hibOut.classList.remove("hidden");
      hibOut.innerHTML = `<span class="muted">${enable ? LH("Turning hibernation on...") : LH("Turning hibernation off...")}</span>`;
    }
    try {
      const res = await api().set_hibernation_enabled(enable);
      if (!res.ok) {
        if (hibOut) hibOut.textContent = res.error || L("Could not update hibernation setting.");
        showToast(res.error || L("Hibernation change failed"), "danger");
        hibBtn.disabled = false;
        hibBtn.textContent = prevLabel;
        return;
      }
      if (!enable && res.freed_bytes) recordLifetimeCleanup(res.freed_bytes);
      if (res.drives_after) renderDrives(res.drives_after);
      if (typeof res.history_count === "number") updateHeaderCounts(undefined, res.history_count);
      showToast(res.message || L("Updated Windows hibernation"), "good");
      state.windowsData = null;
      if (inModal) {
        await openSystemToolsModal();
      } else {
        await loadWindowsToolsView(true);
      }
    } catch (err) {
      if (hibOut) hibOut.textContent = String(err);
      hibBtn.disabled = false;
      hibBtn.textContent = prevLabel;
    }
  });

  document.querySelectorAll(".btn-compact-vhdx").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const vhdxPath = btn.dataset.path || "";
      const vhdxName = btn.dataset.name || "virtual disk";
      if (!data.is_admin) {
        showToast(L("Administrator rights required to compact virtual disks"), "warn");
        if (hibOut) {
          hibOut.classList.remove("hidden");
          hibOut.textContent = L("Restart DriveSweep as Administrator to compact virtual disks automatically.");
        }
        return;
      }
      const wslWarning = tr("wsl_body").replace("{name}", vhdxName);
      const proceed = inModal
        ? window.confirm(`${tr("wsl_prompt")}\n\n${wslWarning}`)
        : await confirmAction(
            tr("wsl_title"),
            `<div class="caution-box"><strong>${escapeHtml(tr("wsl_heading"))}</strong> ${escapeHtml(wslWarning)}</div>`,
            tr("wsl_confirm")
          );
      if (!proceed) return;
      const allShrinkBtns = Array.from(document.querySelectorAll(".btn-compact-vhdx"));
      allShrinkBtns.forEach((b) => (b.disabled = true));
      btn.textContent = L("Shrinking...");
      if (hibOut) {
        hibOut.classList.remove("hidden");
        hibOut.innerHTML = `<span class="muted">${LH("Stopping WSL/Docker backend and compacting {name}...", { name: escapeHtml(vhdxName) })}</span>`;
      }
      try {
        const res = await api().compact_virtual_disk(vhdxPath);
        if (!res.ok) {
          if (hibOut) hibOut.textContent = res.error || L("Virtual disk compaction failed.");
          showToast(res.error || L("Could not shrink virtual disk"), "danger");
          allShrinkBtns.forEach((b) => (b.disabled = false));
          btn.textContent = L("Shrink Disk");
          return;
        }
        if (res.freed_bytes) recordLifetimeCleanup(res.freed_bytes);
        if (res.drives_after) renderDrives(res.drives_after);
        if (typeof res.history_count === "number") updateHeaderCounts(undefined, res.history_count);
        showToast(res.message || L("Compacted {name}", { name: vhdxName }), "good");
        state.windowsData = null;
        if (inModal) {
          await openSystemToolsModal();
        } else {
          await loadWindowsToolsView(true);
        }
      } catch (err) {
        if (hibOut) hibOut.textContent = String(err);
        allShrinkBtns.forEach((b) => (b.disabled = false));
        btn.textContent = L("Shrink Disk");
      }
    });
  });

  const outBox = document.getElementById("winsxs-output");
  const analyzeBtn = document.getElementById("btn-sys-winsxs-analyze");
  const cleanBtn = document.getElementById("btn-sys-winsxs-clean");

  analyzeBtn?.addEventListener("click", async () => {
    if (!outBox) return;
    analyzeBtn.disabled = true;
    if (cleanBtn) cleanBtn.disabled = true;
    outBox.classList.remove("hidden");
    outBox.innerHTML = `<div class="muted">${LH("Running DISM /AnalyzeComponentStore (usually takes 30 to 90 seconds)...")}</div>`;
    try {
      const res = await api().analyze_winsxs();
      if (!res.ok) {
        outBox.textContent = res.error || "WinSxS analysis failed.";
        return;
      }
      state.winsxsAnalysis = res;
      outBox.innerHTML = `
        <div class="kpi-mini-grid" style="margin-top:0;">
          <div class="kpi-mini-cell">
            <div class="kpi-mini-label">${LH("Component Store")}</div>
            <div class="kpi-mini-val">${escapeHtml(res.component_store_size || "Unknown")}</div>
          </div>
          <div class="kpi-mini-cell">
            <div class="kpi-mini-label">${LH("Backups & Disabled")}</div>
            <div class="kpi-mini-val">${escapeHtml(res.backups_and_disabled || "0")}</div>
          </div>
          <div class="kpi-mini-cell">
            <div class="kpi-mini-label">${LH("Reclaimable")}</div>
            <div class="kpi-mini-val">${escapeHtml(res.reclaimable_packages || "0")} packages</div>
          </div>
          <div class="kpi-mini-cell">
            <div class="kpi-mini-label">${LH("Cleanup Needed")}</div>
            <div class="kpi-mini-val">${res.cleanup_recommended ? `<span class="badge badge-warn">${LH("Recommended")}</span>` : `<span class="badge badge-good">${LH("Optimal")}</span>`}</div>
          </div>
        </div>`;
    } finally {
      analyzeBtn.disabled = false;
      if (cleanBtn) cleanBtn.disabled = false;
    }
  });

  cleanBtn?.addEventListener("click", async () => {
    if (!outBox) return;
    analyzeBtn && (analyzeBtn.disabled = true);
    cleanBtn.disabled = true;
    outBox.classList.remove("hidden");
    outBox.innerHTML = `<div class="muted">${LH("Running DISM /StartComponentCleanup (keep DriveSweep open until Windows finishes)...")}</div>`;
    try {
      const res = await api().run_winsxs_cleanup();
      if (res.ok) {
        if (res.drives_after) renderDrives(res.drives_after);
        if (typeof res.history_count === "number") updateHeaderCounts(undefined, res.history_count);
        outBox.innerHTML = `<div class="accent-good" style="font-weight:600;">${LH("WinSxS component cleanup finished cleanly and was recorded in Cleanup Log.")}</div>`;
        showToast(L("WinSxS component cleanup finished"), "good");
      } else {
        outBox.textContent = res.error || "WinSxS cleanup failed.";
      }
    } finally {
      analyzeBtn && (analyzeBtn.disabled = false);
      cleanBtn.disabled = false;
    }
  });
}

function renderWindowsToolsView() {
  const host = document.getElementById("windows-content");
  if (!host) return;
  if (!state.windowsData) {
    host.innerHTML = `<div class="progress-card"><div class="muted">${LH("Inspecting Windows Recycle Bin, Downloads installers, WinSxS, hibernation, and virtual disks...")}</div></div>`;
    return;
  }
  host.innerHTML = buildWindowsToolsHtml(state.windowsData, true);
  bindWindowsToolsEvents(state.windowsData, { inModal: false });
}

async function loadWindowsToolsView(force = false) {
  const host = document.getElementById("windows-content");
  if (!host) return;
  if (force || !state.windowsData) {
    host.innerHTML = `<div class="progress-card"><div class="muted">${LH("Inspecting Windows Recycle Bin, Downloads installers, WinSxS, hibernation, and virtual disks...")}</div></div>`;
  }
  const btn = document.getElementById("btn-windows-refresh");
  if (btn) btn.disabled = true;
  try {
    state.windowsData = await api().inspect_system_space(Number(state.windowsAgeDays || 30));
    renderWindowsToolsView();
  } catch (err) {
    host.innerHTML = `<div class="warning-box">${escapeHtml(String(err))}</div>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openSystemToolsModal() {
  showModal(
    L("Windows Space & System Tools"),
    `<div class="muted">${LH("Checking Recycle Bin, old Download installers, hibernation, and virtual disks...")}</div>`,
    [{ text: L("Close"), cls: "btn-primary", onClick: closeModal }]
  );

  let data;
  try {
    data = await api().inspect_system_space(Number(state.windowsAgeDays || 30));
    state.windowsData = data;
  } catch (err) {
    showModal(
      L("Windows Space & System Tools"),
      `<div class="warning-box">${escapeHtml(String(err))}</div>`,
      [{ text: L("Close"), cls: "btn-primary", onClick: closeModal }]
    );
    return;
  }

  showModal(
    L("Windows Space & System Tools"),
    buildWindowsToolsHtml(data, false),
    [{ text: L("Close"), cls: "btn-primary", onClick: closeModal }]
  );
  bindWindowsToolsEvents(data, { inModal: true });
}

/* ==================== TAB 1: SMART CACHE SCAN ==================== */

async function loadSmartScan() {
  const rescanBtn = document.getElementById("btn-smart-scan");
  if (rescanBtn) {
    rescanBtn.disabled = true;
    rescanBtn.textContent = L("Scanning...");
  }
  document.getElementById("smart-count-sub").textContent = L("Scanning locations...");
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
    document.getElementById("smart-count-sub").textContent = L("{count} cleanup items found", { count: res.count });
    document.getElementById("nav-smart-badge").textContent = res.total_human;

    renderSmartBreakdown(res.total_human);
    renderSmartGroups();
    updateDriveHealthPill();
  } catch (err) {
    document.getElementById("smart-count-sub").textContent = L("Scan failed: {error}", { error: String(err) });
  } finally {
    if (rescanBtn) {
      rescanBtn.disabled = false;
      rescanBtn.textContent = L("Re-scan");
    }
  }
}

function toggleCategoryFilter(groupName) {
  state.activeCategoryFilter = state.activeCategoryFilter === groupName ? null : groupName;
  if (state.activeCategoryFilter) {
    state.collapsedGroups.delete(state.activeCategoryFilter);
  }
  renderSmartBreakdown(document.getElementById("smart-total-metric")?.textContent || "0 B");
  renderSmartGroups();
}

function renderSmartBreakdown(totalHuman) {
  const barEl = document.getElementById("smart-breakdown-bar");
  const donutEl = document.getElementById("smart-donut-wrap");
  const hintEl = document.getElementById("smart-cat-hint");

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
    donutEl.innerHTML = `<span class="muted small-text">${LH("No caches to visualize.")}</span>`;
    return;
  }

  const sorted = Array.from(totals.entries()).sort((a, b) => b[1] - a[1]);
  barEl.innerHTML = sorted
    .map(([grp, bytes]) => {
      const pct = Math.max(1.5, (bytes / grandTotal) * 100);
      const color = GROUP_COLORS[grp] || "#64748b";
      return `<div class="breakdown-seg" data-cat="${escapeHtml(grp)}" style="width:${pct}%;background:${color};" title="${LH(grp)}: ${formatBytes(bytes)}"></div>`;
    })
    .join("");

  barEl.querySelectorAll(".breakdown-seg").forEach((seg) => {
    seg.addEventListener("click", () => toggleCategoryFilter(seg.dataset.cat));
  });

  if (hintEl) {
    hintEl.textContent = state.activeCategoryFilter
      ? L("Filtered: {category} (click to clear)", { category: L(state.activeCategoryFilter) })
      : L("Click a category to filter");
  }

  const donutSegs = sorted.map(([grp, bytes]) => ({
    label: L(grp),
    rawCategory: grp,
    value: bytes,
    valueLabel: formatBytes(bytes),
    color: GROUP_COLORS[grp] || "#64748b",
  }));
  donutEl.innerHTML = buildSvgDonut(
    donutSegs,
    totalHuman || formatBytes(grandTotal),
    L("Total Found"),
    state.activeCategoryFilter,
    true
  );

  donutEl.querySelectorAll(".donut-list-row[data-cat]").forEach((row) => {
    row.addEventListener("click", () => toggleCategoryFilter(row.dataset.cat));
  });
}

function renderPrivilegeLabels() {
  const title = document.getElementById("priv-title");
  const sub = document.getElementById("priv-sub");
  if (!title || !sub) return;
  title.textContent = state.isAdmin ? L("Administrator") : L("Standard Mode");
  title.classList.toggle("accent-good", !!state.isAdmin);
  sub.textContent = state.isAdmin ? L("Full drive & system temp access") : L("Safe user-level access");
}

function updateCollapseToggleBtn() {
  const btn = document.getElementById("btn-smart-collapse-toggle");
  if (!btn) return;
  const visibleGroups = Array.from(document.querySelectorAll(".group-card[data-group]")).map((el) => el.dataset.group);
  const allCollapsed = visibleGroups.length > 0 && visibleGroups.every((g) => state.collapsedGroups.has(g));
  btn.textContent = allCollapsed ? L("Expand All") : L("Collapse All");
}

function renderSmartGroups() {
  const filter = (document.getElementById("smart-filter").value || "").trim().toLowerCase();
  const container = document.getElementById("smart-groups");

  const filtered = state.smartItems.filter(
    (item) =>
      (!state.activeCategoryFilter || item.group === state.activeCategoryFilter) &&
      (!filter ||
        item.label.toLowerCase().includes(filter) ||
        L(item.label).toLowerCase().includes(filter) ||
        item.path.toLowerCase().includes(filter) ||
        item.group.toLowerCase().includes(filter))
  );

  if (filtered.length === 0) {
    container.innerHTML = `<div class="summary-strip">${LH("No matching caches found.")}</div>`;
    updateCollapseToggleBtn();
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
    const selectedCount = items.filter((it) => !isPathExcludedLocal(it.path) && isItemSelected(it.path, !!it.contents_only)).length;
    const color = GROUP_COLORS[groupName] || "#64748b";
    const card = document.createElement("div");
    card.className = `group-card ${state.collapsedGroups.has(groupName) ? "collapsed" : ""}`;
    card.dataset.group = groupName;

    const header = document.createElement("div");
    header.className = "group-header";
    header.innerHTML = `
      <div class="group-title-wrap">
        ${ICON_CHEVRON}
        <span class="legend-dot" style="background:${color};"></span>
        <span>${LH(groupName)}</span>
        <span class="ver-chip">${items.length}</span>
      </div>
      <div class="group-header-right">
        <span class="group-selected-chip">${LH("{done}/{total} selected", { done: selectedCount, total: items.length })}</span>
        <span class="size-pill">${formatBytes(groupBytes)}</span>
      </div>
    `;
    header.addEventListener("click", () => {
      if (state.collapsedGroups.has(groupName)) {
        state.collapsedGroups.delete(groupName);
      } else {
        state.collapsedGroups.add(groupName);
      }
      card.classList.toggle("collapsed");
      updateCollapseToggleBtn();
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
        <label class="toggle-switch" title="${LH("Toggle clean or keep")}">
          <input type="checkbox" ${checked ? "checked" : ""} ${excluded ? "disabled" : ""} />
          <span class="toggle-slider"></span>
        </label>
        <div class="preset-main">
          <div class="preset-title-line">
            <span class="preset-title">${LH(item.label)}</span>
            ${renderRiskBadge(item.risk_level || "safe", item.risk_reason || item.safety_note)}
            ${item.running_app ? `<span class="badge badge-warn">${LH("{app} running", { app: escapeHtml(item.running_app) })}</span>` : ""}
            ${excluded ? `<span class="badge badge-info">${LH("Always Keep")}</span>` : ""}
          </div>
          <div class="preset-path" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}</div>
          <div class="preset-note">${LH(item.safety_note || "")}</div>
        </div>
        <div class="preset-right">
          <div class="row-hover-actions">
            ${item.is_custom ? `<button class="btn btn-soft btn-xs btn-remove-custom" data-id="${escapeHtml(item.id)}">${escapeHtml(tr("remove", "Remove"))}</button>` : ""}
            ${item.is_docker_prune ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? escapeHtml(tr("allow", "Allow")) : escapeHtml(tr("keep", "Keep"))}</button>`}
            ${item.is_docker_prune ? "" : `<button class="btn btn-soft btn-xs btn-open">${escapeHtml(tr("open_folder", "Open Folder"))}</button>`}
          </div>
          <span class="muted small-text row-file-count">${item.file_count ? LH("{count} files", { count: item.file_count.toLocaleString() }) : "-"}</span>
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

      const remCustomBtn = row.querySelector(".btn-remove-custom");
      if (remCustomBtn) {
        remCustomBtn.addEventListener("click", async () => {
          await api().remove_custom_preset(remCustomBtn.dataset.id);
          await loadSmartScan();
        });
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

  stats.textContent = L("{files} files | {folders} folders | {size} ({secs}s)", { files: st.files_scanned.toLocaleString(), folders: st.dirs_scanned.toLocaleString(), size: st.bytes_human, secs: st.elapsed_sec });
  curPath.textContent = st.current_path || "";

  if (st.status === "scanning") {
    label.textContent = L("Scanning {path}...", { path: st.root_path });
    return;
  }

  clearInterval(state.scanTimer);
  state.scanTimer = null;
  document.getElementById("btn-cancel-scan").classList.add("hidden");

  if (st.status === "error") {
    label.textContent = L("Scan error: {error}", { error: st.error });
    return;
  }

  document.getElementById("scan-progress").classList.add("hidden");
  document.getElementById("explorer-workspace").classList.remove("hidden");
  const prefix = st.cached ? `${L("Cached")} \u00b7 ` : "";
  document.getElementById("explorer-summary-pill").textContent =
    `${prefix}${L("{count} files", { count: st.files_scanned.toLocaleString() })} \u00b7 ${st.bytes_human} \u00b7 ${st.elapsed_sec}s` +
    (st.skipped_count ? ` \u00b7 ${L("{count} locked skipped", { count: st.skipped_count })}` : "");
  const engineBadge = document.getElementById("scan-engine-badge");
  if (engineBadge) {
    engineBadge.classList.remove("hidden");
    engineBadge.textContent = st.scan_engine === "ntfs_mft" ? "NTFS MFT" : L("Standard Scan");
  }
  document.getElementById("export-menu-wrap")?.classList.remove("hidden");
  document.getElementById("btn-explorer-rescan").classList.remove("hidden");

  state.treemapPath = st.root_path;
  state.dupResult = null;
  document.getElementById("dup-groups").innerHTML = "";
  document.getElementById("btn-dup-select-extra")?.classList.add("hidden");

  state.browseState.path = st.root_path;
  state.browseState.offset = 0;
  await Promise.all([loadAnalytics(), loadBrowseFolder(), loadAllFiles(), loadLargestFiles(), loadDevArtifacts()]);
}

const SPACE_PALETTE = [
  "#3b82f6",
  "#8b5cf6",
  "#14b8a6",
  "#f59e0b",
  "#ec4899",
  "#06b6d4",
  "#6366f1",
  "#10b981",
];

async function loadTreemap(targetPath) {
  const data = await api().get_treemap_data(targetPath || state.treemapPath || state.browseState.path);
  state.treemapPath = data.current_path;
  const controlsEl = document.getElementById("treemap-controls");
  const canvasEl = document.getElementById("treemap-grid");
  if (!controlsEl || !canvasEl) return;

  const crumbs = data.breadcrumbs || [];
  const parentPath = crumbs.length > 1 ? crumbs[crumbs.length - 2].path : null;
  const crumbsHtml = crumbs
    .map((c, idx) => `<button class="crumb-btn tm-crumb" data-path="${escapeHtml(c.path)}">${idx === 0 ? "Root" : escapeHtml(c.name)}</button>`)
    .join(`<span class="muted">/</span>`);

  controlsEl.innerHTML = `
    <div class="breadcrumbs">${crumbsHtml}</div>
    <div style="display:flex;gap:6px;align-items:center;">
      <span class="muted small-text">${escapeHtml(data.total_human || "0 B")}</span>
      <button id="btn-treemap-up" class="btn btn-ghost btn-xs" ${parentPath ? "" : "disabled"}>${escapeHtml(tr("treemap_up", "Up One Level"))}</button>
      <button id="btn-treemap-browse" class="btn btn-ghost btn-xs">${escapeHtml(tr("treemap_open_folders", "Open in Folders"))}</button>
    </div>
  `;

  controlsEl.querySelectorAll(".tm-crumb").forEach((b) => {
    b.addEventListener("click", () => loadTreemap(b.dataset.path));
  });
  if (parentPath) {
    document.getElementById("btn-treemap-up")?.addEventListener("click", () => loadTreemap(parentPath));
  }
  document.getElementById("btn-treemap-browse")?.addEventListener("click", () => {
    state.browseState.path = data.current_path;
    state.browseState.offset = 0;
    switchExplorerSubView("browse");
    loadBrowseFolder();
  });

  const allItems = (data.items || []).filter((it) => Number(it.size_bytes || 0) > 0);
  if (!allItems.length) {
    canvasEl.innerHTML = `<div class="muted small-text" style="padding:18px;">${LH("No sized items in this folder.")}</div>`;
    return;
  }

  const totalBytes = Math.max(1, allItems.reduce((s, it) => s + Number(it.size_bytes || 0), 0));
  const maxRows = 7;
  const shown = allItems.slice(0, maxRows);
  const rest = allItems.slice(maxRows);
  const restBytes = rest.reduce((s, it) => s + Number(it.size_bytes || 0), 0);
  const restPct = Math.round((restBytes / totalBytes) * 1000) / 10;

  // Segmented pill bar: show major slices clearly and group tiny slivers cleanly
  const segItems = [];
  let minorBytes = restBytes;
  shown.forEach((it, idx) => {
    const pct = (Number(it.size_bytes || 0) / totalBytes) * 100;
    if (pct >= 1.0 || idx === 0) {
      segItems.push({
        item: it,
        color: SPACE_PALETTE[idx % SPACE_PALETTE.length],
        pct: Math.max(pct, 1.2),
      });
    } else {
      minorBytes += Number(it.size_bytes || 0);
    }
  });

  const minorPct = (minorBytes / totalBytes) * 100;
  const segHtml = [
    ...segItems.map((seg) => {
      const drill = seg.item.kind === "dir" && seg.item.has_children;
      return `
        <button class="space-seg" type="button"
          data-kind="${escapeHtml(seg.item.kind)}"
          data-path="${escapeHtml(seg.item.path)}"
          data-drill="${drill ? "1" : "0"}"
          title="${escapeHtml(seg.item.name)} | ${escapeHtml(seg.item.size_human)} (${seg.item.percent}%)"
          style="flex:${seg.pct.toFixed(2)} 1 0%;background:${seg.color};"></button>
      `;
    }),
    minorBytes > 0
      ? `<div class="space-seg" style="flex:${Math.max(minorPct, 1.2).toFixed(2)} 1 0%;background:#64748b;opacity:0.55;cursor:default;" title="${LH("Other smaller items")} | ${escapeHtml(formatBytes(minorBytes))}"></div>`
      : "",
  ].join("");

  const rowsHtml = shown
    .map((item, idx) => {
      const color = SPACE_PALETTE[idx % SPACE_PALETTE.length];
      const drill = item.kind === "dir" && item.has_children;
      const pctNum = Math.min(100, Math.max(0, Number(item.percent || 0)));
      const iconHtml = item.kind === "dir" ? ICON_FOLDER : ICON_FILE;
      const lockBadge = item.risk_level === "critical" ? `<span class="space-map-lock">${LH("System")}</span>` : "";
      return `
        <button class="space-map-row" type="button"
          data-kind="${escapeHtml(item.kind)}"
          data-path="${escapeHtml(item.path)}"
          data-drill="${drill ? "1" : "0"}"
          title="${escapeHtml(item.path)}">
          <div class="space-map-label">
            <span class="space-map-dot" style="background:${color};"></span>
            ${iconHtml}
            <span class="space-map-name">${escapeHtml(item.name)}</span>
            ${lockBadge}
          </div>
          <div class="space-map-bar-wrap">
            <div class="space-map-bar-fill" style="width:${Math.max(2, pctNum)}%;background:${color};"></div>
          </div>
          <div class="space-map-right">
            <strong>${escapeHtml(item.size_human)}</strong>
            <span class="muted">${pctNum}%</span>
            ${drill ? `<span class="space-map-chev">&#8250;</span>` : ""}
          </div>
        </button>
      `;
    })
    .join("");

  const summaryHtml = rest.length > 0
    ? `<div class="space-map-row is-summary">
         <div class="space-map-label">
           <span class="space-map-dot" style="background:#64748b;"></span>
           <span class="space-map-name">${rest.length === 1 ? LH("1 smaller item") : LH("{count} smaller items", { count: rest.length })}</span>
         </div>
         <div class="space-map-bar-wrap">
           <div class="space-map-bar-fill" style="width:${Math.max(2, restPct)}%;background:#64748b;opacity:0.6;"></div>
         </div>
         <div class="space-map-right">
           <strong>${escapeHtml(formatBytes(restBytes))}</strong>
           <span class="muted">${restPct}%</span>
         </div>
       </div>`
    : "";

  canvasEl.innerHTML = `
    <div class="space-seg-bar">${segHtml}</div>
    <div class="space-map-list">${rowsHtml}${summaryHtml}</div>
  `;

  canvasEl.querySelectorAll(".space-seg[data-path], .space-map-row[data-path]").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.dataset.drill === "1") {
        loadTreemap(el.dataset.path);
      } else {
        state.browseState.path = el.dataset.path;
        state.browseState.offset = 0;
        switchExplorerSubView("browse");
        loadBrowseFolder();
      }
    });
  });
}

async function loadAnalytics() {
  const data = await api().get_drive_analytics(state.browseState.path);
  const risk = data.risk_summary || {};
  const crit = risk.critical || { size_human: "0 B", file_count: 0, percent: 0 };
  const caut = risk.caution || { size_human: "0 B", file_count: 0, percent: 0 };
  const safe = risk.safe || { size_human: "0 B", file_count: 0, percent: 0 };

  document.getElementById("risk-cards-row").innerHTML = `
    <div class="risk-quiet-bar">
      <div class="risk-quiet-item" title="${LH("Windows and program files locked so they cannot be deleted by mistake.")}">
        <span class="risk-dot risk-dot-critical"></span>
        <span>${escapeHtml(tr("risk_sys_title", "System Files (Locked)"))}:</span>
        <strong>${escapeHtml(crit.size_human)}</strong>
        <span class="muted">(${crit.percent}% &middot; ${LH("{count} locked", { count: crit.file_count.toLocaleString() })})</span>
      </div>
      <span class="risk-quiet-sep" aria-hidden="true">&middot;</span>
      <div class="risk-quiet-item" title="${LH("Personal, database, app, or project files. DriveSweep asks before cleaning.")}">
        <span class="risk-dot risk-dot-caution"></span>
        <span>${escapeHtml(tr("risk_imp_title", "Important Files (Review First)"))}:</span>
        <strong>${escapeHtml(caut.size_human)}</strong>
        <span class="muted">(${caut.percent}%)</span>
      </div>
      <span class="risk-quiet-sep" aria-hidden="true">&middot;</span>
      <div class="risk-quiet-item" title="${LH("Regular files and temporary caches you can safely review or remove.")}">
        <span class="risk-dot risk-dot-safe"></span>
        <span>${escapeHtml(tr("risk_std_title", "Standard Files"))}:</span>
        <strong>${escapeHtml(safe.size_human)}</strong>
        <span class="muted">(${safe.percent}%)</span>
      </div>
    </div>
  `;

  // Interactive Proportional Zoomable Treemap
  await loadTreemap(state.treemapPath || state.browseState.path);

  // Category Donut Chart (click any category to drill down into Find Any File)
  const catSegs = (data.by_category || []).map((c) => ({
    label: `${L(c.name)} (${c.percent}%)`,
    rawCategory: c.name,
    value: c.size_bytes,
    valueLabel: c.size_human,
    color: c.color,
  }));
  const catWrap = document.getElementById("category-chart-wrap");
  catWrap.innerHTML = buildSvgDonut(
    catSegs,
    data.total_human || "0 B",
    "Total",
    null,
    true
  );
  catWrap.querySelectorAll(".donut-list-row[data-cat]").forEach((row) => {
    row.addEventListener("click", () => {
      const cat = row.dataset.cat || "";
      state.allFilesState.query = "";
      state.allFilesState.ext = "";
      state.allFilesState.minMb = 0;
      state.allFilesState.minAgeDays = 0;
      state.allFilesState.category = cat;
      state.allFilesState.offset = 0;
      const qEl = document.getElementById("allfiles-query");
      const extEl = document.getElementById("allfiles-ext");
      const minMbEl = document.getElementById("allfiles-minmb");
      const ageEl = document.getElementById("allfiles-age");
      const catEl = document.getElementById("allfiles-category");
      if (qEl) qEl.value = "";
      if (extEl) extEl.value = "";
      if (minMbEl) minMbEl.value = "";
      if (ageEl) ageEl.value = "0";
      if (catEl) catEl.value = cat;
      switchExplorerSubView("allfiles");
      loadAllFiles();
    });
  });

  // Age Bar Chart (click any age bar to drill down into Find Any File)
  const ageList = data.by_age || [];
  const maxAgeBytes = Math.max(1, ...ageList.map((a) => Number(a.size_bytes || 0)));
  const ageMinDaysForLabel = (name) => {
    const s = String(name || "").toLowerCase();
    if (s.includes("year")) return 365;
    if (s.includes("90 to")) return 90;
    if (s.includes("30 to")) return 30;
    return 0;
  };
  const ageWrap = document.getElementById("age-chart-wrap");
  ageWrap.innerHTML = ageList
    .map((a) => {
      const w = Math.min(100, (Number(a.size_bytes || 0) / maxAgeBytes) * 100);
      const minAge = ageMinDaysForLabel(a.name);
      return `
        <div class="bar-row is-clickable" data-min-age="${minAge}" title="${LH("Click to browse files in this age bracket")}">
          <div class="bar-row-top">
            <span><strong>${LH(a.name)}</strong> <span class="muted">(${LH("{count} files", { count: a.file_count.toLocaleString() })})</span></span>
            <span><strong>${escapeHtml(a.size_human)}</strong> <span class="muted">(${a.percent}%)</span></span>
          </div>
          <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${a.color};"></div></div>
        </div>`;
    })
    .join("");
  ageWrap.querySelectorAll(".bar-row[data-min-age]").forEach((row) => {
    row.addEventListener("click", () => {
      const minAge = Number(row.dataset.minAge || 0);
      state.allFilesState.query = "";
      state.allFilesState.ext = "";
      state.allFilesState.minMb = 0;
      state.allFilesState.category = "";
      state.allFilesState.minAgeDays = minAge;
      state.allFilesState.offset = 0;
      const qEl = document.getElementById("allfiles-query");
      const extEl = document.getElementById("allfiles-ext");
      const minMbEl = document.getElementById("allfiles-minmb");
      const catEl = document.getElementById("allfiles-category");
      const ageEl = document.getElementById("allfiles-age");
      if (qEl) qEl.value = "";
      if (extEl) extEl.value = "";
      if (minMbEl) minMbEl.value = "";
      if (catEl) catEl.value = "";
      if (ageEl) ageEl.value = String(minAge);
      switchExplorerSubView("allfiles");
      loadAllFiles();
    });
  });

  // Simple Summary Table
  const topFolders = data.top_folders || [];
  const tableEl = document.getElementById("top-folders-table-wrap");
  if (topFolders.length === 0) {
    tableEl.innerHTML = `<div class="muted small-text">${LH("No folders to summarize.")}</div>`;
  } else {
    tableEl.innerHTML = `
      <table class="mini-table">
        <thead>
          <tr><th>${LH("Folder")}</th><th>${LH("Safety")}</th><th>${LH("Files")}</th><th>${LH("Size")}</th></tr>
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
      excluded ? `<span class="badge badge-info">${LH("Always Keep")}</span>` : "",
      item.is_dev_bloat ? `<span class="badge badge-info">${LH("Project Cache")}</span>` : "",
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
          ${item.risk_reason ? `<div class="item-human-hint">${escapeHtml(item.risk_reason)}</div>` : ""}
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
          <button class="btn btn-soft btn-xs btn-open">${LH("Open Folder")}</button>
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
  const res = await api().search_all_files(a.query, a.minMb, a.minAgeDays, a.ext, a.sort, a.offset, a.limit, a.category || "");
  document.getElementById("allfiles-meta").textContent =
    L("{count} files matched ({size})", { count: res.total_matches.toLocaleString(), size: res.total_matched_human });

  renderFileRows(document.getElementById("allfiles-tbody"), res.items || []);
  renderPager("allfiles-pager", res.total_matches, a.offset, a.limit, (newOffset) => {
    state.allFilesState.offset = newOffset;
    loadAllFiles();
  });
}

async function loadLargeSpaces(force = false) {
  const metaEl = document.getElementById("large-meta");
  const tbody = document.getElementById("large-tbody");
  if (!metaEl || !tbody) return;
  if (!force && state.largeData !== null) {
    renderLargeSpacesTable();
    return;
  }
  metaEl.textContent = L("Scanning Downloads, user spaces, and all drives...");
  tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:28px;">${LH("Scanning large files and folders...")}</td></tr>`;
  try {
    const res = await api().scan_large_spaces(25.0, 100.0);
    state.largeData = res || { files: [], folders: [], spaces: [] };
    populateLargeSpacesDropdown(state.largeData.spaces || []);
    renderLargeSpacesTable();
  } catch (err) {
    state.largeData = { files: [], folders: [], spaces: [] };
    metaEl.textContent = L("Could not complete large item scan.");
    tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:28px;">${escapeHtml(err?.message || String(err))}</td></tr>`;
  }
}

function populateLargeSpacesDropdown(spaces) {
  const sel = document.getElementById("large-space-filter");
  if (!sel) return;
  const prev = sel.value || "";
  sel.innerHTML = `<option value="">${LH("All Spaces & Drives")}</option>`;
  for (const sp of spaces || []) {
    const opt = document.createElement("option");
    opt.value = sp;
    opt.textContent = sp;
    sel.appendChild(opt);
  }
  if (prev && (spaces || []).includes(prev)) {
    sel.value = prev;
  }
}

function renderLargeSpacesTable() {
  const metaEl = document.getElementById("large-meta");
  const tbody = document.getElementById("large-tbody");
  if (!metaEl || !tbody) return;
  const data = state.largeData || { files: [], folders: [] };
  const isFolders = state.largeMode === "folders";
  const rawList = isFolders ? (data.folders || []) : (data.files || []);
  const spaceFilter = document.getElementById("large-space-filter")?.value || "";
  const minMb = Number(document.getElementById("large-min-mb")?.value || 0);
  const query = (document.getElementById("large-filter")?.value || "").trim().toLowerCase();
  const minBytes = minMb * 1024 * 1024;

  const filtered = rawList.filter((item) => {
    if (spaceFilter && item.space !== spaceFilter) return false;
    if (Number(item.size_bytes || 0) < minBytes) return false;
    if (query) {
      const hay = `${item.name || ""} ${item.path || ""} ${item.space || ""}`.toLowerCase();
      if (!hay.includes(query)) return false;
    }
    return true;
  });

  const totalBytes = filtered.reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
  const countLabel = isFolders
    ? (filtered.length === 1 ? L("1 large folder") : L("{count} large folders", { count: filtered.length }))
    : (filtered.length === 1 ? L("1 large file") : L("{count} large files", { count: filtered.length }));
  metaEl.textContent = `${countLabel} (${formatBytes(totalBytes)}) | ${L("Nothing auto-selected")}`;

  tbody.innerHTML = "";
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:28px;">${isFolders ? LH("No matching folders above {mb} MB. Try lowering the size filter or rescanning.", { mb: minMb }) : LH("No matching files above {mb} MB. Try lowering the size filter or rescanning.", { mb: minMb })}</td></tr>`;
    return;
  }

  const maxBytes = Math.max(1, ...filtered.map((it) => Number(it.size_bytes || 0)));
  for (const item of filtered) {
    const tr = document.createElement("tr");
    const excluded = isPathExcludedLocal(item.path);
    const disabled = !!item.is_protected || excluded;
    const checked = !disabled && isItemSelected(item.path, false);
    const pct = Math.min(100, (Number(item.size_bytes || 0) / maxBytes) * 100);
    const fileCountHint = isFolders && item.file_count ? ` | ${L("{count} files", { count: Number(item.file_count).toLocaleString() })}` : "";

    tr.innerHTML = `
      <td class="col-check">
        <input class="chk-box" type="checkbox" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
      </td>
      <td>
        <div class="item-name-line">
          ${isFolders ? ICON_FOLDER : ICON_FILE}
          <strong>${escapeHtml(item.name)}</strong>
          ${excluded ? `<span class="badge badge-info">${LH("Always Keep")}</span>` : ""}
        </div>
        ${item.risk_reason ? `<div class="item-human-hint">${escapeHtml(item.risk_reason)}</div>` : ""}
        <div class="item-subpath" title="${escapeHtml(item.path)}">${escapeHtml(item.path)}${escapeHtml(fileCountHint)}</div>
        <div class="inline-bar-track"><div class="inline-bar-fill" style="width:${pct}%"></div></div>
      </td>
      <td class="col-risk"><span class="badge badge-info">${escapeHtml(item.space || "PC")}</span></td>
      <td class="col-risk">${renderRiskBadge(item.risk_level || (item.is_protected ? "critical" : "caution"), item.risk_reason)}</td>
      <td class="col-date">${escapeHtml(formatModified(item.mtime_str, item.age_days))}</td>
      <td class="col-size">${escapeHtml(item.size_human)}</td>
      <td class="col-actions">
        <div class="row-actions">
          ${item.is_protected ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>`}
          <button class="btn btn-soft btn-xs btn-open">${LH("Open Folder")}</button>
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
            risk_level: item.risk_level || "caution",
            risk_reason: item.risk_reason || "",
            source: "large",
          },
          cb.checked
        );
      });
    }
    tr.querySelector(".btn-keep-toggle")?.addEventListener("click", () => toggleAlwaysKeep(item.path));
    tr.querySelector(".btn-open")?.addEventListener("click", () => api().open_in_explorer(item.path));
    tbody.appendChild(tr);
  }
}

async function loadLargestFiles() {
  const isFolders = state.largestMode === "folders";
  const items = isFolders
    ? await api().get_largest_folders(200, 25.0)
    : await api().get_largest_files(200);
  const list = items || [];
  const metaEl = document.getElementById("largest-meta");
  if (metaEl) {
    const totalBytes = list.reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
    metaEl.textContent = `${isFolders ? L("{count} largest folders", { count: list.length }) : L("{count} largest files", { count: list.length })} (${formatBytes(totalBytes)})`;
  }
  const tbody = document.getElementById("largest-tbody");
  if (!tbody) return;
  if (isFolders) {
    renderExplorerFolderRows(tbody, list);
  } else {
    renderFileRows(tbody, list);
  }
}

function renderExplorerFolderRows(tbody, items) {
  tbody.innerHTML = "";
  const maxBytes = Math.max(1, ...items.map((it) => Number(it.size_bytes || 0)));
  for (const item of items) {
    const tr = document.createElement("tr");
    const excluded = isPathExcludedLocal(item.path);
    const disabled = item.is_protected || excluded;
    const checked = !disabled && isItemSelected(item.path, false);
    const pct = Math.min(100, (Number(item.size_bytes || 0) / maxBytes) * 100);
    const fileCountHint = item.file_count ? ` | ${L("{count} files", { count: Number(item.file_count).toLocaleString() })}` : "";

    tr.innerHTML = `
      <td class="col-check">
        <input class="chk-box" type="checkbox" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
      </td>
      <td>
        <div class="item-name-line">
          ${ICON_FOLDER}
          <strong>${escapeHtml(item.name)}</strong>
          ${excluded ? `<span class="badge badge-info">${LH("Always Keep")}</span>` : ""}
        </div>
        ${item.risk_reason ? `<div class="item-human-hint">${escapeHtml(item.risk_reason)}</div>` : ""}
        <div class="item-subpath">${escapeHtml(item.path)}${escapeHtml(fileCountHint)}</div>
        <div class="inline-bar-track"><div class="inline-bar-fill" style="width:${pct}%"></div></div>
      </td>
      <td class="col-risk">${renderRiskBadge(item.risk_level || (item.is_protected ? "critical" : "caution"), item.risk_reason)}</td>
      <td class="col-date">${escapeHtml(formatModified(item.mtime_str, item.age_days))}</td>
      <td class="col-size">${escapeHtml(item.size_human)}</td>
      <td class="col-actions">
        <div class="row-actions">
          ${item.is_protected ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>`}
          <button class="btn btn-soft btn-xs btn-open">${LH("Open Folder")}</button>
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
            risk_level: item.risk_level || "caution",
            risk_reason: item.risk_reason || "",
            source: "explorer",
          },
          cb.checked
        );
      });
    }
    tr.querySelector(".btn-keep-toggle")?.addEventListener("click", () => toggleAlwaysKeep(item.path));
    tr.querySelector(".btn-open")?.addEventListener("click", () => api().open_in_explorer(item.path));
    tbody.appendChild(tr);
  }
}

async function loadDevArtifacts() {
  state.devBloatItems = (await api().get_dev_artifacts(250, state.devBloatMinAgeDays)) || [];
  renderDevArtifacts();
}

function renderDevArtifacts() {
  const q = (state.devBloatQuery || "").trim().toLowerCase();
  const items = (state.devBloatItems || []).filter((item) => {
    if (!q) return true;
    const hay = `${item.name || ""} ${item.parent_name || ""} ${item.path || ""}`.toLowerCase();
    return hay.includes(q);
  });
  const totalBytes = items.reduce((acc, i) => acc + Number(i.size_bytes || 0), 0);
  document.getElementById("devbloat-meta").textContent =
    L("{count} project cache folder(s) | {size}", { count: items.length, size: formatBytes(totalBytes) });

  const maxBytes = Math.max(1, ...items.map((it) => Number(it.size_bytes || 0)));
  const tbody = document.getElementById("devbloat-tbody");
  tbody.innerHTML = "";

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
          ${ICON_FOLDER}
          <strong>${escapeHtml(item.name)}</strong>
          <span class="muted">in ${escapeHtml(item.parent_name)}</span>
          ${excluded ? `<span class="badge badge-info">${LH("Always Keep")}</span>` : ""}
        </div>
        ${item.risk_reason ? `<div class="item-human-hint">${escapeHtml(item.risk_reason)}</div>` : ""}
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
          <button class="btn btn-soft btn-xs btn-open">${LH("Open Folder")}</button>
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

function selectInactiveDevArtifacts(minAgeDays = 30) {
  let added = 0;
  const q = (state.devBloatQuery || "").trim().toLowerCase();
  for (const item of state.devBloatItems || []) {
    if (item.is_protected || isPathExcludedLocal(item.path)) continue;
    if (Number(item.age_days || 0) < minAgeDays) continue;
    if (q) {
      const hay = `${item.name || ""} ${item.parent_name || ""} ${item.path || ""}`.toLowerCase();
      if (!hay.includes(q)) continue;
    }
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
      true
    );
    added += 1;
  }
  renderDevArtifacts();
  showToast(
    added > 0 ? L("Selected {count} inactive project cache(s) (older than {days} days)", { count: added, days: minAgeDays }) : L("No inactive caches older than {days} days found", { days: minAgeDays }),
    added > 0 ? "good" : "info"
  );
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
          ${excluded ? `<span class="badge badge-info">${LH("Always Keep")}</span>` : ""}
        </div>
        ${item.risk_reason ? `<div class="item-human-hint">${escapeHtml(item.risk_reason)}</div>` : ""}
        <div class="item-subpath">${escapeHtml(item.dir_path || item.path)}</div>
        <div class="inline-bar-track"><div class="inline-bar-fill" style="width:${pct}%"></div></div>
      </td>
      <td class="col-risk">${renderRiskBadge(item.risk_level || (item.is_protected ? "critical" : "safe"), item.risk_reason)}</td>
      <td class="col-date">${escapeHtml(formatModified(item.mtime_str, item.age_days))}</td>
      <td class="col-size">${escapeHtml(item.size_human)}</td>
      <td class="col-actions">
        <div class="row-actions">
          ${item.is_protected ? "" : `<button class="btn btn-soft btn-xs btn-keep-toggle">${excluded ? "Allow" : "Keep"}</button>`}
          <button class="btn btn-soft btn-xs btn-open">${LH("Open Folder")}</button>
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
    el.innerHTML = `<span>${total === 1 ? LH("Showing 1 item") : LH("Showing {count} items", { count: total })}</span><span></span>`;
    return;
  }
  const start = offset + 1;
  const end = Math.min(total, offset + limit);
  el.innerHTML = `
    <span>${LH("Showing {start} to {end} of {total}", { start: start.toLocaleString(), end: end.toLocaleString(), total: total.toLocaleString() })}</span>
    <div style="display:flex;gap:8px;">
      <button class="btn btn-soft btn-sm btn-prev" ${offset === 0 ? "disabled" : ""}>${LH("Prev")}</button>
      <button class="btn btn-soft btn-sm btn-next" ${end >= total ? "disabled" : ""}>${LH("Next")}</button>
    </div>
  `;
  const prev = el.querySelector(".btn-prev");
  const next = el.querySelector(".btn-next");
  if (prev) prev.addEventListener("click", () => onPage(Math.max(0, offset - limit)));
  if (next) next.addEventListener("click", () => onPage(offset + limit));
}

/* ==================== MODALS & SAFETY PERMISSION GATES ==================== */

function setModalFooterButtons(footerButtons) {
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
}

function showModal(title, bodyHtml, footerButtons) {
  state.modalToken += 1;
  state.onModalDismiss = null;
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = bodyHtml;
  setModalFooterButtons(footerButtons);
  document.getElementById("modal-backdrop").classList.remove("hidden");
  return state.modalToken;
}

function closeModal() {
  state.modalToken += 1;
  document.getElementById("modal-backdrop").classList.add("hidden");
  // Lets promise based dialogs settle when closed with the X button or Escape.
  const hook = state.onModalDismiss;
  state.onModalDismiss = null;
  if (typeof hook === "function") hook();
}

function openReviewModal() {
  const { items } = getEffectiveSelectedItems();
  const rowsHtml = items
    .map(
      (it) => `
      <div class="review-row">
        <div style="min-width:0;flex:1;">
          <div style="display:flex;gap:8px;align-items:center;">
            <strong>${LH(it.label)}</strong>
            ${renderRiskBadge(it.risk_level || "safe", it.risk_reason)}
          </div>
          ${it.risk_reason ? `<div class="item-human-hint">${escapeHtml(it.risk_reason)}</div>` : ""}
          <div class="item-subpath">${escapeHtml(it.path)}</div>
        </div>
        <span class="size-pill">${escapeHtml(it.size_human || formatBytes(it.size_bytes))}</span>
        <button class="btn btn-soft btn-sm btn-keep" data-key="${escapeHtml(it.key)}">${LH("Keep")}</button>
      </div>`
    )
    .join("");

  showModal(
    L("Selected for Cleanup ({count})", { count: items.length }),
    `<div class="review-list">${rowsHtml || `<p class='muted'>${LH("No items selected.")}</p>`}</div>`,
    [{ text: L("Done"), cls: "btn-primary", onClick: closeModal }]
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

// Promise based confirmation built on the shared modal. Resolves true only if the user confirms.
function confirmAction(title, bodyHtml, confirmText, confirmCls = "btn-danger") {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    showModal(title, bodyHtml, [
      { text: tr("cancel", "Cancel"), cls: "btn-soft", onClick: () => finish(false) },
      { text: confirmText, cls: confirmCls, onClick: () => finish(true) },
    ]);
    state.onModalDismiss = () => finish(false);
  });
}

// Plain explanation of how this copy of DriveSweep will be updated.
function describeUpdateMethod(u) {
  const folder = u.update_folder ? tr("upd_folder_in").replace("{path}", u.update_folder) : "";
  if (u.update_method === "replace_exe") return tr("upd_method_exe").replace("{folder}", folder);
  if (u.update_method === "replace_folder") return tr("upd_method_folder").replace("{folder}", folder);
  return tr("upd_method_setup");
}

function openConfirmCleanModal() {
  const { items } = getEffectiveSelectedItems();
  if (items.length === 0) return;

  const mode = getDeleteMode();
  const totalBytes = items.reduce((acc, it) => acc + Number(it.size_bytes || 0), 0);
  const isPerm = mode === "permanent";
  const cautionItems = items.filter((it) => it.risk_level === "caution");
  const hasWindowsOld = items.some((it) => /(^|[\\/])windows\.old[\\/]?$/i.test(String(it.path || "")));
  const isDangerous = isPerm || cautionItems.length > 0 || hasWindowsOld;

  const warningHtml = isPerm
    ? `<div class="warning-box"><strong>${LH("Permission Required (Permanent Delete):")}</strong> ${LH("Selected items will bypass the Recycle Bin and cannot be recovered.")}</div>`
    : `<div class="summary-strip">${escapeHtml(tr("recycle_note"))}</div>`;

  const winOldItem = items.find((it) => /(^|[\\/])windows\.old[\\/]?$/i.test(String(it.path || "")));
  const winOldHtml = winOldItem
    ? `<div class="caution-box"><strong>${escapeHtml(tr("winold_title"))}</strong> ${escapeHtml(tr("winold_body"))}</div>`
    : "";

  const cautionHtml = cautionItems.length
    ? `<div class="caution-box"><strong>${LH("Caution Items Flagged ({count}):", { count: cautionItems.length })}</strong> ${LH("You selected personal, active project, or sensitive files. Please verify you intend to remove them.")}</div>`
    : "";

  const ackHtml = isDangerous
    ? `<label class="ack-box"><input id="danger-ack" type="checkbox" /><span>${isPerm ? LH("I give permission to proceed with this permanent deletion.") : LH("I give permission to proceed with this caution cleanup.")}</span></label>`
    : "";

  showModal(
    isDangerous ? L("Permission Required: Confirm Cleanup") : L("Confirm Move to Recycle Bin"),
    `
      ${warningHtml}
      ${winOldHtml}
      ${cautionHtml}
      <p>${LH("Ready to clean {count} selected item(s) totaling {size}.", { count: `<strong>${items.length}</strong>`, size: `<strong>${formatBytes(totalBytes)}</strong>` })}</p>
      <div class="review-list">
        ${items
          .slice(0, 40)
          .map(
            (it) => `
          <div class="review-row">
            <div style="min-width:0;flex:1;">
              <div style="display:flex;gap:8px;align-items:center;">
                <strong>${LH(it.label)}</strong>
                ${renderRiskBadge(it.risk_level || "safe", it.risk_reason)}
              </div>
              <div class="item-subpath">${escapeHtml(it.path)}</div>
              ${it.risk_level === "caution" && it.risk_reason ? `<div class="muted small-text">${escapeHtml(it.risk_reason)}</div>` : ""}
            </div>
            <span class="size-pill">${escapeHtml(it.size_human || formatBytes(it.size_bytes))}</span>
          </div>`
          )
          .join("")}
        ${items.length > 40 ? `<div class="muted small-text">${LH("...and {count} more item(s).", { count: items.length - 40 })}</div>` : ""}
      </div>
      ${ackHtml}
    `,
    [
      { text: L("Cancel"), cls: "btn-soft", onClick: closeModal },
      {
        id: "btn-confirm-execute",
        text: isPerm ? L("Permanently Delete") : L("Move to Recycle Bin"),
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
  const totalCount = Math.max(1, items.length);
  state.isCleaning = true;

  const renderProgressBody = (done, total, currentPath, freedHuman) => {
    const pct = Math.min(100, Math.max(4, Math.round((done / Math.max(1, total)) * 100)));
    return `
      <div class="summary-strip" style="margin-bottom:12px;">
        <div>${LH("Progress:")} <strong id="cleanup-prog-count">${done} / ${total}</strong></div>
        <div>${LH("Reclaimed so far:")} <strong id="cleanup-prog-freed" class="accent-good">${escapeHtml(freedHuman || "0 B")}</strong></div>
      </div>
      <div class="progress-track" style="margin-bottom:10px;">
        <div id="cleanup-prog-fill" class="progress-fill" style="width:${pct}%;transition:width 0.15s ease;"></div>
      </div>
      <div id="cleanup-prog-path" class="preset-path" title="${escapeHtml(currentPath || "")}">
        ${currentPath ? escapeHtml(currentPath) : LH("Preparing cleanup...")}
      </div>
    `;
  };

  showModal(
    L("Cleaning Selected Items..."),
    renderProgressBody(0, totalCount, items[0]?.path || "", "0 B"),
    [
      {
        id: "btn-cancel-cleanup",
        text: L("Cancel Remaining"),
        cls: "btn-soft",
        onClick: async () => {
          const cancelBtn = document.getElementById("btn-cancel-cleanup");
          if (cancelBtn) {
            cancelBtn.disabled = true;
            cancelBtn.textContent = L("Stopping...");
          }
          await api().cancel_cleanup();
        },
      },
    ]
  );

  const includeDocker = items.some((it) => it.is_docker_prune);
  const targets = items
    .filter((it) => !it.is_docker_prune)
    .map((it) => ({ path: it.path, contents_only: !!it.contents_only }));

  let res = null;
  try {
    await api().start_cleanup(targets, mode, includeDocker);
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 130));
      const st = await api().get_cleanup_status();
      if (st.status === "running") {
        const countEl = document.getElementById("cleanup-prog-count");
        const freedEl = document.getElementById("cleanup-prog-freed");
        const fillEl = document.getElementById("cleanup-prog-fill");
        const pathEl = document.getElementById("cleanup-prog-path");
        const pct = Math.min(100, Math.max(4, Math.round((st.done / Math.max(1, st.total)) * 100)));
        if (countEl) countEl.textContent = `${st.done} / ${st.total}`;
        if (freedEl) freedEl.textContent = st.freed_human || "0 B";
        if (fillEl) fillEl.style.width = `${pct}%`;
        if (pathEl) pathEl.textContent = st.current_path || "Cleaning...";
        continue;
      }
      if (st.status === "error") {
        throw new Error(st.error || L("Cleanup failed."));
      }
      res = st.result;
      break;
    }
  } catch (err) {
    state.isCleaning = false;
    showModal(
      L("Cleanup Failed"),
      `<div class="warning-box">${escapeHtml(String(err))}</div>`,
      [{ text: L("Close"), cls: "btn-primary", onClick: closeModal }]
    );
    return;
  } finally {
    state.isCleaning = false;
  }

  if (!res) {
    closeModal();
    return;
  }

  renderDrives(res.drives_after);
  if (res.freed_bytes) recordLifetimeCleanup(res.freed_bytes);

  const hist = await api().get_history(50);
  updateHeaderCounts(undefined, hist.length);

  state.selectedMap.clear();
  updateSelectionBar();

  const failedHtml = (res.failed || []).length
    ? `<div class="warning-box" style="margin-top:12px;">
         <strong>${LH("Skipped / Locked ({count}):", { count: res.failed.length })}</strong>
         <ul>${res.failed.slice(0, 15).map((f) => `<li><code>${escapeHtml(f.path)}</code>: ${escapeHtml(f.error)}</li>`).join("")}</ul>
       </div>`
    : "";

  const dockerHtml = res.docker_result
    ? `<p class="small-text"><strong>${LH("Docker Prune:")}</strong> ${escapeHtml(res.docker_result.message)}</p>`
    : "";

  const title = res.cancelled ? L("Cleanup Stopped (Partial)") : L("Cleanup Complete");
  showModal(
    title,
    `
      <div class="summary-strip">
        <div>${LH("Reclaimed:")} <strong class="accent-good">${escapeHtml(res.freed_human)}</strong></div>
        <div>${LH("Items cleaned:")} <strong>${res.deleted_count}</strong></div>
        <div>${LH("Mode:")} <strong>${res.mode === "permanent" ? LH("Permanent Delete") : LH("Recycle Bin")}</strong></div>
      </div>
      ${dockerHtml}
      ${failedHtml}
    `,
    [
      {
        text: L("Done"),
        cls: "btn-primary",
        onClick: async () => {
          closeModal();
          await loadSmartScan();
          state.largeData = null;
          if (state.activeTab === "large") {
            await loadLargeSpaces(true);
          }
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
  btn.textContent = L("Refreshing...");

  try {
    const [drives] = await Promise.all([
      api().refresh_drives(),
      new Promise((resolve) => setTimeout(resolve, 240)),
    ]);
    renderDrives(drives, true);
    btn.classList.remove("is-busy");
    btn.classList.add("is-done");
    btn.textContent = L("Updated");
  } catch (_err) {
    btn.classList.remove("is-busy");
    btn.classList.add("is-error");
    btn.textContent = L("Failed");
  } finally {
    btn.disabled = false;
    refreshResetTimer = setTimeout(() => {
      btn.classList.remove("is-busy", "is-done", "is-error");
      btn.textContent = L("Refresh");
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
          L("Permission Required: Permanent Delete Mode"),
          `<div class="warning-box"><strong>${LH("Warning:")}</strong> ${LH("In Permanent Delete mode, cleaned files bypass the Recycle Bin and cannot be restored.")}</div>
           <p>${LH("Do you want to switch to Permanent Delete mode?")}</p>`,
          [
            {
              text: L("Keep Safe Recycle Bin"),
              cls: "btn-soft",
              onClick: () => {
                setDeleteMode("recycle");
                closeModal();
              },
            },
            {
              text: L("Allow Permanent Delete"),
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
      L("Permission Required: Restart as Administrator"),
      `<div class="caution-box">${LH("Windows UAC will prompt to relaunch DriveSweep with Administrator privileges so it can clean protected system temp folders.")}</div>`,
      [
        { text: L("Cancel"), cls: "btn-soft", onClick: closeModal },
        {
          text: L("Continue & Relaunch"),
          cls: "btn-primary",
          onClick: async () => {
            closeModal();
            const res = await api().relaunch_as_admin();
            if (!res.ok) {
              showModal(L("Elevation Failed"), `<p>${escapeHtml(res.error || L("Could not elevate."))}</p>`, [
                { text: L("Close"), cls: "btn-primary", onClick: closeModal },
              ]);
            }
          },
        },
      ]
    );
  });

  document.getElementById("btn-smart-scan").addEventListener("click", loadSmartScan);
  document.getElementById("btn-hero-restore-rb")?.addEventListener("click", async () => {
    await api().open_recycle_bin();
    showToast(L("Opened Windows Recycle Bin to review or restore items"), "info");
  });
  document.getElementById("smart-filter").addEventListener("input", renderSmartGroups);
  document.getElementById("btn-large-rescan")?.addEventListener("click", () => loadLargeSpaces(true));
  document.getElementById("large-filter")?.addEventListener("input", renderLargeSpacesTable);
  document.getElementById("large-space-filter")?.addEventListener("change", renderLargeSpacesTable);
  document.getElementById("large-min-mb")?.addEventListener("change", renderLargeSpacesTable);
  document.getElementById("btn-large-mode-files")?.addEventListener("click", () => {
    state.largeMode = "files";
    document.getElementById("btn-large-mode-files")?.classList.add("active");
    document.getElementById("btn-large-mode-folders")?.classList.remove("active");
    renderLargeSpacesTable();
  });
  document.getElementById("btn-large-mode-folders")?.addEventListener("click", () => {
    state.largeMode = "folders";
    document.getElementById("btn-large-mode-folders")?.classList.add("active");
    document.getElementById("btn-large-mode-files")?.classList.remove("active");
    renderLargeSpacesTable();
  });
  document.getElementById("btn-explorer-largest-files")?.addEventListener("click", () => {
    state.largestMode = "files";
    document.getElementById("btn-explorer-largest-files")?.classList.add("active");
    document.getElementById("btn-explorer-largest-folders")?.classList.remove("active");
    loadLargestFiles();
  });
  document.getElementById("btn-explorer-largest-folders")?.addEventListener("click", () => {
    state.largestMode = "folders";
    document.getElementById("btn-explorer-largest-folders")?.classList.add("active");
    document.getElementById("btn-explorer-largest-files")?.classList.remove("active");
    loadLargestFiles();
  });
  document.getElementById("btn-smart-collapse-toggle").addEventListener("click", () => {
    const cards = Array.from(document.querySelectorAll(".group-card[data-group]"));
    const allCollapsed = cards.length > 0 && cards.every((el) => state.collapsedGroups.has(el.dataset.group));
    for (const el of cards) {
      if (allCollapsed) {
        state.collapsedGroups.delete(el.dataset.group);
      } else {
        state.collapsedGroups.add(el.dataset.group);
      }
    }
    renderSmartGroups();
  });

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

  const runAllFilesQuery = () => {
    state.allFilesState.query = document.getElementById("allfiles-query").value;
    state.allFilesState.category = document.getElementById("allfiles-category")?.value || "";
    state.allFilesState.ext = document.getElementById("allfiles-ext").value;
    state.allFilesState.minMb = Number(document.getElementById("allfiles-minmb").value || 0);
    state.allFilesState.minAgeDays = Number(document.getElementById("allfiles-age").value || 0);
    state.allFilesState.sort = document.getElementById("allfiles-sort").value;
    state.allFilesState.offset = 0;
    loadAllFiles();
  };

  document.getElementById("btn-allfiles-search").addEventListener("click", runAllFilesQuery);
  document.getElementById("allfiles-category")?.addEventListener("change", runAllFilesQuery);
  document.getElementById("allfiles-age")?.addEventListener("change", runAllFilesQuery);
  document.getElementById("allfiles-sort")?.addEventListener("change", runAllFilesQuery);
  document.getElementById("allfiles-query")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runAllFilesQuery();
  });

  document.getElementById("devbloat-query")?.addEventListener("input", (e) => {
    state.devBloatQuery = e.target.value || "";
    renderDevArtifacts();
  });
  document.getElementById("devbloat-age").addEventListener("change", (e) => {
    state.devBloatMinAgeDays = Number(e.target.value || 0);
    loadDevArtifacts();
  });
  document.getElementById("btn-devbloat-select-inactive")?.addEventListener("click", () => {
    selectInactiveDevArtifacts(Math.max(30, Number(state.devBloatMinAgeDays || 30)));
  });

  document.getElementById("btn-windows-refresh")?.addEventListener("click", () => loadWindowsToolsView(true));
  document.getElementById("windows-installer-age")?.addEventListener("change", (e) => {
    state.windowsAgeDays = Number(e.target.value || 30);
    loadWindowsToolsView(true);
  });
  document.getElementById("btn-add-custom-preset")?.addEventListener("click", promptAddCustomPreset);
  const exportMenuWrap = document.getElementById("export-menu-wrap");
  const exportToggle = document.getElementById("btn-export-toggle");
  const exportDropdown = document.getElementById("export-dropdown");
  exportToggle?.addEventListener("click", (e) => {
    e.stopPropagation();
    exportDropdown?.classList.toggle("hidden");
  });
  document.addEventListener("click", (e) => {
    if (exportDropdown && exportMenuWrap && !exportMenuWrap.contains(e.target)) {
      exportDropdown.classList.add("hidden");
    }
  });
  document.getElementById("btn-export-csv")?.addEventListener("click", () => {
    exportDropdown?.classList.add("hidden");
    handleExportReport("csv");
  });
  document.getElementById("btn-export-json")?.addEventListener("click", () => {
    exportDropdown?.classList.add("hidden");
    handleExportReport("json");
  });
  document.getElementById("btn-find-dups")?.addEventListener("click", startDuplicateScan);
  document.getElementById("btn-cancel-dups")?.addEventListener("click", () => api().cancel_duplicate_scan());
  document.getElementById("btn-dup-select-extra")?.addEventListener("click", selectAllExtraDuplicates);
  document.getElementById("dup-query")?.addEventListener("input", (e) => {
    state.dupQuery = e.target.value || "";
    renderDuplicateResults();
  });
  document.getElementById("dup-keep-strategy")?.addEventListener("change", (e) => {
    state.dupKeepStrategy = e.target.value || "newest";
    renderDuplicateResults();
  });

  document.getElementById("btn-review-queue").addEventListener("click", openReviewModal);
  document.getElementById("btn-clean-now").addEventListener("click", openConfirmCleanModal);
  document.getElementById("btn-updates-privacy").addEventListener("click", () => openUpdatesPrivacyModal(false));
  document.getElementById("app-version").addEventListener("click", () => openUpdatesPrivacyModal(false));
  document.getElementById("modal-close").addEventListener("click", () => {
    if (!state.isCleaning && !state.isUpdating) closeModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const backdrop = document.getElementById("modal-backdrop");
      if (backdrop && !backdrop.classList.contains("hidden") && !state.isCleaning && !state.isUpdating) {
        closeModal();
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
      e.preventDefault();
      const explorerActive = document.getElementById("tab-explorer")?.classList.contains("active");
      const largeActive = document.getElementById("tab-large")?.classList.contains("active");
      const allFilesActive = document.getElementById("subview-allfiles")?.classList.contains("active");
      const target = explorerActive
        ? document.getElementById(allFilesActive ? "allfiles-query" : "browse-query")
        : largeActive
          ? document.getElementById("large-filter")
          : document.getElementById("smart-filter");
      if (target) {
        target.focus();
        target.select();
      }
    }
  });
}

async function handleExportReport(fmt) {
  const res = await api().export_scan_report(fmt);
  if (res.cancelled) return;
  if (!res.ok) {
    showModal(
      L("Export Failed"),
      `<div class="warning-box">${escapeHtml(res.error || L("Could not export report."))}</div>`,
      [{ text: L("Close"), cls: "btn-primary", onClick: closeModal }]
    );
    return;
  }
  showModal(
    L("Scan Report Exported"),
    `<div class="summary-strip" style="margin-bottom:10px;">
       <div>${LH("Exported {folders} folders and {files} largest files as {format}.", { folders: `<strong>${res.folders_exported}</strong>`, files: `<strong>${res.files_exported}</strong>`, format: `<strong>${escapeHtml(res.format.toUpperCase())}</strong>` })}</div>
     </div>
     <div class="item-subpath">${escapeHtml(res.path)}</div>`,
    [
      { text: L("Reveal File"), cls: "btn-soft", onClick: () => api().open_in_explorer(res.path) },
      { text: L("Close"), cls: "btn-primary", onClick: closeModal },
    ]
  );
}

async function startDuplicateScan() {
  const minKb = Number(document.getElementById("dup-min-size")?.value || 100);
  const prog = document.getElementById("dup-progress");
  const findBtn = document.getElementById("btn-find-dups");
  const cancelBtn = document.getElementById("btn-cancel-dups");
  const groupsEl = document.getElementById("dup-groups");

  if (groupsEl) groupsEl.innerHTML = "";
  document.getElementById("btn-dup-select-extra")?.classList.add("hidden");
  prog?.classList.remove("hidden");
  cancelBtn?.classList.remove("hidden");
  if (findBtn) findBtn.disabled = true;

  const st = await api().start_duplicate_scan(minKb);
  if (st.status === "error") {
    prog?.classList.add("hidden");
    cancelBtn?.classList.add("hidden");
    if (findBtn) findBtn.disabled = false;
    document.getElementById("dup-meta").textContent = st.error || "Could not start duplicate scan.";
    return;
  }

  if (state.dupTimer) clearInterval(state.dupTimer);
  state.dupTimer = setInterval(pollDuplicateStatus, 220);
  await pollDuplicateStatus();
}

async function pollDuplicateStatus() {
  const st = await api().get_duplicate_status();
  const prog = document.getElementById("dup-progress");
  const lbl = document.getElementById("dup-status-label");
  const statsEl = document.getElementById("dup-stats-text");
  const fillEl = document.getElementById("dup-progress-fill");
  const findBtn = document.getElementById("btn-find-dups");
  const cancelBtn = document.getElementById("btn-cancel-dups");

  if (st.status === "running") {
    const tot = Math.max(1, Number(st.total || 0));
    const pct = st.total > 0 ? Math.min(100, Math.max(5, Math.round((st.progress / tot) * 100))) : 15;
    if (lbl) lbl.textContent = st.stage === "hashing" ? L("Verifying SHA-256 checksums...") : L("Checking matching file sizes...");
    if (statsEl) statsEl.textContent = st.total > 0 ? `${st.progress} / ${st.total}` : "...";
    if (fillEl) fillEl.style.width = `${pct}%`;
    return;
  }

  clearInterval(state.dupTimer);
  state.dupTimer = null;
  prog?.classList.add("hidden");
  cancelBtn?.classList.add("hidden");
  if (findBtn) findBtn.disabled = false;

  if (st.status === "error") {
    document.getElementById("dup-meta").textContent = st.error || "Duplicate search failed.";
    return;
  }

  state.dupResult = st.result || null;
  renderDuplicateResults();
}

function getOrderedDuplicateCopies(copies) {
  const strat = state.dupKeepStrategy || "newest";
  const sorted = [...(copies || [])].sort((a, b) => {
    if (strat === "oldest") {
      const mdiff = Number(a.mtime || 0) - Number(b.mtime || 0);
      if (mdiff !== 0) return mdiff;
    } else if (strat === "shortest") {
      const ldiff = String(a.path || "").length - String(b.path || "").length;
      if (ldiff !== 0) return ldiff;
    } else {
      const mdiff = Number(b.mtime || 0) - Number(a.mtime || 0);
      if (mdiff !== 0) return mdiff;
    }
    return String(a.path || "").localeCompare(String(b.path || ""));
  });
  return sorted.map((c, idx) => ({ ...c, _keepThis: idx === 0 }));
}

function renderDuplicateResults() {
  const container = document.getElementById("dup-groups");
  const meta = document.getElementById("dup-meta");
  const selAllBtn = document.getElementById("btn-dup-select-extra");
  if (!container) return;

  const res = state.dupResult;
  if (!res || !(res.groups || []).length) {
    meta.textContent = L("No duplicate files found for this size threshold.");
    container.innerHTML = `<div class="muted small-text" style="padding:14px;">${LH("No exact duplicates found.")}</div>`;
    selAllBtn?.classList.add("hidden");
    return;
  }

  const q = (state.dupQuery || "").trim().toLowerCase();
  const visibleGroups = (res.groups || []).filter((grp) => {
    if (!q) return true;
    if (String(grp.name || "").toLowerCase().includes(q)) return true;
    return (grp.copies || []).some((c) => String(c.path || "").toLowerCase().includes(q));
  });

  meta.textContent = L("{count} duplicate group(s) | {size} reclaimable if extra copies are cleaned", { count: visibleGroups.length, size: res.reclaimable_human });
  selAllBtn?.classList.toggle("hidden", visibleGroups.length === 0);
  container.innerHTML = "";

  if (visibleGroups.length === 0) {
    container.innerHTML = `<div class="muted small-text" style="padding:14px;">${LH("No duplicate groups match \"{query}\".", { query: escapeHtml(state.dupQuery) })}</div>`;
    return;
  }

  const strat = state.dupKeepStrategy || "newest";
  const keepLabel =
    strat === "oldest" ? "Keep Oldest" : strat === "shortest" ? "Keep Shortest" : tr("dup_keep_newest", "Keep Newest");

  for (const grp of visibleGroups) {
    const card = document.createElement("div");
    card.className = "group-card";
    card.innerHTML = `
      <div class="group-header">
        <div class="group-title-wrap">
          <span class="group-title">${escapeHtml(grp.name)}</span>
          <span class="badge badge-info">${grp.copy_count} copies</span>
          <span class="badge badge-warn">${LH("Hash: {hash}", { hash: escapeHtml(grp.sha256_short) })}</span>
        </div>
        <div class="group-right">
          <span class="muted small-text">${LH("Each {size}", { size: escapeHtml(grp.size_human) })}</span>
          <span class="group-size">${escapeHtml(grp.reclaimable_human)} extra</span>
        </div>
      </div>
      <div class="group-body"></div>
    `;
    const body = card.querySelector(".group-body");
    for (const copy of getOrderedDuplicateCopies(grp.copies)) {
      const excluded = !!copy.excluded || isPathExcludedLocal(copy.path);
      const disabled = !!copy.is_protected || excluded;
      const checked = !disabled && isItemSelected(copy.path, false);

      const row = document.createElement("div");
      row.className = "preset-row";
      row.innerHTML = `
        <label class="toggle-switch">
          <input type="checkbox" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
          <span class="toggle-slider"></span>
        </label>
        <div class="preset-main">
          <div class="preset-title-line">
            <span class="preset-title">${escapeHtml(copy.name)}</span>
            ${copy._keepThis ? `<span class="badge badge-good">${escapeHtml(keepLabel)}</span>` : `<span class="badge badge-warn">${escapeHtml(tr("dup_extra_copy", "Extra Copy"))}</span>`}
            ${renderRiskBadge(copy.risk_level || "safe", copy.risk_reason || "")}
          </div>
          <div class="preset-path" title="${escapeHtml(copy.path)}">${escapeHtml(copy.path)}</div>
        </div>
        <div class="preset-right">
          <button class="btn btn-soft btn-xs btn-open">${escapeHtml(tr("open_folder", "Open Folder"))}</button>
          <span class="size-pill">${escapeHtml(copy.size_human)}</span>
        </div>
      `;
      const cb = row.querySelector('input[type="checkbox"]');
      if (!disabled) {
        cb.addEventListener("change", () => {
          setItemSelected(
            {
              path: copy.path,
              label: L("Duplicate: {name}", { name: copy.name }),
              size_bytes: copy.size_bytes,
              size_human: copy.size_human,
              contents_only: false,
              risk_level: copy.risk_level || "caution",
              risk_reason: copy.risk_reason || L("Exact duplicate file."),
              source: "duplicates",
            },
            cb.checked
          );
        });
      }
      row.querySelector(".btn-open")?.addEventListener("click", () => api().open_in_explorer(copy.path));
      body.appendChild(row);
    }
    container.appendChild(card);
  }
}

function selectAllExtraDuplicates() {
  const res = state.dupResult;
  if (!res || !res.groups) return;
  const q = (state.dupQuery || "").trim().toLowerCase();
  for (const grp of res.groups) {
    if (q) {
      const hit =
        String(grp.name || "").toLowerCase().includes(q) ||
        (grp.copies || []).some((c) => String(c.path || "").toLowerCase().includes(q));
      if (!hit) continue;
    }
    for (const copy of getOrderedDuplicateCopies(grp.copies)) {
      if (copy._keepThis || copy.is_protected || copy.excluded || isPathExcludedLocal(copy.path)) {
        continue;
      }
      setItemSelected(
        {
          path: copy.path,
          label: L("Duplicate: {name}", { name: copy.name }),
          size_bytes: copy.size_bytes,
          size_human: copy.size_human,
          contents_only: false,
          risk_level: copy.risk_level || "caution",
          risk_reason: copy.risk_reason || L("Exact duplicate copy."),
          source: "duplicates",
        },
        true
      );
    }
  }
  renderDuplicateResults();
}

// One time notice: what DriveSweep does, its limits, and an opt in for update checks.
function showFirstRunNotice() {
  return new Promise((resolve) => {
    const T = (k) => escapeHtml(tr(k));
    showModal(
      tr("fr_title", "Before you start"),
      `
        <p>${T("fr_intro")}</p>
        <ul class="notice-list">
          <li><strong>${T("fr_backup_b")}</strong> ${T("fr_backup")}</li>
          <li><strong>${T("fr_recycle_b")}</strong> ${T("fr_recycle")}</li>
          <li><strong>${T("fr_protect_b")}</strong> ${T("fr_protect")}</li>
          <li><strong>${T("fr_local_b")}</strong> ${T("fr_local")}</li>
        </ul>
        <label class="ack-box"><input id="chk-firstrun-updates" type="checkbox" /><span>${T("fr_updates_opt")}</span></label>
        <p class="muted small-text">${T("fr_affiliation")}</p>
      `,
      [
        {
          id: "btn-firstrun-ok",
          text: tr("fr_ok", "I Understand"),
          cls: "btn-primary",
          onClick: async () => {
            const opted = !!document.getElementById("chk-firstrun-updates")?.checked;
            state.onModalDismiss = null;
            closeModal();
            try {
              await api().accept_disclaimer(opted);
            } catch (_e) {}
            resolve(opted);
          },
        },
      ]
    );
    // Closed without accepting: continue with update checks off and show the notice next launch.
    state.onModalDismiss = () => resolve(false);
  });
}

async function initApp() {
  window.addEventListener("error", (ev) => {
    try {
      api().report_ui_error(ev.message || "Uncaught UI error", ev.filename || "window.onerror", ev.error?.stack || "");
    } catch (_e) {}
  });
  window.addEventListener("unhandledrejection", (ev) => {
    try {
      const reason = ev.reason;
      api().report_ui_error(String(reason?.message || reason || "Unhandled promise rejection"), "unhandledrejection", reason?.stack || "");
    } catch (_e) {}
  });

  bindEvents();
  const info = await api().get_app_info();
  applyTheme(info.theme || "dark");
  state.language = info.language || "en";
  if (window.DriveSweepI18n) {
    window.DriveSweepI18n.setLanguage(state.language);
  }
  state.isAdmin = !!info.is_admin;
  state.osName = info.os || "Windows";
  state.version = info.version || "0.3.1";
  state.dataDir = info.data_dir || "";
  state.installKind = info.install_kind || "source";
  state.autoCheckUpdates = info.auto_check_updates === true;
  state.reminderEnabled = !!info.reminder_enabled;
  state.reminderFrequency = info.reminder_frequency || "weekly";
  state.reminderThresholdPct = Number(info.reminder_threshold_pct || 15);
  state.lowDiskAlerts = info.low_disk_alerts || null;
  state.lifetimeStats = info.lifetime_stats || { total_runs: 0, lifetime_freed_bytes: 0, lifetime_freed_human: "0 B" };
  document.getElementById("app-version").textContent = `v${state.version}`;
  updateHeaderCounts(info.exclusions || [], info.history_count || 0);
  renderLowDiskBanner();

  renderPrivilegeLabels();
  if (!state.isAdmin && state.osName === "Windows") {
    document.getElementById("btn-elevate").classList.remove("hidden");
  }

  renderDrives(info.drives);
  if (!info.disclaimer_accepted) {
    state.autoCheckUpdates = await showFirstRunNotice();
  }
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
