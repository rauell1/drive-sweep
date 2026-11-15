# DriveSweep

**Free up disk space safely on Windows.** DriveSweep scans your PC for temporary files, leftover app caches, browser caches, and oversized old files, then lets you review everything in plain visual charts before moving anything to the Recycle Bin.

- **Works on any Windows PC:** Automatically finds Windows temporary files, Windows Update leftovers, Microsoft Store app caches, browser caches (Edge, Chrome, Firefox, Brave, Opera), everyday app caches (Teams, Discord, Spotify, Slack, Zoom, Steam, Epic Games, Office), and any installed desktop app caches on your computer. Optional coding and AI caches are also detected automatically only if you use those tools.
- **Built for safety first:** Personal folders (`Downloads`, `OneDrive`, `Documents`, `Pictures`, `Videos`, `Music`, `Desktop`) are never auto-selected by Quick Clean. Use the **Large Files & Folders** view to inspect big files and folders across `Downloads`, user spaces, and all drives where every item stays unchecked until you manually select it. System files are locked so they cannot be removed accidentally, important files ask for your confirmation first, and cleanup defaults to **Recycle Bin (Safe)** so you can restore files anytime.
- **Light and Dark Mode:** Switch themes anytime from the top-left corner.
- **100% private and offline:** Every scan, setting, and cleanup record stays on your own computer. Nothing is uploaded anywhere.

---

## Step-by-Step Installation (Windows)

Choose **Option A** (standard Windows installer, recommended for most users) or **Option B** (portable app with no installation).

### Option A: Windows Installer (Recommended)

