"""Smart AI, Dev & App Cache Presets (Windows, macOS, and Linux)."""

from __future__ import annotations

import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil

from app.safety import format_bytes, is_os_protected_path, is_personal_guarded_path, to_os_path
from app.storage import get_exclusions, is_path_excluded


@dataclass
class SmartPresetCandidate:
    id: str
    group: str
    label: str
    path: str
    contents_only: bool
    safety_note: str
    default_checked: bool = True
    process_hint: str | None = None
    is_docker_prune: bool = False


@dataclass
class SmartPresetResult:
    id: str
    group: str
    label: str
    path: str
    contents_only: bool
    size_bytes: int
    size_human: str
    file_count: int
    safety_note: str
    default_checked: bool
    excluded: bool
    risk_level: str
    risk_reason: str
    running_app: str | None
    is_docker_prune: bool = False


def _get_running_process_names() -> set[str]:
    names: set[str] = set()
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name:
                names.add(name)
    except Exception:
        pass
    return names


def _is_process_running(running_names: set[str], prefix: str | None) -> str | None:
    if not prefix:
        return None
    low = prefix.lower()
    for name in running_names:
        if name.startswith(low):
            return prefix
    return None


def _measure_path(raw_path: str) -> tuple[int, int]:
    """Fast iterative measurement of (total_bytes, file_count) with long-path support."""
    os_p = to_os_path(raw_path)
    if not os.path.lexists(os_p) or os.path.islink(os_p):
        return 0, 0
    if os.path.isfile(os_p):
        try:
            return os.stat(os_p, follow_symlinks=False).st_size, 1
        except OSError:
            return 0, 0

    total_bytes = 0
    file_count = 0
    stack = [os_p]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                            file_count += 1
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
    return total_bytes, file_count


def _safe_add(
    items: list[SmartPresetCandidate],
    cid: str,
    group: str,
    label: str,
    target: Path,
    *,
    contents_only: bool = True,
    note: str = "Safe regenerable cache.",
    default_checked: bool = True,
    process_hint: str | None = None,
) -> None:
    if not target.exists():
        return
    if is_personal_guarded_path(target):
        return
    if is_os_protected_path(target, allow_temp_contents=contents_only):
        return
    items.append(
        SmartPresetCandidate(
            id=cid,
            group=group,
            label=label,
            path=str(target),
            contents_only=contents_only,
            safety_note=note,
            default_checked=default_checked,
            process_hint=process_hint,
        )
    )


