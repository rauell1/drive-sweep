# Changelog

All notable changes to DriveSweep are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

When you release, `scripts/bump_version.py` turns the **Unreleased** section into the new version, and the release workflow copies that section into the GitHub Release notes.

## [Unreleased]

## [0.8.0] - 2026-11-20

### Added
- **Undo Last Cleanup** in the Cleanup Log puts the files from your most recent Recycle Bin cleanup back in their original folders. It restores only what that cleanup moved, never overwrites a file that exists again, and asks first. The Cleanup Complete window points to it.
- **Export List (CSV or JSON)** in **Review Selected** saves exactly what a cleanup would remove, without deleting anything.
- **Scheduled cleanup of Safe items** (off by default): on the same schedule as the low-disk reminder, the Quick Clean items marked Safe and recommended can go to the Recycle Bin automatically. Always Keep items, items whose app is running, Caution items and custom folders are skipped, and each run can be undone from the Cleanup Log.
- README screenshots and demo refreshed for 0.8.0.
- winget: a ready to submit folder for 0.7.6 and steps for submitting again after a closed pull request.

### Changed
- Messages from the app's engine are now translated too: update and Windows Tools errors, safety explanations on hover, cleanup item notes and Cleanup Log entries. Paths, numbers and file names inside them stay as they are.
- The lifetime space freed total no longer counts the same files twice: emptying the Recycle Bin is listed in the Cleanup Log but not added again, and an undo subtracts what it restored. Existing logs are recalculated the same way.

## [0.7.6] - 2026-11-18

### Security
- **Empty Recycle Bin** now always asks first. It shows how many items and how much space will go, and says that it also removes files you deleted earlier and cannot be undone. This applies to the button in **Cleanup Complete** and the one in **Windows Tools**. The app's backend also refuses to empty the Recycle Bin without that confirmation.

### Fixed
- Messages added in 0.7.3 to 0.7.5 are now translated into Spanish, French, German and Portuguese: the running apps tip, the Recycle Bin messages and the locked file notices in the cleanup summary. A few older button labels ("Copied", "Enabling...") are translated too.
- Emptying the Recycle Bin from **Cleanup Complete** now updates the space freed counter, like the button in **Windows Tools**.
- A test now flags interface text that skips translation.

## [0.7.5] - 2026-11-17

### Fixed
- Fixed table layout clipping on the right edge (`Keep` / `Open Folder` buttons, `Size`, and `Space` columns) when displaying long unbroken filenames in **Large Files & Folders** and **Drive Scanner** by using `table-layout: fixed`, proper word wrapping on item names, and single-line badges/sizes.

## [0.7.4] - 2026-11-17

### Added
- Added a 1-click **Empty Recycle Bin** button directly inside the **Cleanup Complete** modal so users can free disk space permanently right after reviewing Recycle Bin cleanup results.
- Added a running-app tip inside the cleanup confirmation modal when selected caches belong to currently open apps (such as Chrome or Docker Desktop).

### Fixed
- Fixed `[Errno 2]` fallback errors when a partial Recycle Bin batch already moved some files before hitting a locked file, and only batched files (not heavy cache subfolders) for faster, smoother deletion.
- Added friendly wording for `WinError 161` active cache path errors and wrapped long paths cleanly inside modal notices to remove horizontal scrollbars.

## [0.7.3] - 2026-11-17

### Fixed
- Batched Windows Recycle Bin cleanup for folder contents (`AppData\Local\Temp`, `SoftwareDistribution\Download`, `Logs`) so large temp folders clean much faster with live sub-item progress updates instead of appearing paused.
- Replaced raw Windows lock error arrays (`WinError 5` / `WinError 32`) with plain-English locked-file notices in a calmer cleanup summary box.

## [0.7.2] - 2026-11-17

### Added
- The whole interface is now available in Spanish, French, German and Portuguese, with proper accents and one consistent tone. This includes buttons, menus, messages, tooltips and the names and notes of cleanup items.
- Screenshots and a short demo in the README, and a social preview image for links to the repository.
- A step by step checklist for testing updates on a real PC, including the automatic rollback.

