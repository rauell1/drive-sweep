# Platform notes: Windows on ARM and the Microsoft Store

_Evaluated November 2026._

## Windows on ARM

**Status: supported on Windows 11 on ARM through the x64 build. No separate ARM64 build for now.**

- Windows 11 on ARM (for example Snapdragon X laptops) runs x64 apps through its built in x64 emulation. The CI job **Runs on Windows on ARM (x64 build under emulation)** installs the exact test build on GitHub's `windows-11-arm` runner, self-tests the portable exe and the installed copy (including loading the interface engine), and uninstalls it, on every pull request.
- Windows 10 on ARM only emulates 32 bit x86 apps, not x64, so it is not supported.
- The Setup installer allows `x64compatible` systems, which includes Windows 11 on ARM, and winget offers the x64 installer there.

### Why not a native ARM64 build yet

| Part | Native ARM64 available? |
| --- | --- |
| Python 3.12, PyInstaller, psutil, cffi | Yes (official ARM64 builds and wheels; the dependency lock resolves for ARM64) |
| GitHub Actions runner | Yes (`windows-11-arm`) |
| pywebview's .NET bridge (pythonnet with clr-loader) | **No.** clr-loader 0.3.1 ships its .NET Framework loader only for x64 and x86 (`clr_loader/ffi/dlls/amd64`, `x86`). On native ARM64 Python, pywebview falls back to the separate .NET runtime (`PYTHONNET_RUNTIME=coreclr`), which Windows does not include. |

A native ARM64 DriveSweep would therefore require every ARM user to install the .NET Desktop Runtime first, or the app would have to bundle it, adding tens of megabytes. Under emulation the x64 build needs nothing extra. Scanning and cleaning are limited mainly by disk speed rather than processor speed, so emulation costs little in practice.

**Revisit when** clr-loader ships an ARM64 .NET Framework loader, or pywebview supports ARM64 without the separate runtime. Then add a `windows-11-arm` build job with an ARM64 lock (`uv pip compile ... --python-platform aarch64-pc-windows-msvc`) and publish `DriveSweep-arm64` assets next to the x64 ones.

## Microsoft Store

**Recommendation: not now.** winget covers command line installs, and the Store paths either do not remove the need for a certificate or would mean cutting features.

| Store path | Solves code signing? | Fit for DriveSweep |
| --- | --- | --- |
| Submit the existing EXE installer | **No.** The Store does not re-sign EXE or MSI installers. They must already be signed with a certificate from a CA in the Microsoft Trusted Root Program. | Would work once releases are signed, but adds nothing over winget for signing. |
| Repackage as MSIX | **Yes.** The Store signs MSIX packages itself. | Poor today. System tasks (Windows Temp, Windows Update cache, DISM, hibernation, virtual disk shrinking, fast NTFS scanning) need Administrator rights. Elevating from an MSIX package needs the restricted `allowElevation` capability, which Microsoft says it rarely approves for Store apps. MSIX also replaces the built in updater with Store updates, and redirects some app data writes. |

### If SmartScreen warnings become the main adoption problem

A **Store edition** packaged as MSIX, limited to the features that work as a standard user, would get a Microsoft signed listing without buying a certificate:
- Included: Quick Clean of user caches, Drive Scanner (standard scanning), Large Files and Folders, Duplicates, Recycle Bin tools, Always Keep, Cleanup Log.
- Left out: Windows Temp and update cache cleaning, DISM, hibernation, virtual disk shrinking, fast NTFS scanning, the self updater and the scheduled reminder.

Work involved: a build flavor that hides the admin features and the updater, an MSIX manifest and packaging step in CI, a Partner Center developer account (check the current registration terms), and Store certification. Ask for it as a separate project if wanted.

## Sources

- Microsoft: [Choose a distribution path](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/choose-distribution-path), [Code signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options), [Publish your first app](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/publish-first-app), [App certification for MSI and EXE apps](https://docs.microsoft.com/en-us/windows/uwp/publish/msiexe/the-app-certification-process)
- Elevation in MSIX: [Advanced Installer: allowElevation for MSIX](https://www.advancedinstaller.com/allow-elevation-msix-packages.html), [Microsoft Q&A: run an MSIX packaged app as admin](https://learn.microsoft.com/en-us/answers/questions/5907620/run-msix-packaged-app-as-admin)
- ARM64 runners: [GitHub: Windows arm64 hosted runners](https://github.blog/changelog/2025-04-14-windows-arm64-hosted-runners-now-available-in-public-preview/), [GitHub: arm64 runners generally available for public repositories](https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/)
- .NET on ARM64: [Toga Windows platform notes (Python.NET runtime on ARM64)](https://toga.beeware.org/en/stable/reference/platforms/windows/), [.NET Framework 4.8.1 adds native Arm64](https://visualstudiomagazine.com/articles/2022/08/12/net-framework-4-8-1.aspx)