def _discover_windows_candidates() -> list[SmartPresetCandidate]:
    home = Path.home()
    local_app = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming_app = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    temp_dir = Path(os.environ.get("TEMP", local_app / "Temp"))
    win_temp = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Temp"

    items: list[SmartPresetCandidate] = []
    add = lambda *a, **kw: _safe_add(items, *a, **kw)  # noqa: E731

    # 1. Package Managers & ML/CLI Caches
    add("uv-cache", "Package Managers & ML", "Python uv Cache", local_app / "uv" / "cache",
        note="Downloaded Python wheels & uv cache; re-downloads automatically if needed.")
    add("pip-cache", "Package Managers & ML", "Python pip Cache", local_app / "pip" / "cache",
        note="Cached pip wheel downloads.")
    add("bun-cache", "Package Managers & ML", "Bun Package Cache", home / ".bun" / "install" / "cache",
        note="Cached Bun npm packages.")
    add("npm-local-cache", "Package Managers & ML", "npm Cache (AppData Local)", local_app / "npm-cache",
        note="Cached npm tarballs.")
    add("npm-home-cache", "Package Managers & ML", "npm Cache (Home)", home / "npm-cache",
        note="Cached npm tarballs.")
    add("npm-underscore-cache", "Package Managers & ML", "npm _cacache", home / ".npm" / "_cacache",
        note="Standard npm content-addressable cache.")
    add("hf-cache", "Package Managers & ML", "HuggingFace Model Cache", home / ".cache" / "huggingface",
        note="Cached HuggingFace models/datasets (can be many GB; re-downloads on demand).",
        default_checked=False)
    add("torch-cache", "Package Managers & ML", "PyTorch Hub Cache", home / ".cache" / "torch",
        note="Cached PyTorch weights & hub files.", default_checked=False)
    add("codex-runtimes", "AI Coding Tools", "OpenAI Codex Runtimes Cache", home / ".cache" / "codex-runtimes",
        note="Cached Codex CLI runtimes.", process_hint="codex")
    add("playwright-browsers", "Package Managers & ML", "Playwright Browser Binaries", local_app / "ms-playwright",
        note="Downloaded test browsers (re-install with playwright install).", default_checked=False)
    add("gradle-caches", "Package Managers & ML", "Gradle Caches", home / ".gradle" / "caches",
        note="Cached Java/Android Gradle dependencies.", default_checked=False)

    # 2. Claude Desktop & Claude Code
    claude_data = local_app / "Claude-Data"
    if claude_data.exists():
        for profile in claude_data.iterdir():
            if not profile.is_dir():
                continue
            tag = profile.name
            add(f"claude-vm-{tag}", "AI Coding Tools", f"Claude Desktop VM Bundles ({tag})", profile / "vm_bundles",
                note="Claude Desktop VM bundle downloads (often multi-GB). Quit Claude first.",
                process_hint="Claude")
            add(f"claude-cache-{tag}", "AI Coding Tools", f"Claude Desktop Cache ({tag})", profile / "Cache",
                note="Electron cache; preserves logins & chats.", process_hint="Claude")
            add(f"claude-code-cache-{tag}", "AI Coding Tools", f"Claude Desktop Code Cache ({tag})", profile / "Code Cache",
                note="V8 JS code cache.", process_hint="Claude")
            add(f"claude-logs-{tag}", "AI Coding Tools", f"Claude Desktop Logs ({tag})", profile / "logs",
                note="Diagnostic log files.", process_hint="Claude")

    claude_roaming = roaming_app / "Claude"
    if claude_roaming.exists():
        for sub in ("Cache", "Code Cache", "GPUCache", "logs"):
            add(f"claude-roaming-{sub.lower().replace(' ', '-')}", "AI Coding Tools",
                f"Claude App {sub}", claude_roaming / sub,
                note="Electron cache/logs; preserves settings.", process_hint="Claude")

    claude_cli = home / ".claude"
    if claude_cli.exists():
        add("claude-cli-cache", "AI Coding Tools", "Claude Code CLI Cache", claude_cli / "cache",
            note="Claude Code cache folder (preserves settings, plugins & projects).")
        add("claude-cli-debug", "AI Coding Tools", "Claude Code Debug Logs", claude_cli / "debug",
            note="Claude Code debug logs.")
        add("claude-cli-snapshots", "AI Coding Tools", "Claude Code Shell Snapshots", claude_cli / "shell-snapshots",
            note="Old shell environment snapshots created by Claude Code.", default_checked=False)
        add("claude-cli-file-history", "AI Coding Tools", "Claude Code File History", claude_cli / "file-history",
            note="Checkpoint backups of files edited by Claude Code (uncheck if you want undo history).",
            default_checked=False)

    # 3. Editors (VS Code, Cursor)
    vscode = roaming_app / "Code"
    add("vscode-vsix", "Editors & Dev Tools", "VS Code Cached Extension Installers", vscode / "CachedExtensionVSIXs",
        note="Old downloaded VSIX extension packages (installed extensions stay intact).")
    add("vscode-cache", "Editors & Dev Tools", "VS Code Cache", vscode / "Cache",
        note="VS Code renderer cache.", process_hint="Code")
    add("vscode-cached-data", "Editors & Dev Tools", "VS Code CachedData", vscode / "CachedData",
        note="V8 code cache.", process_hint="Code")
    vs_web = vscode / "WebStorage"
    if vs_web.exists():
        for idx, cs in enumerate(vs_web.glob("*/CacheStorage")):
            add(f"vscode-web-{idx}", "Editors & Dev Tools", f"VS Code WebStorage Cache ({cs.parent.name})", cs,
                note="Extension webview cache.", process_hint="Code")

    cursor = roaming_app / "Cursor"
    if cursor.exists():
        add("cursor-vsix", "Editors & Dev Tools", "Cursor Cached Extension Installers", cursor / "CachedExtensionVSIXs",
            note="Old downloaded VSIX packages.")
        add("cursor-cache", "Editors & Dev Tools", "Cursor Cache", cursor / "Cache",
            note="Cursor Electron cache.", process_hint="Cursor")
        add("cursor-cached-data", "Editors & Dev Tools", "Cursor CachedData", cursor / "CachedData",
            note="Cursor V8 code cache.", process_hint="Cursor")

    # 4. Notion, GitHub Desktop, Canva, Zoom, BitTorrent, OpenWA, App Updaters
    notion_base = roaming_app / "Notion" / "Partitions" / "notion"
    if notion_base.exists():
        for sub in ("Service Worker", "Cache", "Code Cache", "GPUCache", "DawnWebGPUCache", "DawnGraphiteCache", "Shared Dictionary"):
            add(f"notion-{sub.lower().replace(' ', '-')}", "Apps & Updaters", f"Notion {sub}", notion_base / sub,
                note="Notion Electron cache; workspace & login stay intact.", process_hint="Notion")

    gh_desktop = local_app / "GitHubDesktop"
    add("gh-packages", "Editors & Dev Tools", "GitHub Desktop Update Packages", gh_desktop / "packages",
        note="Old Squirrel update installers.")
    if gh_desktop.exists():
        app_dirs = sorted([d for d in gh_desktop.iterdir() if d.is_dir() and d.name.startswith("app-")], key=lambda p: p.name, reverse=True)
        for old_app in app_dirs[1:]:
            add(f"gh-old-{old_app.name}", "Editors & Dev Tools", f"GitHub Desktop Old Version ({old_app.name})",
                old_app, contents_only=False, note="Superseded GitHub Desktop version folder.")

    canva = roaming_app / "Canva"
    for sub in ("Cache", "Code Cache", "GPUCache"):
        add(f"canva-{sub.lower().replace(' ', '-')}", "Apps & Updaters", f"Canva {sub}", canva / sub,
            note="Canva desktop cache.", process_hint="Canva")

    add("zoom-downloads", "Apps & Updaters", "Zoom Update Downloads", roaming_app / "Zoom" / "ZoomDownload",
        note="Zoom installer/update temp downloads.")

    bt_base = roaming_app / "BitTorrent Web" / "btweb.exe.WebView2" / "EBWebView" / "Default"
    add("bt-cache", "Apps & Updaters", "BitTorrent Web Cache", bt_base / "Cache", note="WebView2 cache.")
    add("bt-code-cache", "Apps & Updaters", "BitTorrent Web Code Cache", bt_base / "Code Cache", note="WebView2 code cache.")

    if local_app.exists():
        for entry in local_app.iterdir():
            if entry.is_dir() and entry.name.lower().endswith("-updater"):
                add(f"updater-{entry.name}", "Apps & Updaters", f"App Updater Leftovers ({entry.name})",
                    entry, contents_only=False, note="Electron/app auto-updater downloaded installers.")

    openwa_sessions = local_app / "Docker" / "OpenWA" / "data" / "sessions"
    if openwa_sessions.exists():
        for sess in openwa_sessions.iterdir():
            if not sess.is_dir():
                continue
            d = sess / "Default"
            for sub in ("Cache", "Code Cache", "Service Worker"):
                add(f"openwa-{sess.name}-{sub.lower().replace(' ', '-')}", "Apps & Updaters",
                    f"OpenWA ({sess.name}) {sub}", d / sub, note="Browser cache inside OpenWA session.")

    # 5. Browsers & Office/Outlook
    chrome_ud = local_app / "Google" / "Chrome" / "User Data"
    if chrome_ud.exists():
        for prof in chrome_ud.iterdir():
            if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                for sub, label in (
                    ("Cache", "Cache"),
                    ("Code Cache", "Code Cache"),
                    ("GPUCache", "GPUCache"),
                    (os.path.join("Service Worker", "CacheStorage"), "Service Worker Cache"),
                    ("File System", "File System Cache"),
                    ("Shared Dictionary", "Shared Dictionary"),
                ):
                    add(f"chrome-{prof.name}-{label.lower().replace(' ', '-')}", "Browsers",
                        f"Chrome ({prof.name}) {label}", prof / sub,
                        note="Browser cache only; logins, bookmarks & history stay untouched.", process_hint="chrome")
        for extra, label in (
            ("OptGuideOnDeviceModel", "On-Device AI Model"),
            ("OptGuideOnDeviceClassifierModel", "On-Device Classifier Model"),
            ("screen_ai", "Screen AI"),
            ("Snapshots", "Version Snapshots"),
            ("component_crx_cache", "Component CRX Cache"),
        ):
            add(f"chrome-{extra.lower()}", "Browsers", f"Chrome {label}", chrome_ud / extra,
                note="Cached Chrome browser components/models.", process_hint="chrome")
    add("google-updater", "Browsers", "GoogleUpdater Cache", local_app / "Google" / "GoogleUpdater",
        note="Old Chrome/Google updater downloads.")

    edge_ud = local_app / "Microsoft" / "Edge" / "User Data"
    if edge_ud.exists():
        for prof in edge_ud.iterdir():
            if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                for sub, label in (
                    ("Cache", "Cache"),
                    ("Code Cache", "Code Cache"),
                    ("GPUCache", "GPUCache"),
                    (os.path.join("Service Worker", "CacheStorage"), "Service Worker Cache"),
                ):
                    add(f"edge-{prof.name}-{label.lower().replace(' ', '-')}", "Browsers",
                        f"Edge ({prof.name}) {label}", prof / sub,
                        note="Browser cache only; logins & favorites stay untouched.", process_hint="msedge")
        add("edge-snapshots", "Browsers", "Edge Version Snapshots", edge_ud / "Snapshots",
            note="Old Edge upgrade snapshots.", process_hint="msedge")

    add("office-cache", "Apps & Updaters", "Office File Cache",
        local_app / "Microsoft" / "Office" / "16.0" / "OfficeFileCache",
        note="Local Microsoft Office document upload/download cache.")
    add("outlook-cache", "Apps & Updaters", "New Outlook WebView Cache",
        local_app / "Microsoft" / "Olk" / "ebwebview" / "Default" / "Cache",
        note="New Outlook WebView cache.", process_hint="olk")
    add("outlook-code-cache", "Apps & Updaters", "New Outlook WebView Code Cache",
        local_app / "Microsoft" / "Olk" / "ebwebview" / "Default" / "Code Cache",
        note="New Outlook WebView JS cache.", process_hint="olk")

    # 6. Temp Directories
    add("user-temp", "System & Temp", "User Temp Directory", temp_dir,
        note="Temporary files in %TEMP%; active locked files are skipped automatically.")
    add("win-temp", "System & Temp", "Windows Temp Directory", win_temp,
        note="System temporary files in C:\\Windows\\Temp (run as Administrator for full access).")

    return items


