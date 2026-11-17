# DriveSweep

**Free up disk space safely on Windows.** DriveSweep scans your PC for temporary files, leftover app caches, browser caches, and oversized old files, then lets you review everything in plain visual charts before moving anything to the Recycle Bin.

- **Works on any Windows PC:** Automatically finds Windows temporary files, Windows Update leftovers, Microsoft Store app caches, browser caches (Edge, Chrome, Firefox, Brave, Opera), everyday app caches (Teams, Discord, Spotify, Slack, Zoom, Steam, Epic Games, Office), and any installed desktop app caches on your computer. Optional coding and AI caches are also detected automatically only if you use those tools.
- **Designed for safety:** Personal folders (`Downloads`, `OneDrive`, `Documents`, `Pictures`, `Videos`, `Music`, `Desktop`) are never auto-selected by Quick Clean. Use the **Large Files & Folders** view to inspect big files and folders across `Downloads`, user spaces, and all drives where every item stays unchecked until you manually select it. Windows system folders and other user accounts are blocked, important files ask for your confirmation first, and cleanup defaults to the **Recycle Bin** so you can usually restore files (see [Limits](#limits-please-read)).
- **Light and Dark Mode:** Switch themes anytime from the top-left corner.
- **Private by design:** Every scan, setting, and cleanup record stays on your own computer. Nothing is uploaded. The only network use is the optional update check, which is off by default (see [Privacy](#privacy)).
- **Least privilege:** DriveSweep runs as a standard user. It asks for Administrator rights only when you choose **Restart as Admin** for system level tasks.

---

## Step-by-Step Installation (Windows)

Choose **Option A** (standard Windows installer, recommended for most users) or **Option B** (portable app with no installation).

### Option A: Windows Installer (Recommended)

1. Open the **[GitHub Releases](https://github.com/rauell1/drive-sweep/releases)** page.
2. Under the latest release (**Assets** section at the bottom), click **`DriveSweep-Setup-0.7.0.exe`** (or the newest version listed) to download it.
3. Open your `Downloads` folder and double-click the downloaded `DriveSweep-Setup-...exe` file.
4. **If Windows shows a "Windows protected your PC" (SmartScreen) blue popup:**
   - DriveSweep releases are not code signed yet (see [Code Signing Policy](#code-signing-policy)), so Windows shows this for a publisher it does not know. Before running, you can [verify the download](#verifying-downloads) against `SHA256SUMS.txt` and its build provenance.
   - Click **More info**, then click **Run anyway**.
5. **Accept the Administrator prompt (UAC):** Click **Yes** when Windows asks if Setup can make changes to your device. Setup needs this to install into `Program Files`. The app itself then runs as a standard user.
6. Follow the setup wizard (**Next -> Install -> Finish**). Leave **Launch DriveSweep** checked to open the app right away, or open **DriveSweep** anytime from your Start Menu or Desktop shortcut.

### Option B: Portable Version (No Installer)

1. Open the **[GitHub Releases](https://github.com/rauell1/drive-sweep/releases)** page.
2. Under **Assets**, download **`DriveSweep.exe`** (single-file app) or **`DriveSweep-win64.zip`** (unzip it to any folder you like).
3. Double-click **`DriveSweep.exe`** and click **More info -> Run anyway** if SmartScreen appears. No Administrator prompt appears until you choose **Restart as Admin** inside the app.

---

## How to Use DriveSweep

### 1. Quick Clean (Easiest Way to Free Space)
1. When DriveSweep opens, **Quick Clean** scans your PC automatically for safe, regenerable temporary files and app caches.
2. Each item is grouped clearly (`Windows & Temp`, `Web Browsers`, `Desktop Apps`, `AI & Coding Tools`, `Dev Editors & Packages`, `Custom Folders`, `Other App Caches`) and labeled **Safe** or **Caution**.
3. Click **+ Add Custom Folder** anytime to save any custom cleanup folder to your **Custom Folders** list (critical Windows system folders stay blocked).
4. Turn toggles on or off for any item you want to clean or skip. Click **Open Folder** on any row to inspect the actual folder in Windows Explorer before deleting.
5. Look at the bottom bar: keep **Recycle Bin (Safe)** selected (recommended), then click the blue **Clean** button and confirm.
6. Windows system temp folders (such as `C:\Windows\Temp` and Windows Update downloads) need Administrator rights. Click **Restart as Admin** in the sidebar when you want to include them.

### 2. Drive Scanner, Interactive Disk Map & Duplicate Finder
1. Click **Drive Scanner** on the left sidebar, then click any drive (`Drive C:`, `Drive D:`, etc.) or **Scan Custom Folder...** to analyze a specific folder. When running as Administrator on a local NTFS drive root, DriveSweep uses fast NTFS Master File Table (MFT) scanning; otherwise it uses standard multi-threaded scanning.
2. Export full scan summaries anytime via **Export CSV** or **Export JSON**. CSV cells that start with `=`, `+`, `-` or `@` are prefixed with `'` so spreadsheet apps never run them as formulas.
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
- **Hibernation & Virtual Disks:** View `hiberfil.sys` size, enable/disable Windows hibernation in one click, inspect WSL2 / Docker `.vhdx` virtual disks with proportional usage bars, reveal files in Explorer, and run one-click **Shrink Disk** compaction right inside the app. Shrinking first runs `wsl --shutdown`, which closes every running Linux distribution and Docker Desktop's engine, so DriveSweep asks you to confirm first.

### 4. Always Keep, Cleanup Log & Scheduled Low-Disk Reminders
- **Always Keep:** Protect any folder or file from deletion across Quick Clean, Large Files & Folders, Drive Scanner, and Duplicates by clicking **Keep** on any row, or by opening **Always Keep** in the sidebar and clicking **+ Add Folder...**. You can remove protected paths from this list anytime.
- **Cleanup Log:** Shows a local record of past cleanups on your PC and includes an **Open Recycle Bin** button for quick restoration.
- **Settings & Updates:** Switch UI language (`English`, `Espanol`, `Francais`, `Deutsch`, `Portugues`), configure an optional Windows Task Scheduler low-disk space reminder, verify local storage privacy, and check or install updates via GitHub Releases Setup.

### 5. Updates
Open **Settings & Updates** (left sidebar) -> **Check for Updates**. DriveSweep checks GitHub Releases over HTTPS and updates **the copy you are running**:

| How you run DriveSweep | What gets downloaded | What happens |
| --- | --- | --- |
| Installed with Setup | `DriveSweep-Setup-x.y.z.exe` | Setup upgrades your installed copy in place and reopens DriveSweep. |
| Portable `DriveSweep.exe` | `DriveSweep.exe` | The new file is saved in the **same folder** as your `DriveSweep.exe`. DriveSweep closes, swaps the new version in (keeping `DriveSweep.exe.old` as a backup), and reopens. |
| Folder version from `DriveSweep-win64.zip` | `DriveSweep-win64.zip` | The zip is saved and unpacked in the **same folder**. DriveSweep closes, replaces its program files with the new ones (keeping a backup in `_update_old`), and reopens. Other files you keep in that folder are left alone. |

Every update is checked before anything is replaced:
- Only official `github.com/rauell1/drive-sweep` release downloads newer than your current version are accepted.
- The file's SHA-256 must match `SHA256SUMS.txt`, and it is checked again right before the swap.
- The Authenticode signature is checked. Once DriveSweep builds are signed, updates must be signed by the same publisher.
- If the swap fails, the previous version is restored. The backup is deleted automatically the next time the new version starts.

A portable copy must be in a folder you can write to (for example not inside `Program Files`); otherwise DriveSweep asks you to move it or use Setup. Checking on startup is **off by default**; you can turn it on during first run or in Settings.

---

## Safety Protections Built In

- **Personal folders are never auto-selected:** Quick Clean never selects your `Downloads`, `OneDrive`, `CrossDevice`, `Documents`, `Desktop`, `Pictures`, `Music`, or `Videos` folders.
- **System and other accounts blocked:** Essential Windows folders (`Windows`, `Program Files`, `ProgramData\Microsoft`, `Boot`, `Recovery`, and similar), the `Users` folder itself, and other user accounts' profiles (including `Public` and `Default`) are blocked from deletion.
- **Folder links are never followed:** If a path goes through a junction, symbolic link or mount point, DriveSweep refuses to clean through it. Deleting a link removes only the link, never the folder it points to.
- **Always Keep is enforced twice:** Your Always Keep list is checked in the interface and again by the cleanup engine right before anything is removed.
- **Permission prompt on important items:** Deleting databases, code repositories, executables, `Windows.old`, or selecting **Delete Forever** always asks for explicit confirmation first.
- **Clean parent/child math:** Selecting both a folder and files inside it never counts or deletes anything twice.

### Limits (please read)

These protections reduce risk; they do not remove it. You decide what is removed, so **back up anything important first**.

- **The Recycle Bin is not a guarantee.** Network and removable drives have no Recycle Bin (DriveSweep skips those items in Recycle Bin mode instead of deleting them), paths longer than about 255 characters cannot go there, and Windows may permanently delete an item that is too large for the Recycle Bin.
- **Delete Forever cannot be undone.**
- **Removing `Windows.old`** ends your ability to roll back to your previous Windows version.

---

## Diagnostics & Winget Packaging

- **Crash & Diagnostics Log:** Rotating logs (`drivesweep.log`, up to 1 MB x 3 backups) are stored in `%LOCALAPPDATA%\DriveSweep\drivesweep.log` and capture unhandled Python exceptions and UI `window.onerror` / `unhandledrejection` events. Logs can contain file and folder paths. Open them from **Settings & Updates -> Open Diagnostics Log**, or erase them with **Clear Logs**.
- **Winget:** manifests live in `packaging/winget/` (schema 1.12.0). See [packaging/winget/README.md](packaging/winget/README.md) for how to submit DriveSweep to the winget community repository so users can run `winget install rauell1.DriveSweep`.

## Code Signing Policy

**Current status: DriveSweep releases are not code signed.** Windows SmartScreen may therefore show "Windows protected your PC" the first time you run a download; click **More info > Run anyway** once you have verified the file (see [Verifying downloads](#verifying-downloads)). Each release states in its notes whether its files are signed.

The project applied for free code signing from [SignPath Foundation](https://signpath.org) in November 2026. The application was not approved yet because the Foundation requires a project to show more public visibility first (community adoption, independent references and sustained activity); the decision was not about the code. The project will reapply as it grows. Until then releases stay unsigned on purpose, rather than switching to a paid certificate that would later change the publisher name and break automatic updates.

Once a signed release is published, its notes will carry this notice: _Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org)._

### Verifying downloads

Every release includes three ways to check that a file is genuine and unchanged:

1. **Checksum.** In PowerShell, compare the file's hash with the matching line in `SHA256SUMS.txt` from the same release:
   ```powershell
   (Get-FileHash .\DriveSweep-Setup-0.7.0.exe -Algorithm SHA256).Hash.ToLower()
   ```
2. **Build provenance.** Proves the file was built by this repository's GitHub Actions workflow from a specific commit (requires the [GitHub CLI](https://cli.github.com)):
   ```powershell
   gh attestation verify .\DriveSweep-Setup-0.7.0.exe --repo rauell1/drive-sweep
   ```
3. **Software bill of materials.** `DriveSweep-sbom.cdx.json` lists every bundled Python package and version.

DriveSweep's built in updater does the checksum check automatically before installing anything.

### Project Team & Roles
- **Authors / Maintainers / Approvers:** [Roy Otieno (@rauell1)](https://github.com/rauell1)
- All source code changes are committed to the public repository and built through the GitHub Actions workflow in [.github/workflows/ci-release.yml](https://github.com/rauell1/drive-sweep/blob/main/.github/workflows/ci-release.yml). Every third party action is pinned to a commit SHA and every Python dependency is installed from the hash-locked `requirements-dev.lock`.
- The pipeline signs in the correct order: the app executables first, then the zip and installer are built from the signed files, then the installer itself is signed.
- The pipeline is ready to sign as soon as a provider is set up; see [docs/CODE_SIGNING.md](docs/CODE_SIGNING.md) for the current plan and the setup steps. The SignPath artifact configurations live in [`.signpath/artifact-configurations/`](.signpath/artifact-configurations/).
- Tagged releases are never published with SignPath's test certificate; test signing runs only through **Run workflow**.

---

## Privacy

DriveSweep has no accounts, analytics, telemetry or ads. Scans, settings, history and logs stay in `%LOCALAPPDATA%\DriveSweep` on your own device and are never uploaded. The only network use is the **optional** update check (off by default), which sends a standard HTTPS request to GitHub; GitHub sees your IP address and the DriveSweep version, under GitHub's own privacy statement. Read the full [Privacy Policy](PRIVACY.md).

---

## License, Warranty & Trademarks

- DriveSweep is released under the [MIT License](LICENSE) and is provided **"as is", without warranty of any kind**. The authors are not liable for lost data or other damage arising from its use.
- Bundled third party components and their licenses are listed in [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt), which also ships with every release.
- DriveSweep is an independent project and is not affiliated with or endorsed by Microsoft, Google, Mozilla, Valve, or any other company whose software it can clean. Product names are trademarks of their owners and are used only to describe compatibility.

---

## Building from Source (For Developers)

```powershell
git clone https://github.com/rauell1/drive-sweep.git
cd drive-sweep
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe main.py
```

- DriveSweep starts as a standard user. To start it elevated directly:
  ```powershell
  .\.venv\Scripts\python.exe main.py --elevate
  ```
- Run automated tests:
  ```powershell
  .\.venv\Scripts\python.exe -m pytest -v
  ```
- Build Windows portable executables and checksums (and the Inno Setup installer if `ISCC.exe` is installed). CI runs the same script in stages (`-Stage Binaries`, `Package`, `Checksums`) so it can sign in between:
  ```powershell
  .\build.ps1
  ```
- Maintainer guide (branch protection, releasing with `scripts\bump_version.py`, dependency updates): [docs/MAINTAINING.md](docs/MAINTAINING.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).
- After changing `requirements.txt` or `requirements-dev.txt`, regenerate the lock file with `python scripts\refresh_lock.py` (needs uv), and regenerate `THIRD_PARTY_NOTICES.txt` with `python scripts\collect_licenses.py`.
