# DriveSweep

Interactive desktop utility for scanning drives and cleaning AI, developer, browser, and temporary files safely.

## Features
- **Smart AI & Dev Cleanup**: Automatically discovers caches for `uv`, `pip`, `bun`, `npm`, HuggingFace, PyTorch, Codex runtimes, Claude Desktop (`vm_bundles`, caches, logs), Claude Code (`~/.claude` cache/debug/snapshots/history), VS Code, Cursor, Notion, GitHub Desktop old versions, Chrome/Edge caches, app `*-updater` leftovers, Docker build cache, and Temp directories, while strictly excluding `Downloads`, `OneDrive`, and `CrossDevice`. Supports Windows, macOS, and Linux preset discovery.
- **Full-Drive Explorer**: Scan any drive (`C:`, `D:`, etc.) or custom folder, browse folder trees sorted by size/date, search across **all files** on the drive (filter by name, extension, min MB, and **age in days**), inspect largest files, and locate stale dev bloat (`node_modules`, `.venv`, `__pycache__`, `target`).
- **Safety & Choice**:
  - Launches elevated (**Administrator mode** via embedded UAC manifest `--uac-admin` and source auto-relaunch) for full drive and `C:\Windows\Temp` visibility.
  - **Recycle Bin (Safe)** (default) or **Permanent Delete** selector with permission modals for dangerous tasks.
  - Nested parent/child selection deduplication so folders and files inside them are never double-counted.
  - Windows long-path (`\\?\`) support, critical/caution/safe risk classification, **Always Keep** exclusions, and **Cleanup History** audit log.

## Run from Source (Windows)
```powershell
cd D:\coding\drive-sweep
.\.venv\Scripts\python.exe main.py
```
To bypass the UAC elevation prompt during local UI testing:
```powershell
.\.venv\Scripts\python.exe main.py --no-elevate
```

## Run Tests
```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Build Release Artifacts
```powershell
.\build.ps1
```
Produces:
- `dist\DriveSweep.exe` (portable single-file executable with UAC admin manifest, icon & version metadata)
- `dist\DriveSweep-win64.zip` (`--onedir` portable bundle)
- `dist\SHA256SUMS.txt` (SHA-256 checksums)
- `dist\DriveSweep-Setup-0.2.0.exe` (when Inno Setup `ISCC.exe` is installed, using [DriveSweep.iss](file:///D:/coding/drive-sweep/installer/DriveSweep.iss))

## Downloads
Prebuilt Windows executables and checksums are available on the [GitHub Releases](https://github.com/rauell1/drive-sweep/releases) page.

## Code Signing Policy
Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

### Project Team & Roles
- **Authors / Maintainers / Approvers:** [Roy Otieno (@rauell1)](https://github.com/rauell1)
- All source code changes are committed to the public repository and built cleanly through GitHub Actions workflows in [.github/workflows/ci-release.yml](https://github.com/rauell1/drive-sweep/blob/main/.github/workflows/ci-release.yml).

## Privacy Policy
DriveSweep runs completely offline on your local computer. It does not collect, transmit, sell, or share any personal data, file listings, or telemetry with any external server. Settings (`settings.json`), exclusion paths, and local cleanup logs (`history.jsonl`) are stored strictly in `%LOCALAPPDATA%\DriveSweep` (or `~/.config/DriveSweep`) on your device.

## Windows Verification & SmartScreen Signing
Unsigned desktop builds show the Windows SmartScreen "Unknown Publisher" prompt until code-signed with an Authenticode certificate. Tagged builds in `.github/workflows/ci-release.yml` support **SignPath Foundation** and **Azure Trusted Signing** so release executables and installers can be verified automatically.