def _discover_unix_candidates() -> list[SmartPresetCandidate]:
    """Comprehensive Smart Scan presets for macOS and Linux."""
    home = Path.home()
    is_mac = sys.platform == "darwin"
    cache_root = home / "Library" / "Caches" if is_mac else Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    config_root = home / "Library" / "Application Support" if is_mac else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))

    items: list[SmartPresetCandidate] = []
    add = lambda *a, **kw: _safe_add(items, *a, **kw)  # noqa: E731

    # Package Managers & ML
    add("uv-cache", "Package Managers & ML", "Python uv Cache", cache_root / "uv", note="Downloaded Python wheels & uv cache.")
    add("pip-cache", "Package Managers & ML", "Python pip Cache", cache_root / "pip", note="Cached pip downloads.")
    add("bun-cache", "Package Managers & ML", "Bun Package Cache", home / ".bun" / "install" / "cache", note="Cached Bun packages.")
    add("npm-cache", "Package Managers & ML", "npm _cacache", home / ".npm" / "_cacache", note="Standard npm cache.")
    add("hf-cache", "Package Managers & ML", "HuggingFace Model Cache", home / ".cache" / "huggingface",
        note="Cached HuggingFace models/datasets.", default_checked=False)
    add("torch-cache", "Package Managers & ML", "PyTorch Hub Cache", home / ".cache" / "torch",
        note="Cached PyTorch weights.", default_checked=False)
    add("gradle-caches", "Package Managers & ML", "Gradle Caches", home / ".gradle" / "caches",
        note="Cached Gradle dependencies.", default_checked=False)
    add("playwright-browsers", "Package Managers & ML", "Playwright Browser Binaries",
        cache_root / "ms-playwright", note="Playwright test browsers.", default_checked=False)

    # AI Coding Tools
    add("codex-runtimes", "AI Coding Tools", "OpenAI Codex Runtimes", home / ".cache" / "codex-runtimes",
        note="Cached Codex CLI runtimes.", process_hint="codex")
    claude_cli = home / ".claude"
    if claude_cli.exists():
        add("claude-cli-cache", "AI Coding Tools", "Claude Code CLI Cache", claude_cli / "cache",
            note="Claude Code cache folder.")
        add("claude-cli-debug", "AI Coding Tools", "Claude Code Debug Logs", claude_cli / "debug",
            note="Claude Code debug logs.")
        add("claude-cli-snapshots", "AI Coding Tools", "Claude Code Shell Snapshots", claude_cli / "shell-snapshots",
            note="Old shell environment snapshots.", default_checked=False)
        add("claude-cli-history", "AI Coding Tools", "Claude Code File History", claude_cli / "file-history",
            note="Checkpoint backups of edited files.", default_checked=False)

    for sub in ("Cache", "Code Cache", "GPUCache", "vm_bundles", "logs"):
        add(f"claude-app-{sub.lower().replace(' ', '-')}", "AI Coding Tools", f"Claude Desktop {sub}",
            config_root / "Claude" / sub, note="Claude Desktop cache/logs.", process_hint="Claude")

    # Editors
    for app_dir, label, proc in (("Code", "VS Code", "code"), ("Cursor", "Cursor", "cursor")):
        base = config_root / app_dir
        add(f"{app_dir.lower()}-cache", "Editors & Dev Tools", f"{label} Cache", base / "Cache",
            note=f"{label} renderer cache.", process_hint=proc)
        add(f"{app_dir.lower()}-cached-data", "Editors & Dev Tools", f"{label} CachedData", base / "CachedData",
            note=f"{label} V8 code cache.", process_hint=proc)
        add(f"{app_dir.lower()}-vsix", "Editors & Dev Tools", f"{label} Cached VSIXs", base / "CachedExtensionVSIXs",
            note="Old extension installer packages.")

    if is_mac:
        add("homebrew-cache", "Package Managers & ML", "Homebrew Cache", cache_root / "Homebrew",
            note="Downloaded Homebrew bottles & archives.")
        add("xcode-derived", "Editors & Dev Tools", "Xcode DerivedData",
            home / "Library" / "Developer" / "Xcode" / "DerivedData",
            note="Xcode build intermediates & indexes.", default_checked=False)
        add("chrome-cache", "Browsers", "Google Chrome Cache", cache_root / "Google" / "Chrome",
            note="Chrome browser caches.", process_hint="Google Chrome")
        add("mac-logs", "System & Temp", "User App Logs", home / "Library" / "Logs",
            note="Application diagnostic logs.")
    else:
        add("chrome-cache", "Browsers", "Google Chrome Cache", cache_root / "google-chrome",
            note="Chrome browser caches.", process_hint="chrome")
        add("chromium-cache", "Browsers", "Chromium Cache", cache_root / "chromium",
            note="Chromium browser caches.", process_hint="chromium")
        add("thumbnails", "System & Temp", "Desktop Thumbnail Cache", cache_root / "thumbnails",
            note="Cached file manager thumbnails.")

    return items


