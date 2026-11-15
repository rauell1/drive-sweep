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

## Windows Verification & SmartScreen Signing
Unsigned desktop builds show the Windows SmartScreen "Unknown Publisher" prompt until code-signed with an Authenticode certificate. This repository includes a ready GitHub Actions workflow in `.github/workflows/ci-release.yml` with optional **Azure Trusted Signing** integration (configure `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_SIGNING_ENDPOINT`, `AZURE_SIGNING_ACCOUNT`, and `AZURE_SIGNING_PROFILE` secrets to sign tagged releases automatically).
