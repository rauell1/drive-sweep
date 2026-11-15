"""Universal Smart Cleanup Presets for Windows, macOS, and Linux."""

from __future__ import annotations

import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import psutil

from app.safety import (
    classify_path_risk,
    format_bytes,
    get_all_personal_roots,
    is_os_protected_path,
    is_personal_guarded_path,
    to_os_path,
)
from app.storage import get_custom_presets, get_exclusions, is_path_excluded


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
    is_custom: bool = False


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
    is_custom: bool = False


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
                        st = entry.stat(follow_symlinks=False)
                        attrs = getattr(st, "st_file_attributes", 0)
                        if os.name == "nt" and (attrs & 0x400400):
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total_bytes += st.st_size
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
    seen_paths: set[str],
    cid: str,
    group: str,
    label: str,
    target: Path,
    *,
    contents_only: bool = True,
    note: str = "Safe temporary files that apps can rebuild if needed.",
    default_checked: bool = True,
    process_hint: str | None = None,
) -> None:
    try:
        if not target.exists():
            return
    except OSError:
        return
    norm_key = os.path.normcase(os.path.abspath(str(target)))
    if norm_key in seen_paths:
        return
    if is_personal_guarded_path(target):
        return
    if is_os_protected_path(target, allow_temp_contents=contents_only):
        return
    seen_paths.add(norm_key)
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


def _discover_dynamic_app_caches(
    local_app: Path,
    roaming_app: Path,
    add_fn,
) -> None:
    """Automatically find standard temp/cache folders inside apps installed on this PC."""
    skip_dirs = {
        "microsoft",
        "packages",
        "temp",
        "programs",
        "google",
        "mozilla",
        "bravesoftware",
        "opera software",
        "claude-data",
        "claude",
        "code",
        "cursor",
        "notion",
        "discord",
        "slack",
        "spotify",
        "zoom",
        "canva",
        "githubdesktop",
        "drivesweep",
    }
    cache_subnames = (
        ("Cache", "Temporary Cache"),
        ("Code Cache", "App Speed Cache"),
        ("GPUCache", "Graphics Cache"),
        ("logs", "Diagnostic Logs"),
        (os.path.join("Crashpad", "reports"), "Crash Reports"),
    )

    for scope_name, root in (("local", local_app), ("roaming", roaming_app)):
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for app_dir in entries:
            if not app_dir.is_dir():
                continue
            low = app_dir.name.lower()
            if low in skip_dirs or low.startswith("."):
                continue
            if low.endswith("-updater"):
                add_fn(
                    f"dyn-{scope_name}-upd-{low}",
                    "Desktop Apps",
                    f"{app_dir.name} Leftover Installers",
                    app_dir,
                    contents_only=False,
                    note="Old update installer files downloaded automatically in the background.",
                )
                continue
            for sub_rel, sub_label in cache_subnames:
                cand = app_dir / sub_rel
                try:
                    exists = cand.exists()
                except OSError:
                    continue
                if exists:
                    add_fn(
                        f"dyn-{scope_name}-{low}-{sub_label.lower().replace(' ', '-')}",
                        "Desktop Apps",
                        f"{app_dir.name} ({sub_label})",
                        cand,
                        note=f"Temporary files for {app_dir.name}. Your logins and saved work stay safe.",
                        process_hint=app_dir.name,
                    )