### Fixed
- Toolbar buttons such as **Re-scan**, **+ Add Custom Folder** and **Restart as Admin** no longer wrap onto two lines.
- Category names in the **Space by Category** chart are no longer cut off; long names wrap, and the list moves below the chart when space is tight.
- Counts such as "1 item selected" now use the correct singular or plural form.

## [0.7.1] - 2026-11-17

### Added
- Automatic rollback after an in place update: if the new portable or folder version does not open, the previous version is restored and started again.
- Every pull request now builds the app, checks that the built files start, installs and uninstalls Setup silently, and uploads a test build.
- One command version bumps (`scripts/bump_version.py`) and this changelog, which now feeds the release notes.
- Translations of the first run notice, the new warnings and the update descriptions into Spanish, French, German and Portuguese.
- Security policy, contributing guide, code of conduct, issue and pull request templates, and CodeQL code scanning.

### Changed
- GitHub Actions updated to their latest major versions (checkout, upload artifact, release, Azure signing), still pinned by commit.
- Python dependencies are refreshed weekly by a workflow that tests the new versions before opening a pull request.
- Installed apps now shows the name "DriveSweep" without a version number, so winget and upgrades match it reliably.
- Confirmed working on Windows 11 on ARM (the x64 build runs through Windows' built in emulation); checked automatically on every pull request.

## [0.7.0] - 2026-11-16

### Added
- Updates now replace the copy you run: Setup for installed copies, `DriveSweep.exe` in place for the portable version, and the program files in place for the zip folder version, each verified before the swap.
- First run notice with the disclaimer; update checks are now opt in.
- Privacy policy, third party license notices, and a Limits section explaining when the Recycle Bin cannot protect a file.
- Build provenance attestation and a software bill of materials with every release.

### Security
- Cleanup never follows folder links (junctions, symbolic links, mount points); deleting a link removes only the link.
- The Always Keep list is enforced by the cleanup engine itself, and the Users folder, other accounts and the ProgramData folder are protected.
- Fixed a command injection in Shrink Disk; the updater only accepts official, newer release downloads and verifies the file again right before it runs.
- The app runs as a standard user and asks for Administrator rights only when needed.
- Content Security Policy for the interface, quote safe HTML escaping, and formula safe CSV export.

### Changed
- Release pipeline signs in the right order (when signing is configured), pins every action by commit and installs only hash locked dependencies.

## [0.6.0] - 2026-11-16
- Interactive drill downs, duplicate keep rules, Windows.old cleanup and a lifetime space freed counter.

## [0.5.0] - 2026-11-16
- Plain English guidance throughout, one click Windows workflows and Windows 11 polish.

## [0.4.0] - 2026-11-15
- Interface design sweep and a full page Windows Space and Tools workspace.

## 0.3.0 to 0.3.9 - 2026-11-15
- Duplicate finder, fast NTFS MFT scanning, Windows tools, custom cleanup folders, low disk reminders and five languages (0.3.0).
- Diagnostics log, end to end UI tests and winget manifests (0.3.1); Explorer layout and stability fixes (0.3.2); faster, smoother updates (0.3.3, 0.3.4).
- Calmer interface, Known Folders and OneDrive safety, opt in Large Files and Folders, a segmented storage bar, Cleanup Log entries for system cleanups, and support for fragmented NTFS file tables (0.3.5 to 0.3.9).

## 0.2.0 to 0.2.8 - 2026-11-15
- First public release with Administrator mode and CI (0.2.0), then local only privacy guarantees, a SHA-256 verified updater, wider cache detection and interface polish.

[Unreleased]: https://github.com/rauell1/drive-sweep/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/rauell1/drive-sweep/compare/v0.7.6...v0.8.0
[0.7.6]: https://github.com/rauell1/drive-sweep/compare/v0.7.5...v0.7.6
[0.7.5]: https://github.com/rauell1/drive-sweep/compare/v0.7.4...v0.7.5
[0.7.4]: https://github.com/rauell1/drive-sweep/compare/v0.7.3...v0.7.4
[0.7.3]: https://github.com/rauell1/drive-sweep/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/rauell1/drive-sweep/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/rauell1/drive-sweep/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/rauell1/drive-sweep/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/rauell1/drive-sweep/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/rauell1/drive-sweep/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rauell1/drive-sweep/compare/v0.3.9...v0.4.0
