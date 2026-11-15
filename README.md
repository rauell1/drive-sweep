# DriveSweep

**Free up disk space safely on Windows.** DriveSweep scans your PC for temporary files, leftover app caches, browser caches, and oversized old files, then lets you review everything in plain visual charts before moving anything to the Recycle Bin.

- **Works on any Windows PC:** Automatically finds Windows temporary files, Windows Update leftovers, Microsoft Store app caches, browser caches (Edge, Chrome, Firefox, Brave, Opera), everyday app caches (Teams, Discord, Spotify, Slack, Zoom, Steam, Epic Games, Office), and any installed desktop app caches on your computer. Optional coding and AI caches are also detected automatically only if you use those tools.
- **Built for safety first:** Personal folders (`Downloads`, `OneDrive`, `Documents`, `Pictures`, `Videos`, `Music`, `Desktop`) are never selected by Quick Clean. System files are locked so they cannot be removed accidentally, important files ask for your confirmation first, and cleanup defaults to **Recycle Bin (Safe)** so you can restore files anytime.
- **Light and Dark Mode:** Switch themes anytime from the top-left corner.
- **100% private and offline:** Every scan, setting, and cleanup record stays on your own computer. Nothing is uploaded anywhere.

---

## Step-by-Step Installation (Windows)

Choose **Option A** (standard Windows installer, recommended for most users) or **Option B** (portable app with no installation).

### Option A: Windows Installer (Recommended)

1. Open the **[GitHub Releases](https://github.com/rauell1/drive-sweep/releases)** page.
2. Under the latest release (**Assets** section at the bottom), click **`DriveSweep-Setup-0.2.6.exe`** (or the newest version listed) to download it.
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
2. Each item is grouped clearly (`Windows & Temp`, `Web Browsers`, `Desktop Apps`, `AI & Coding Tools`, `Dev Editors & Packages`, `Other App Caches`) and labeled **Safe** or **Caution**.
3. Turn toggles on or off for any item you want to clean or skip. Click **Open Folder** on any row to inspect the actual folder in Windows Explorer before deleting.
4. Look at the bottom bar: keep **Recycle Bin (Safe)** selected (recommended), then click the blue **Clean** button and confirm.

### 2. Drive Scanner (Find What Is Filling Up Any Drive)
1. Click **Drive Scanner** on the left sidebar, then click any drive (`Drive C:`, `Drive D:`, etc.) or **Scan Custom Folder...** to analyze a specific folder.
2. Explore the 5 tabs:
   - **Visual Summary:** Shows **Largest Folders**, **What Takes Up Space** (videos, archives, documents, code, other), **How Old Your Files Are**, and **Top Space Users**, plus safety cards (**System Files**, **Important Files**, **Standard Files**).
   - **Folders:** Browse folders from largest to smallest, check items to clean, or click **Keep** to protect a folder permanently.
   - **Find Any File:** Search by file name, extension (such as `.zip` or `.mp4`), minimum size in MB, or age (for example, files untouched for over 90 days).
   - **Biggest Files:** Quickly lists the largest individual files on the selected drive.
   - **Project Caches:** Finds old build and dependency folders (`node_modules`, `.venv`, `target`, `dist`, and similar) if you work on coding projects.

### 3. Always Keep & Cleanup History
- **Always Keep:** Any folder or file you mark **Keep** is protected from deletion across both Quick Clean and Drive Scanner. You can remove it from this list later if you change your mind.
- **Cleanup History:** Shows a local record of past cleanups on your PC and lets you open **Updates & Privacy** to check for newer releases.

### 4. Automatic Update Checks
Open **Cleanup History** (left sidebar) -> **Check for Updates**. DriveSweep checks GitHub Releases over HTTPS, verifies the `SHA256SUMS.txt` checksum before running the installer or replacing a portable build, and lets you install the update cleanly on your machine. Auto-checking on startup can be turned on or off anytime.

---

## Safety Protections Built In

- **Personal folders protected automatically:** Quick Clean never selects your `Downloads`, `OneDrive`, `CrossDevice`, `Documents`, `Desktop`, `Pictures`, `Music`, or `Videos` folders.
- **Critical system files locked:** Essential Windows folders (`Windows\System32`, `Program Files`, `Boot`, and similar) cannot be deleted in DriveSweep.
- **Permission prompt on important items:** Deleting databases, code repositories, executables, or selecting **Delete Forever** always asks for explicit confirmation first.
- **Clean parent/child math:** Selecting both a folder and files inside it never counts or deletes anything twice.

---

## Code Signing Policy

Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).

### Project Team & Roles
- **Authors / Maintainers / Approvers:** [Roy Otieno (@rauell1)](https://github.com/rauell1)
- All source code changes are committed to the public repository and built cleanly through GitHub Actions workflows in [.github/workflows/ci-release.yml](https://github.com/rauell1/drive-sweep/blob/main/.github/workflows/ci-release.yml).

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