def _discover_windows_candidates() -> list[SmartPresetCandidate]:
    home = Path.home()
    local_app = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roaming_app = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    temp_dir = Path(os.environ.get("TEMP", local_app / "Temp"))
    windir = Path(os.environ.get("WINDIR", "C:\\Windows"))
    win_temp = windir / "Temp"
    program_data = Path(os.environ.get("ProgramData", "C:\\ProgramData"))

    items: list[SmartPresetCandidate] = []
    seen_paths: set[str] = set()
    add = lambda *a, **kw: _safe_add(items, seen_paths, *a, **kw)  # noqa: E731

    # 1. Windows & System Temp (useful on every Windows PC)
    add(
        "user-temp",
        "Windows & Temp",
        "User Temporary Files",
        temp_dir,
        note="Temporary files created by apps. Files currently in use are skipped automatically.",
    )
    add(
        "win-temp",
        "Windows & Temp",
        "Windows System Temporary Files",
        win_temp,
        note="System-wide temporary files in Windows\\Temp.",
    )
    add(
        "win-update-cache",
        "Windows & Temp",
        "Windows Update Download Cache",
        windir / "SoftwareDistribution" / "Download",
        note="Old Windows Update installer downloads. Windows re-downloads anything needed later.",
    )
    add(
        "win-delivery-opt",
        "Windows & Temp",
        "Windows Update Delivery Cache",
        windir
        / "ServiceProfiles"
        / "NetworkService"
        / "AppData"
        / "Local"
        / "Microsoft"
        / "Windows"
        / "DeliveryOptimization"
        / "Cache",
        note="Cached Windows Update files shared on your network.",
    )
    add(
        "win-crash-dumps",
        "Windows & Temp",
        "App Crash Dump Files",
        local_app / "CrashDumps",
        note="Diagnostic snapshots saved when an app crashes.",
    )
    add(
        "win-wer-user",
        "Windows & Temp",
        "User Error Reports",
        local_app / "Microsoft" / "Windows" / "WER" / "ReportArchive",
        note="Old Windows Error Reporting files.",
    )
    add(
        "win-wer-system-archive",
        "Windows & Temp",
        "System Error Report Archive",
        program_data / "Microsoft" / "Windows" / "WER" / "ReportArchive",
        note="System crash and error report archive.",
    )
    add(
        "win-wer-system-queue",
        "Windows & Temp",
        "Pending System Error Reports",
        program_data / "Microsoft" / "Windows" / "WER" / "ReportQueue",
        note="Queued Windows error report files.",
    )
    add(
        "win-inet-cache",
        "Windows & Temp",
        "Windows Web Temporary Files",
        local_app / "Microsoft" / "Windows" / "INetCache",
        note="Temporary web cache used by Windows components.",
    )
    add(
        "dx-shader-cache",
        "Windows & Temp",
        "DirectX Graphics Cache",
        local_app / "D3DSCache",
        note="Graphics shader cache rebuilt automatically by games and apps.",
    )
    add(
        "nvidia-dx-cache",
        "Windows & Temp",
        "NVIDIA Graphics Shader Cache",
        local_app / "NVIDIA" / "DXCache",
        note="NVIDIA graphics cache rebuilt automatically when needed.",
    )
    add(
        "nvidia-gl-cache",
        "Windows & Temp",
        "NVIDIA OpenGL Cache",
        local_app / "NVIDIA" / "GLCache",
        note="NVIDIA OpenGL cache rebuilt automatically when needed.",
    )
    add(
        "amd-dx-cache",
        "Windows & Temp",
        "AMD Graphics Shader Cache",
        local_app / "AMD" / "DxCache",
        note="AMD graphics cache rebuilt automatically when needed.",
    )
    add(
        "intel-shader-cache",
        "Windows & Temp",
        "Intel Graphics Cache",
        local_app / "Intel" / "ShaderCache",
        note="Intel graphics cache rebuilt automatically when needed.",
    )
    add(
        "win-minidump",
        "Windows & Temp",
        "Windows BSOD Minidump Files",
        windir / "Minidump",
        note="Old Windows crash dump snapshots.",
    )
    add(
        "win-live-kernel",
        "Windows & Temp",
        "Windows Live Kernel Reports",
        windir / "LiveKernelReports",
        note="Diagnostic kernel crash reports saved by Windows.",
    )
    add(
        "win-cbs-logs",
        "Windows & Temp",
        "Windows Servicing Logs (CBS)",
        windir / "Logs" / "CBS",
        note="Windows Update servicing log files.",
    )
    add(
        "win-dism-logs",
        "Windows & Temp",
        "Windows DISM Logs",
        windir / "Logs" / "DISM",
        note="Component store servicing logs.",
    )
    sys_drive_root = Path(os.environ.get("SystemDrive", "C:") + "\\")
    win_old = sys_drive_root / "Windows.old"
    if win_old.exists():
        add(
            "win-old-backup",
            "Windows & Temp",
            "Previous Windows Installation (Windows.old)",
            win_old,
            contents_only=False,
            note="Backup of your prior Windows install. Review before cleaning if you no longer need rollback.",
            default_checked=False,
        )
    add(
        "winget-temp",
        "Windows & Temp",
        "Windows Package Manager (WinGet) Temp",
        temp_dir / "WinGet",
        note="Downloaded WinGet installer packages already installed.",
    )
    add(
        "winget-store-cache",
        "Windows & Temp",
        "App Installer Local Cache",
        local_app / "Packages" / "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" / "LocalCache",
        note="Downloaded WinGet manifest & installer cache.",
    )
    add(
        "squirrel-temp",
        "Windows & Temp",
        "Desktop App Installer Temp (SquirrelTemp)",
        local_app / "SquirrelTemp",
        note="Leftover temporary installer extraction files.",
    )

    uwp_packages = local_app / "Packages"
    if uwp_packages.exists():
        try:
            for pkg in uwp_packages.iterdir():
                if not pkg.is_dir():
                    continue
                short_name = pkg.name.split("_")[0]
                for sub_rel, sub_label in (("TempState", "Temp Files"), (os.path.join("AC", "INetCache"), "Web Cache")):
                    cand = pkg / sub_rel
                    if cand.exists():
                        add(
                            f"uwp-{pkg.name}-{sub_label.lower().replace(' ', '-')}",
                            "Windows & Temp",
                            f"Microsoft Store: {short_name} ({sub_label})",
                            cand,
                            note=f"Temporary files for the {short_name} Store app.",
                        )
        except OSError:
            pass

    # 2. Web Browsers (Chrome, Edge, Brave, Vivaldi, Firefox, Opera)
    chromium_browsers = [
        ("chrome", "Google Chrome", local_app / "Google" / "Chrome" / "User Data", "chrome"),
        ("edge", "Microsoft Edge", local_app / "Microsoft" / "Edge" / "User Data", "msedge"),
        ("brave", "Brave Browser", local_app / "BraveSoftware" / "Brave-Browser" / "User Data", "brave"),
        ("vivaldi", "Vivaldi Browser", local_app / "Vivaldi" / "User Data", "vivaldi"),
    ]
    for slug, bname, ud_path, proc in chromium_browsers:
        if not ud_path.exists():
            continue
        try:
            for prof in ud_path.iterdir():
                if prof.is_dir() and (prof.name == "Default" or prof.name.startswith("Profile ")):
                    for sub, label in (
                        ("Cache", "Temporary Web Files"),
                        ("Code Cache", "Page Speed Cache"),
                        ("GPUCache", "Graphics Cache"),
                        ("DawnWebGPUCache", "WebGPU Shader Cache"),
                        ("DawnGraphiteCache", "Graphics Pipeline Cache"),
                        (os.path.join("Service Worker", "CacheStorage"), "Offline Site Cache"),
                        ("File System", "Site File System Cache"),
                        ("Shared Dictionary", "Compression Cache"),
                    ):
                        add(
                            f"{slug}-{prof.name}-{label.lower().replace(' ', '-')}",
                            "Web Browsers",
                            f"{bname} ({prof.name}) - {label}",
                            prof / sub,
                            note="Temporary browser files only. Saved passwords, bookmarks, and history stay untouched.",
                            process_hint=proc,
                        )
        except OSError:
            pass
        for extra, label in (
            ("OptGuideOnDeviceModel", "On-Device AI Models"),
            ("OptGuideOnDeviceClassifierModel", "Content Classifier Models"),
            ("screen_ai", "Screen Reader AI Cache"),
            ("Snapshots", "Old Version Backups"),
            ("component_crx_cache", "Component Update Downloads"),
        ):
            add(
                f"{slug}-{extra.lower()}",
                "Web Browsers",
                f"{bname} ({label})",
                ud_path / extra,
                note="Cached browser updates or downloaded components.",
                process_hint=proc,
            )
    add(
        "google-updater",
        "Web Browsers",
        "Google Update Leftover Files",
        local_app / "Google" / "GoogleUpdater",
        note="Old Chrome and Google updater downloads.",
    )

    ff_profiles = local_app / "Mozilla" / "Firefox" / "Profiles"
    if ff_profiles.exists():
        for prof in ff_profiles.iterdir():
            if prof.is_dir():
                add(
                    f"firefox-{prof.name}-cache",
                    "Web Browsers",
                    f"Firefox ({prof.name}) Temporary Web Files",
                    prof / "cache2",
                    note="Temporary browser files only. Bookmarks, passwords, and tabs stay untouched.",
                    process_hint="firefox",
                )

    for opera_name in ("Opera Stable", "Opera GX Stable"):
        opera_dir = local_app / "Opera Software" / opera_name
        add(
            f"opera-{opera_name.lower().replace(' ', '-')}",
            "Web Browsers",
            f"{opera_name} Temporary Web Files",
            opera_dir / "Cache",
            note="Temporary browser files only. Saved logins and bookmarks stay untouched.",
            process_hint="opera",
        )

    # 3. Everyday Desktop Apps (Teams, Discord, Spotify, Slack, Zoom, Office, Outlook, Steam, Notion, Canva)
    add(
        "teams-new-cache",
        "Desktop Apps",
        "Microsoft Teams Cache",
        local_app / "Packages" / "MSTeams_8wekyb3d8bbwe" / "LocalCache" / "Microsoft" / "MSTeams" / "EBWebView" / "Default" / "Cache",
        note="Temporary Teams cache. Chats and account login stay safe.",
        process_hint="ms-teams",
    )
    add(
        "teams-classic-cache",
        "Desktop Apps",
        "Microsoft Teams (Classic) Cache",
        roaming_app / "Microsoft" / "Teams" / "Cache",
        note="Temporary Teams cache.",
        process_hint="Teams",
    )
    for sub in ("Cache", "Code Cache", "GPUCache"):
        add(
            f"discord-{sub.lower().replace(' ', '-')}",
            "Desktop Apps",
            f"Discord ({sub})",
            roaming_app / "discord" / sub,
            note="Temporary Discord media and app cache. Chats and login stay safe.",
            process_hint="Discord",
        )
        add(
            f"slack-{sub.lower().replace(' ', '-')}",
            "Desktop Apps",
            f"Slack ({sub})",
            roaming_app / "Slack" / sub,
            note="Temporary Slack cache. Workspaces stay logged in.",
            process_hint="slack",
        )
        add(
            f"canva-{sub.lower().replace(' ', '-')}",
            "Desktop Apps",
            f"Canva ({sub})",
            roaming_app / "Canva" / sub,
            note="Temporary Canva design preview cache.",
            process_hint="Canva",
        )
    add(
        "spotify-storage",
        "Desktop Apps",
        "Spotify Temporary Song Cache",
        local_app / "Spotify" / "Storage",
        note="Cached audio previews downloaded while streaming (excludes your playlists).",
        default_checked=False,
        process_hint="Spotify",
    )
    add(
        "spotify-data",
        "Desktop Apps",
        "Spotify Browser Cache",
        local_app / "Spotify" / "Data",
        note="Cached album art and interface files.",
        process_hint="Spotify",
    )
    add(
        "zoom-downloads",
        "Desktop Apps",
        "Zoom Update Installers",
        roaming_app / "Zoom" / "ZoomDownload",
        note="Temporary installer files downloaded by Zoom.",
    )
    add(
        "office-cache",
        "Desktop Apps",
        "Microsoft Office Document Cache",
        local_app / "Microsoft" / "Office" / "16.0" / "OfficeFileCache",
        note="Local temporary upload/download cache for Word, Excel, and PowerPoint.",
    )
    add(
        "outlook-cache",
        "Desktop Apps",
        "Outlook App Web Cache",
        local_app / "Microsoft" / "Olk" / "ebwebview" / "Default" / "Cache",
        note="Temporary Outlook display cache. Emails stay safe on your server.",
        process_hint="olk",
    )
    add(
        "outlook-code-cache",
        "Desktop Apps",
        "Outlook App Speed Cache",
        local_app / "Microsoft" / "Olk" / "ebwebview" / "Default" / "Code Cache",
        note="Temporary Outlook script cache.",
        process_hint="olk",
    )
    add(
        "steam-htmlcache",
        "Desktop Apps",
        "Steam Store Browser Cache",
        local_app / "Steam" / "htmlcache" / "Cache",
        note="Temporary Steam store page cache. Installed games are untouched.",
        process_hint="steam",
    )
    add(
        "epic-webcache",
        "Desktop Apps",
        "Epic Games Launcher Web Cache",
        local_app / "EpicGamesLauncher" / "Saved" / "webcache",
        note="Temporary Epic Store cache. Installed games are untouched.",
        process_hint="EpicGamesLauncher",
    )

    notion_base = roaming_app / "Notion" / "Partitions" / "notion"
    if notion_base.exists():
        for sub in ("Service Worker", "Cache", "Code Cache", "GPUCache", "DawnWebGPUCache", "DawnGraphiteCache", "Shared Dictionary"):
            add(
                f"notion-{sub.lower().replace(' ', '-')}",
                "Desktop Apps",
                f"Notion ({sub})",
                notion_base / sub,
                note="Temporary Notion cache. Your workspace and login stay safe.",
                process_hint="Notion",
            )

    bt_base = roaming_app / "BitTorrent Web" / "btweb.exe.WebView2" / "EBWebView" / "Default"
    add("bt-cache", "Desktop Apps", "BitTorrent Web Cache", bt_base / "Cache", note="Temporary browser view cache.")
    add("bt-code-cache", "Desktop Apps", "BitTorrent Web Speed Cache", bt_base / "Code Cache", note="Temporary browser script cache.")

    openwa_sessions = local_app / "Docker" / "OpenWA" / "data" / "sessions"
    if openwa_sessions.exists():
        try:
            for sess in openwa_sessions.iterdir():
                if not sess.is_dir():
                    continue
                default_dir = sess / "Default"
                if not default_dir.is_dir():
                    continue
                for sub, label in (
                    ("Cache", "Browser Cache"),
                    ("Code Cache", "Script Cache"),
                    ("Service Worker", "Service Worker Cache"),
                ):
                    add(
                        f"openwa-{sess.name.lower()}-{sub.lower().replace(' ', '-')}",
                        "Desktop Apps",
                        f"OpenWA ({sess.name}) {label}",
                        default_dir / sub,
                        note="Temporary OpenWA Chromium cache.",
                    )
        except OSError:
            pass

    adobe_common = roaming_app / "Adobe" / "Common"
    if adobe_common.exists():
        for sub, label in (
            ("Media Cache Files", "Adobe Media Cache Files"),
            ("Media Cache", "Adobe Media Peak Cache"),
        ):
            add(
                f"adobe-{sub.lower().replace(' ', '-')}",
                "Desktop Apps",
                label,
                adobe_common / sub,
                note="Rebuilt by Premiere/After Effects on next project open.",
                default_checked=False,
            )

    # Dynamically catch any other installed apps on this user's machine!
    _discover_dynamic_app_caches(local_app, roaming_app, add)

    # 4. AI Coding Tools (if installed on this PC)
    claude_data = local_app / "Claude-Data"
    if claude_data.exists():
        for profile in claude_data.iterdir():
            if not profile.is_dir():
                continue
            tag = profile.name
            add(
                f"claude-vm-{tag}",
                "AI & Coding Tools",
                f"Claude Desktop VM Files ({tag})",
                profile / "vm_bundles",
                note="Downloaded Claude virtual machine bundles (often large). Close Claude first.",
                process_hint="Claude",
            )
            add(
                f"claude-cache-{tag}",
                "AI & Coding Tools",
                f"Claude Desktop Cache ({tag})",
                profile / "Cache",
                note="Temporary Claude app cache. Your chats and login stay safe.",
                process_hint="Claude",
            )
            add(
                f"claude-code-cache-{tag}",
                "AI & Coding Tools",
                f"Claude Desktop Speed Cache ({tag})",
                profile / "Code Cache",
                note="Temporary app script cache.",
                process_hint="Claude",
            )
            add(
                f"claude-logs-{tag}",
                "AI & Coding Tools",
                f"Claude Desktop Logs ({tag})",
                profile / "logs",
                note="Diagnostic log files.",
                process_hint="Claude",
            )

    claude_roaming = roaming_app / "Claude"
    if claude_roaming.exists():
        for sub in ("Cache", "Code Cache", "GPUCache", "logs"):
            add(
                f"claude-roaming-{sub.lower().replace(' ', '-')}",
                "AI & Coding Tools",
                f"Claude App ({sub})",
                claude_roaming / sub,
                note="Temporary Claude app cache/logs. Settings stay safe.",
                process_hint="Claude",
            )

    claude_cli = home / ".claude"
    if claude_cli.exists():
        add(
            "claude-cli-cache",
            "AI & Coding Tools",
            "Claude Code CLI Cache",
            claude_cli / "cache",
            note="Temporary Claude Code cache (settings, plugins, and projects stay safe).",
        )
        add(
            "claude-cli-debug",
            "AI & Coding Tools",
            "Claude Code Debug Logs",
            claude_cli / "debug",
            note="Old diagnostic debug logs.",
        )
        add(
            "claude-cli-snapshots",
            "AI & Coding Tools",
            "Claude Code Terminal Snapshots",
            claude_cli / "shell-snapshots",
            note="Old terminal environment snapshots.",
            default_checked=False,
        )
        add(
            "claude-cli-file-history",
            "AI & Coding Tools",
            "Claude Code Edit Backups",
            claude_cli / "file-history",
            note="Backup checkpoints from past Claude Code edits (keep unchecked if you need undo).",
            default_checked=False,
        )

    add(
        "codex-runtimes",
        "AI & Coding Tools",
        "OpenAI Codex Runtime Cache",
        home / ".cache" / "codex-runtimes",
        note="Downloaded Codex runtime files.",
        process_hint="codex",
    )

    # 5. Developer Editors & Package Caches (if installed on this PC)
    vscode = roaming_app / "Code"
    add(
        "vscode-vsix",
        "Dev Editors & Packages",
        "VS Code Old Extension Installers",
        vscode / "CachedExtensionVSIXs",
        note="Old downloaded extension installers. Installed extensions stay intact.",
    )
    add("vscode-cache", "Dev Editors & Packages", "VS Code Temporary Cache", vscode / "Cache", note="Temporary editor cache.", process_hint="Code")
    add("vscode-cached-data", "Dev Editors & Packages", "VS Code Speed Cache", vscode / "CachedData", note="Rebuilt automatically on launch.", process_hint="Code")
    vscode_web = vscode / "WebStorage"
    if vscode_web.exists():
        try:
            for sub in vscode_web.rglob("CacheStorage"):
                if sub.is_dir():
                    add(
                        f"vscode-webstorage-{abs(hash(str(sub))) & 0xFFFF:04x}",
                        "Dev Editors & Packages",
                        f"VS Code WebStorage ({sub.parent.name})",
                        sub,
                        note="Extension webview CacheStorage rebuilt automatically.",
                        process_hint="Code",
                    )
        except OSError:
            pass

    cursor = roaming_app / "Cursor"
    if cursor.exists():
        add(
            "cursor-vsix",
            "Dev Editors & Packages",
            "Cursor Old Extension Installers",
            cursor / "CachedExtensionVSIXs",
            note="Old downloaded extension installers.",
        )
        add("cursor-cache", "Dev Editors & Packages", "Cursor Temporary Cache", cursor / "Cache", note="Temporary editor cache.", process_hint="Cursor")
        add("cursor-cached-data", "Dev Editors & Packages", "Cursor Speed Cache", cursor / "CachedData", note="Rebuilt automatically on launch.", process_hint="Cursor")
        cursor_web = cursor / "WebStorage"
        if cursor_web.exists():
            try:
                for sub in cursor_web.rglob("CacheStorage"):
                    if sub.is_dir():
                        add(
                            f"cursor-webstorage-{abs(hash(str(sub))) & 0xFFFF:04x}",
                            "Dev Editors & Packages",
                            f"Cursor WebStorage ({sub.parent.name})",
                            sub,
                            note="Extension webview CacheStorage rebuilt automatically.",
                            process_hint="Cursor",
                        )
            except OSError:
                pass

    gh_desktop = local_app / "GitHubDesktop"
    add("gh-packages", "Dev Editors & Packages", "GitHub Desktop Old Updates", gh_desktop / "packages", note="Old downloaded app update files.")
    if gh_desktop.exists():
        app_dirs = sorted([d for d in gh_desktop.iterdir() if d.is_dir() and d.name.startswith("app-")], key=lambda p: p.name, reverse=True)
        for old_app in app_dirs[1:]:
            add(
                f"gh-old-{old_app.name}",
                "Dev Editors & Packages",
                f"GitHub Desktop Old Version ({old_app.name})",
                old_app,
                contents_only=False,
                note="Older GitHub Desktop version replaced by a newer update.",
            )

    add("uv-cache", "Dev Editors & Packages", "Python uv Download Cache", local_app / "uv" / "cache", note="Downloaded Python packages that re-download automatically if needed.")
    add("pip-cache", "Dev Editors & Packages", "Python pip Download Cache", local_app / "pip" / "cache", note="Saved Python package installers.")
    add("bun-cache", "Dev Editors & Packages", "Bun Package Cache", home / ".bun" / "install" / "cache", note="Saved Bun package downloads.")
    add("npm-local-cache", "Dev Editors & Packages", "Node npm Cache (Local)", local_app / "npm-cache", note="Saved npm package downloads.")
    add("npm-home-cache", "Dev Editors & Packages", "Node npm Cache (Home)", home / "npm-cache", note="Saved npm package downloads.")
    add("npm-underscore-cache", "Dev Editors & Packages", "Node npm Cache (_cacache)", home / ".npm" / "_cacache", note="Saved npm package downloads.")
    add("hf-cache", "Dev Editors & Packages", "HuggingFace AI Model Cache", home / ".cache" / "huggingface", note="Large downloaded AI models (re-download on demand if removed).", default_checked=False)
    add("torch-cache", "Dev Editors & Packages", "PyTorch AI Model Cache", home / ".cache" / "torch", note="Cached PyTorch model downloads.", default_checked=False)
    add("playwright-browsers", "Dev Editors & Packages", "Playwright Test Browsers", local_app / "ms-playwright", note="Downloaded test browsers.", default_checked=False)
    add("gradle-caches", "Dev Editors & Packages", "Gradle Build Cache", home / ".gradle" / "caches", note="Cached Java and Android build libraries.", default_checked=False)
    add("nuget-v3-cache", "Dev Editors & Packages", "NuGet HTTP Cache", local_app / "NuGet" / "v3-cache", note="Cached .NET package index files.")
    add("nuget-packages", "Dev Editors & Packages", "NuGet Package Cache", home / ".nuget" / "packages", note="Downloaded .NET packages (restored on build).", default_checked=False)
    add("yarn-cache", "Dev Editors & Packages", "Yarn Package Cache", local_app / "Yarn" / "Cache", note="Saved Yarn package downloads.")
    add("pnpm-store", "Dev Editors & Packages", "pnpm Content Store", local_app / "pnpm" / "store", note="Shared pnpm package store (re-links cleanly if cleared).", default_checked=False)
    add("go-build-cache", "Dev Editors & Packages", "Go Build Cache", local_app / "go-build", note="Compiled Go build cache.")
    add("cargo-reg-cache", "Dev Editors & Packages", "Rust Cargo Registry Cache", home / ".cargo" / "registry" / "cache", note="Downloaded Rust crate archives.")
    jetbrains_root = local_app / "JetBrains"
    if jetbrains_root.exists():
        try:
            for jb_dir in jetbrains_root.iterdir():
                c_dir = jb_dir / "caches"
                if jb_dir.is_dir() and c_dir.is_dir():
                    add(
                        f"jetbrains-{jb_dir.name.lower()}-caches",
                        "Dev Editors & Packages",
                        f"JetBrains {jb_dir.name} Caches",
                        c_dir,
                        note="IDE index caches rebuilt automatically on launch.",
                        default_checked=False,
                    )
        except OSError:
            pass

    return items