def scan_smart_presets(exclusions: list[str] | None = None) -> dict:
    """Scan all smart presets on the system and return measured sizes, warnings, & exclusions."""
    candidates = _discover_windows_candidates() if os.name == "nt" else _discover_unix_candidates()
    running_names = _get_running_process_names()
    ex_list = exclusions if exclusions is not None else get_exclusions()

    results: list[SmartPresetResult] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {pool.submit(_measure_path, item.path): item for item in candidates}
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                size_bytes, file_count = future.result()
            except Exception:
                size_bytes, file_count = 0, 0

            if size_bytes <= 0 and file_count == 0:
                continue

            excluded = is_path_excluded(item.path, ex_list)
            risk_level = "safe" if item.default_checked else "caution"
            risk_reason = (
                "Regenerable cache or temporary files."
                if risk_level == "safe"
                else item.safety_note
            )
            results.append(
                SmartPresetResult(
                    id=item.id,
                    group=item.group,
                    label=item.label,
                    path=item.path,
                    contents_only=item.contents_only,
                    size_bytes=size_bytes,
                    size_human=format_bytes(size_bytes),
                    file_count=file_count,
                    safety_note=item.safety_note,
                    default_checked=False if excluded else item.default_checked,
                    excluded=excluded,
                    risk_level=risk_level,
                    risk_reason=risk_reason,
                    running_app=_is_process_running(running_names, item.process_hint),
                    is_docker_prune=item.is_docker_prune,
                )
            )

    docker_running = _is_process_running(running_names, "com.docker.backend") or _is_process_running(running_names, "dockerd")
    if docker_running and shutil.which("docker"):
        results.append(
            SmartPresetResult(
                id="docker-builder-prune",
                group="Editors & Dev Tools",
                label="Docker Build Cache (docker builder prune)",
                path="docker:builder",
                contents_only=False,
                size_bytes=0,
                size_human="Docker CLI",
                file_count=0,
                safety_note="Runs `docker builder prune -f` to reclaim unused Docker build cache layers.",
                default_checked=False,
                excluded=False,
                risk_level="caution",
                risk_reason="Removes cached Docker image build layers (future builds may re-run steps).",
                running_app=None,
                is_docker_prune=True,
            )
        )

    results.sort(key=lambda r: r.size_bytes, reverse=True)
    total_bytes = sum(r.size_bytes for r in results)
    recommended_bytes = sum(r.size_bytes for r in results if r.default_checked)

    return {
        "items": [asdict(r) for r in results],
        "total_bytes": total_bytes,
        "total_human": format_bytes(total_bytes),
        "recommended_bytes": recommended_bytes,
        "recommended_human": format_bytes(recommended_bytes),
        "count": len(results),
    }