1. Open the **[GitHub Releases](https://github.com/rauell1/drive-sweep/releases)** page.
2. Under the latest release (**Assets** section at the bottom), click **`DriveSweep-Setup-0.5.0.exe`** (or the newest version listed) to download it.
3. Open your `Downloads` folder and double-click the downloaded `DriveSweep-Setup-...exe` file.
4. **If Windows shows a "Windows protected your PC" (SmartScreen) blue popup:**
   - This appears on new open-source Windows apps until code signing is complete. You can verify the file checksum against `SHA256SUMS.txt` on the Releases page if you wish.
   - Click **More info**, then click **Run anyway**.
5. **Accept the Administrator prompt (UAC):** Click **Yes** when Windows asks if the app can make changes to your device. DriveSweep needs Administrator access so it can clean system-level temp folders (such as `C:\Windows\Temp` and Windows Update download caches) and read full drive sizes accurately.
6. Follow the setup wizard (**Next -> Install -> Finish**). Leave **Launch DriveSweep** checked to open the app right away, or open **DriveSweep** anytime from your Start Menu or Desktop shortcut.

### Option B: Portable Version (No Installer)

1. Open the **[GitHub Releases](https://github.com/rauell1/drive-sweep/releases)** page.
2. Under **Assets**, download **`DriveSweep.exe`** (single-file app) or **`DriveSweep-win64.zip`** (unzip it to any folder you like).
3. Double-click **`DriveSweep.exe`**, click **More info -> Run anyway** if SmartScreen appears, and click **Yes** on the Administrator prompt.

---

## How to Use DriveSweep

### 1. Quick Clean (Easiest Way to Free Space)
1. When DriveSweep opens, **Quick Clean** scans your PC automatically for safe, regenerable temporary files and app caches.
2. Each item is grouped clearly (`Windows & Temp`, `Web Browsers`, `Desktop Apps`, `AI & Coding Tools`, `Dev Editors & Packages`, `Custom Folders`, `Other App Caches`) and labeled **Safe** or **Caution**.
3. Click **+ Add Custom Folder** anytime to save any custom cleanup folder to your **Custom Folders** list (critical Windows system folders stay blocked).
4. Turn toggles on or off for any item you want to clean or skip. Click **Open Folder** on any row to inspect the actual folder in Windows Explorer before deleting.
5. Look at the bottom bar: keep **Recycle Bin (Safe)** selected (recommended), then click the blue **Clean** button and confirm.

### 2. Drive Scanner, Interactive Disk Map & Duplicate Finder
1. Click **Drive Scanner** on the left sidebar, then click any drive (`Drive C:`, `Drive D:`, etc.) or **Scan Custom Folder...** to analyze a specific folder. When running as Administrator on a local NTFS drive root, DriveSweep automatically uses fast NTFS Master File Table (MFT) scanning and falls back seamlessly to standard multi-threaded scanning otherwise.
2. Export full scan summaries anytime via **Export CSV** or **Export JSON**.
3. Explore the 6 tabs:
   - **Visual Summary:** Features an interactive **Folder Space Breakdown** (segmented storage bar + proportional folder rows with click-to-explore drill-down and breadcrumbs), **What Takes Up Space**, **How Old Your Files Are**, and **Top Space Users**, plus calm safety indicators (**System Files**, **Important Files**, **Standard Files**).
   - **Folders:** Browse folders from largest to smallest, check items to clean, or click **Keep** to protect a folder permanently.
   - **Find Any File:** Search by file name, extension (such as `.zip` or `.mp4`), minimum size in MB, or age (for example, files untouched for over 90 days).
   - **Biggest Files:** Quickly lists the largest individual files on the selected drive.
   - **Project Caches:** Finds old build and dependency folders (`node_modules`, `.venv`, `target`, `dist`, and similar) if you work on coding projects.
   - **Duplicates:** Finds exact duplicate files using byte-size grouping and SHA-256 checksums, recommends keeping 1 copy per group, and lets you queue extra copies cleanly.

### 3. Windows Space Tools
Click **Windows Tools** on the left sidebar to open the dedicated Windows Space & Tools workspace and inspect or reclaim space across:
- **Windows Recycle Bin:** View total size, per-drive Recycle Bin breakdown chips, and item count, open Recycle Bin directly, or empty it after confirmation (and record the cleanup in Cleanup Log).
- **Old Download Installers (14 / 30 / 90 days):** Filter old `.exe`, `.msi`, `.zip`, `.iso`, and archive installers in `Downloads` and queue selected items for cleanup.
- **WinSxS Component Store (DISM):** Safely analyze and trim superseded Windows Update backups with structured KPI readouts and Administrator Cleanup Log recording.
- **Hibernation & Virtual Disks:** View `hiberfil.sys` size, enable/disable Windows hibernation in one click, inspect WSL2 / Docker `.vhdx` virtual disks with proportional usage bars, reveal files in Explorer, and run one-click **Shrink Disk** compaction right inside the app.

### 4. Always Keep, Cleanup Log & Scheduled Low-Disk Reminders
- **Always Keep:** Protect any folder or file from deletion across Quick Clean, Large Files & Folders, Drive Scanner, and Duplicates by clicking **Keep** on any row, or by opening **Always Keep** in the sidebar and clicking **+ Add Folder...**. You can remove protected paths from this list anytime.
- **Cleanup Log:** Shows a local record of past cleanups on your PC and includes an **Open Recycle Bin** button for quick restoration.
- **Settings & Updates:** Switch UI language (`English`, `Espanol`, `Francais`, `Deutsch`, `Portugues`), configure an optional Windows Task Scheduler low-disk space reminder, verify local storage privacy, and check or install updates via GitHub Releases Setup.

### 5. Automatic Updates via Setup
Open **Settings & Updates** (left sidebar) -> **Check for Updates**. DriveSweep checks GitHub Releases over HTTPS, shows live download progress for the verified Setup installer package, checks `SHA256SUMS.txt` before installing, closes DriveSweep cleanly so Setup can upgrade files in place, and relaunches the updated app automatically. Auto-checking on startup can be turned on or off anytime.

---

## Safety Protections Built In

- **Personal folders protected automatically:** Quick Clean never selects your `Downloads`, `OneDrive`, `CrossDevice`, `Documents`, `Desktop`, `Pictures`, `Music`, or `Videos` folders.
- **Critical system files locked:** Essential Windows folders (`Windows\System32`, `Program Files`, `Boot`, and similar) cannot be deleted in DriveSweep.
- **Permission prompt on important items:** Deleting databases, code repositories, executables, or selecting **Delete Forever** always asks for explicit confirmation first.
- **Clean parent/child math:** Selecting both a folder and files inside it never counts or deletes anything twice.

---

## Diagnostics & Winget Packaging

- **Crash & Diagnostics Log:** Rotating logs (`drivesweep.log`, up to 1 MB x 3 backups) are stored in `%LOCALAPPDATA%\DriveSweep\drivesweep.log` and capture unhandled Python exceptions and UI `window.onerror` / `unhandledrejection` events. Open it anytime from **Settings & Updates -> Open Diagnostics Log**.
- **Winget Manifests:** Release manifest templates live under `packaging/winget/` (`rauell1.DriveSweep.yaml`, `rauell1.DriveSweep.installer.yaml`, `rauell1.DriveSweep.locale.en-US.yaml`).

## Code Signing Policy

Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

### Project Team & Roles
- **Authors / Maintainers / Approvers:** [Roy Otieno (@rauell1)](https://github.com/rauell1)
- All source code changes are committed to the public repository and built cleanly through GitHub Actions workflows in [.github/workflows/ci-release.yml](https://github.com/rauell1/drive-sweep/blob/main/.github/workflows/ci-release.yml).
- Once SignPath Foundation approves the project, add `SIGNPATH_API_TOKEN`, `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, and `SIGNPATH_SIGNING_POLICY_SLUG` to GitHub repository Actions secrets to enable automatic Authenticode signing on every release tag.

---

## Privacy Policy

DriveSweep runs completely offline on your local computer. It does not collect, transmit, sell, or share any personal data, file listings, or telemetry with any external server or with the project author. Settings (`settings.json`), exclusion paths, and local cleanup logs (`history.jsonl`) are stored strictly in `%LOCALAPPDATA%\DriveSweep` (or `~/.config/DriveSweep`) on your own device.

The only optional network connection happens when you check for app updates against the public GitHub Releases API (`api.github.com` / `github.com`), which receives only a standard HTTPS request with no personal data or scan history.

---

## Building from Source (For Developers)

```powershell
git clone https://github.com/rauell1/drive-sweep.git
cd drive-sweep
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

- Run UI without triggering Windows UAC elevation during development:
  ```powershell
  .\.venv\Scripts\python.exe main.py --no-elevate
  ```
- Run automated tests:
  ```powershell
  .\.venv\Scripts\python.exe -m pytest -v
  ```
- Build Windows portable executables and checksums (and the Inno Setup installer if `ISCC.exe` is installed):
  ```powershell
  .\build.ps1
  ```