def _discover_unix_candidates() -> list[SmartPresetCandidate]:
    """Comprehensive Smart Scan presets for macOS and Linux."""
    home = Path.home()
    is_mac = sys.platform == "darwin"
    cache_root = home / "Library" / "Caches" if is_mac else Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    config_root = home / "Library" / "Application Support" if is_mac else Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))

    items: list[SmartPresetCandidate] = []
    seen_paths: set[str] = set()
    add = lambda *a, **kw: _safe_add(items, seen_paths, *a, **kw)  # noqa: E731

    add("uv-cache", "Dev Editors & Packages", "Python uv Download Cache", cache_root / "uv", note="Saved Python package downloads.")
    add("pip-cache", "Dev Editors & Packages", "Python pip Download Cache", cache_root / "pip", note="Saved pip package downloads.")
    add("bun-cache", "Dev Editors & Packages", "Bun Package Cache", home / ".bun" / "install" / "cache", note="Saved Bun package downloads.")
    add("npm-cache", "Dev Editors & Packages", "Node npm Cache", home / ".npm" / "_cacache", note="Saved npm package downloads.")
    add("hf-cache", "Dev Editors & Packages", "HuggingFace AI Model Cache", home / ".cache" / "huggingface", note="Large downloaded AI models.", default_checked=False)
    add("torch-cache", "Dev Editors & Packages", "PyTorch AI Model Cache", home / ".cache" / "torch", note="Cached PyTorch model downloads.", default_checked=False)
    add("gradle-caches", "Dev Editors & Packages", "Gradle Build Cache", home / ".gradle" / "caches", note="Cached Java and Android build libraries.", default_checked=False)
    add("playwright-browsers", "Dev Editors & Packages", "Playwright Test Browsers", cache_root / "ms-playwright", note="Downloaded test browsers.", default_checked=False)

    add("codex-runtimes", "AI & Coding Tools", "OpenAI Codex Runtime Cache", home / ".cache" / "codex-runtimes", note="Downloaded Codex runtime files.", process_hint="codex")
    claude_cli = home / ".claude"
    if claude_cli.exists():
        add("claude-cli-cache", "AI & Coding Tools", "Claude Code CLI Cache", claude_cli / "cache", note="Temporary Claude Code cache.")
        add("claude-cli-debug", "AI & Coding Tools", "Claude Code Debug Logs", claude_cli / "debug", note="Old diagnostic debug logs.")
        add("claude-cli-snapshots", "AI & Coding Tools", "Claude Code Terminal Snapshots", claude_cli / "shell-snapshots", note="Old terminal snapshots.", default_checked=False)
        add("claude-cli-history", "AI & Coding Tools", "Claude Code Edit Backups", claude_cli / "file-history", note="Backup checkpoints from past edits.", default_checked=False)

    for sub in ("Cache", "Code Cache", "GPUCache", "vm_bundles", "logs"):
        add(f"claude-app-{sub.lower().replace(' ', '-')}", "AI & Coding Tools", f"Claude Desktop ({sub})", config_root / "Claude" / sub, note="Temporary Claude Desktop files.", process_hint="Claude")

    for app_dir, label, proc in (("Code", "VS Code", "code"), ("Cursor", "Cursor", "cursor")):
        base = config_root / app_dir
        add(f"{app_dir.lower()}-cache", "Dev Editors & Packages", f"{label} Temporary Cache", base / "Cache", note=f"Temporary {label} cache.", process_hint=proc)
        add(f"{app_dir.lower()}-cached-data", "Dev Editors & Packages", f"{label} Speed Cache", base / "CachedData", note=f"Rebuilt automatically on launch.", process_hint=proc)
        add(f"{app_dir.lower()}-vsix", "Dev Editors & Packages", f"{label} Old Extension Installers", base / "CachedExtensionVSIXs", note="Old downloaded extension installers.")

    if is_mac:
        add("homebrew-cache", "Dev Editors & Packages", "Homebrew Download Cache", cache_root / "Homebrew", note="Saved Homebrew package archives.")
        add("xcode-derived", "Dev Editors & Packages", "Xcode Build Cache", home / "Library" / "Developer" / "Xcode" / "DerivedData", note="Xcode build intermediates and indexes.", default_checked=False)
        add("chrome-cache", "Web Browsers", "Google Chrome Temporary Cache", cache_root / "Google" / "Chrome", note="Temporary browser files.", process_hint="Google Chrome")
        add("mac-logs", "Windows & Temp", "App Diagnostic Logs", home / "Library" / "Logs", note="Old application log files.")
    else:
        add("chrome-cache", "Web Browsers", "Google Chrome Temporary Cache", cache_root / "google-chrome", note="Temporary browser files.", process_hint="chrome")
        add("chromium-cache", "Web Browsers", "Chromium Temporary Cache", cache_root / "chromium", note="Temporary browser files.", process_hint="chromium")
        add("thumbnails", "Windows & Temp", "Image Thumbnail Cache", cache_root / "thumbnails", note="Cached file manager thumbnail previews.")

    return items


def scan_smart_presets(
    exclusions: list[str] | None = None,
    custom_presets: list[dict] | None = None,
) -> dict:
    """Scan all smart presets on the current user's system and return sizes, warnings, & exclusions."""
    candidates = _discover_windows_candidates() if os.name == "nt" else _discover_unix_candidates()
    custom_list = custom_presets if custom_presets is not None else get_custom_presets()
    seen_norm = {os.path.normcase(os.path.abspath(c.path)) for c in candidates}
    for custom in custom_list:
        raw_path = str(custom.get("path", "")).strip()
        if not raw_path:
            continue
        target = Path(raw_path)
        norm_key = os.path.normcase(os.path.abspath(str(target)))
        if norm_key in seen_norm:
            continue
        contents_only = bool(custom.get("contents_only", True))
        if is_os_protected_path(target, allow_temp_contents=contents_only):
            continue
        seen_norm.add(norm_key)
        candidates.append(
            SmartPresetCandidate(
                id=str(custom.get("id", f"custom_{abs(hash(norm_key)) & 0xFFFFFFFF:08x}")),
                group="Custom Folders",
                label=str(custom.get("name") or target.name or str(target)),
                path=str(target),
                contents_only=contents_only,
                safety_note="User-added custom cleanup folder. Review before cleaning.",
                default_checked=False,
                process_hint=None,
                is_docker_prune=False,
                is_custom=True,
            )
        )

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

            if not item.is_custom and size_bytes <= 0 and file_count == 0:
                continue

            excluded = is_path_excluded(item.path, ex_list)
            risk_level = "safe" if item.default_checked else "caution"
            risk_reason = (
                "Safe temporary files that can be rebuilt automatically."
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
                    is_custom=item.is_custom,
                )
            )

    docker_running = _is_process_running(running_names, "com.docker.backend") or _is_process_running(running_names, "dockerd")
    if docker_running and shutil.which("docker"):
        results.append(
            SmartPresetResult(
                id="docker-builder-prune",
                group="Dev Editors & Packages",
                label="Docker Build Cache",
                path="docker:builder",
                contents_only=False,
                size_bytes=0,
                size_human="Docker CLI",
                file_count=0,
                safety_note="Clears unused Docker build cache layers (running containers and saved images stay safe).",
                default_checked=False,
                excluded=False,
                risk_level="caution",
                risk_reason="Removes cached Docker image build layers (future builds may take longer once).",
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


def _scan_space_tree(
    space_label: str,
    root: Path,
    *,
    max_depth: int,
    max_entries: int,
    exclude_child_norms: set[str],
    min_file_bytes: int,
    min_folder_bytes: int,
) -> tuple[list[dict], list[dict]]:
    """Bounded fast walk of a space to collect large files and large subfolders."""
    root_str = os.path.abspath(os.path.normpath(str(root)))
    root_norm = os.path.normcase(root_str)
    os_root = to_os_path(root_str)
    if not os.path.exists(os_root) or not os.path.isdir(os_root):
        return [], []

    # Map normalized dir path -> [orig_path, parent_norm, size, files_cnt, latest_mtime]
    dir_stats: dict[str, list] = {}
    large_files: list[dict] = []
    stack: list[tuple[str, int]] = [(root_str, 0)]
    seen_entries = 0
    is_nt = os.name == "nt"
    now = time.time()

    while stack and seen_entries < max_entries:
        cur_dir, depth = stack.pop()
        cur_norm = os.path.normcase(cur_dir)
        own_size = 0
        own_files = 0
        latest_mtime = 0.0

        try:
            with os.scandir(to_os_path(cur_dir)) as it:
                for entry in it:
                    seen_entries += 1
                    if seen_entries > max_entries:
                        break
                    try:
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                        attrs = getattr(st, "st_file_attributes", 0)
                        if is_nt and (attrs & 0x400400):
                            continue
                        epath = os.path.join(cur_dir, entry.name)
                        enorm = os.path.normcase(epath)
                        if entry.is_dir(follow_symlinks=False):
                            if enorm in exclude_child_norms:
                                continue
                            if is_os_protected_path(epath, allow_temp_contents=False):
                                continue
                            if depth < max_depth:
                                stack.append((epath, depth + 1))
                            dir_stats.setdefault(enorm, [epath, cur_norm, 0, 0, st.st_mtime])
                        elif entry.is_file(follow_symlinks=False):
                            fsize = int(st.st_size)
                            fmtime = float(st.st_mtime)
                            own_size += fsize
                            own_files += 1
                            if fmtime > latest_mtime:
                                latest_mtime = fmtime
                            if fsize >= min_file_bytes and not is_os_protected_path(epath, allow_temp_contents=False):
                                age_days = max(0, int((now - fmtime) // 86400)) if fmtime > 0 else 0
                                mtime_str = datetime.fromtimestamp(fmtime).strftime("%Y-%m-%d") if fmtime > 0 else ""
                                risk = classify_path_risk(epath, is_dir=False, age_days=age_days)
                                large_files.append({
                                    "id": f"lgf-{abs(hash(enorm)) & 0xFFFFFFFF:08x}",
                                    "kind": "file",
                                    "space": space_label,
                                    "name": entry.name,
                                    "label": entry.name,
                                    "path": epath,
                                    "dir_path": cur_dir,
                                    "size_bytes": fsize,
                                    "size_human": format_bytes(fsize),
                                    "file_count": 1,
                                    "mtime": fmtime,
                                    "mtime_str": mtime_str,
                                    "age_days": age_days,
                                    "ext": os.path.splitext(entry.name)[1].lower(),
                                    "default_checked": False,
                                    "contents_only": False,
                                    "is_protected": risk["risk_level"] == "critical",
                                    "risk_level": risk["risk_level"],
                                    "risk_reason": risk["risk_reason"],
                                })
                    except OSError:
                        continue
        except OSError:
            continue

        info = dir_stats.setdefault(cur_norm, [cur_dir, None, 0, 0, latest_mtime])
        info[2] += own_size
        info[3] += own_files
        if latest_mtime > info[4]:
            info[4] = latest_mtime

    # Bottom-up size aggregation into immediate parent dirs
    for dnorm in sorted(dir_stats.keys(), key=lambda p: p.count(os.sep), reverse=True):
        if dnorm == root_norm:
            continue
        _orig, pnorm, sz, fcnt, mt = dir_stats[dnorm]
        if pnorm and pnorm in dir_stats:
            dir_stats[pnorm][2] += sz
            dir_stats[pnorm][3] += fcnt
            if mt > dir_stats[pnorm][4]:
                dir_stats[pnorm][4] = mt

    large_folders: list[dict] = []
    for dnorm, (orig, _pnorm, sz, fcnt, mt) in dir_stats.items():
        if dnorm == root_norm or sz < min_folder_bytes:
            continue
        if is_os_protected_path(orig, allow_temp_contents=False):
            continue
        age_days = max(0, int((now - mt) // 86400)) if mt > 0 else 0
        mtime_str = datetime.fromtimestamp(mt).strftime("%Y-%m-%d") if mt > 0 else ""
        risk = classify_path_risk(orig, is_dir=True, age_days=age_days)
        large_folders.append({
            "id": f"lgd-{abs(hash(dnorm)) & 0xFFFFFFFF:08x}",
            "kind": "folder",
            "space": space_label,
            "name": Path(orig).name or orig,
            "label": Path(orig).name or orig,
            "path": orig,
            "dir_path": str(Path(orig).parent),
            "size_bytes": sz,
            "size_human": format_bytes(sz),
            "file_count": fcnt,
            "mtime": mt,
            "mtime_str": mtime_str,
            "age_days": age_days,
            "default_checked": False,
            "contents_only": False,
            "is_protected": risk["risk_level"] == "critical",
            "risk_level": risk["risk_level"],
            "risk_reason": risk["risk_reason"],
        })

    return large_files, large_folders


def scan_large_spaces(
    exclusions: list[str] | None = None,
    *,
    min_file_mb: float = 25.0,
    min_folder_mb: float = 100.0,
    personal_roots: list[tuple[str, Path]] | None = None,
    drive_roots: list[Path] | None = None,
    include_home_custom: bool = True,
    max_files: int = 160,
    max_folders: int = 120,
) -> dict:
    """Discover large files and folders across Downloads, user spaces, and all drives for manual review."""
    min_file_bytes = int(max(1.0, float(min_file_mb)) * 1024 * 1024)
    min_folder_bytes = int(max(1.0, float(min_folder_mb)) * 1024 * 1024)
    ex_list = exclusions if exclusions is not None else get_exclusions()

    tasks: list[tuple[str, Path, int, int]] = []
    seen_roots: set[str] = set()
    known_norms: set[str] = set()

    p_roots = personal_roots if personal_roots is not None else get_all_personal_roots()
    for label, ppath in p_roots:
        try:
            if not ppath.exists():
                continue
            norm = os.path.normcase(os.path.abspath(str(ppath)))
            known_norms.add(norm)
            if norm in seen_roots:
                continue
            seen_roots.add(norm)
            depth = 7 if label == "Downloads" else 5
            tasks.append((label, ppath, depth, 60000))
        except OSError:
            continue

    home = Path.home()
    home_norm = os.path.normcase(os.path.abspath(str(home)))
    known_norms.add(os.path.normcase(os.path.abspath(str(home / "AppData"))))
    known_norms.add(os.path.normcase(os.path.abspath(str(home / "Users"))))
    if include_home_custom and home.exists():
        try:
            for entry in home.iterdir():
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                if entry.name.lower() in {"appdata", "contacts", "favorites", "links", "saved games", "searches", "crossdevice"}:
                    continue
                norm = os.path.normcase(os.path.abspath(str(entry)))
                if norm in seen_roots or norm in known_norms:
                    continue
                seen_roots.add(norm)
                tasks.append(("User Profile", entry, 4, 30000))
        except OSError:
            pass

    d_roots: list[Path]
    if drive_roots is not None:
        d_roots = list(drive_roots)
    else:
        d_roots = []
        for part in psutil.disk_partitions(all=False):
            if "cdrom" in (part.opts or "").lower():
                continue
            d_roots.append(Path(part.mountpoint))

    for droot in d_roots:
        try:
            if not droot.exists():
                continue
            norm = os.path.normcase(os.path.abspath(str(droot)))
            if norm in seen_roots:
                continue
            seen_roots.add(norm)
            label = f"Drive {str(droot).rstrip(chr(92) + '/')}"
            tasks.append((label, droot, 3, 50000))
        except OSError:
            continue

    exclude_children = {
        home_norm,
        os.path.normcase(os.path.abspath(str(home / "AppData"))),
        os.path.normcase(os.path.abspath(os.environ.get("WINDIR", "C:\\Windows"))),
    }
    sys_drive_users = os.path.normcase(os.path.abspath(os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "Users")))
    exclude_children.add(sys_drive_users)

    all_files: list[dict] = []
    all_folders: list[dict] = []
    seen_file_paths: set[str] = set()
    seen_folder_paths: set[str] = set()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {
            pool.submit(
                _scan_space_tree,
                lbl,
                rpath,
                max_depth=depth,
                max_entries=budget,
                exclude_child_norms=(exclude_children | (known_norms - {os.path.normcase(os.path.abspath(str(rpath)))})),
                min_file_bytes=min_file_bytes,
                min_folder_bytes=min_folder_bytes,
            ): lbl
            for lbl, rpath, depth, budget in tasks
        }
        for fut in as_completed(futs):
            try:
                flist, dlist = fut.result()
            except Exception:
                continue
            for item in flist:
                pnorm = os.path.normcase(item["path"])
                if pnorm in seen_file_paths:
                    continue
                seen_file_paths.add(pnorm)
                item["excluded"] = is_path_excluded(item["path"], ex_list)
                item["default_checked"] = False
                all_files.append(item)
            for item in dlist:
                pnorm = os.path.normcase(item["path"])
                if pnorm in seen_folder_paths:
                    continue
                seen_folder_paths.add(pnorm)
                item["excluded"] = is_path_excluded(item["path"], ex_list)
                item["default_checked"] = False
                all_folders.append(item)

    all_files.sort(key=lambda x: x["size_bytes"], reverse=True)
    all_folders.sort(key=lambda x: x["size_bytes"], reverse=True)
    files_out = all_files[:max_files]
    folders_out = all_folders[:max_folders]

    spaces = []
    for item in files_out + folders_out:
        if item["space"] not in spaces:
            spaces.append(item["space"])

    total_files_bytes = sum(x["size_bytes"] for x in files_out)
    total_folders_bytes = sum(x["size_bytes"] for x in folders_out)
    return {
        "files": files_out,
        "folders": folders_out,
        "spaces": spaces,
        "file_count": len(files_out),
        "folder_count": len(folders_out),
        "total_files_human": format_bytes(total_files_bytes),
        "total_folders_human": format_bytes(total_folders_bytes),
    }
