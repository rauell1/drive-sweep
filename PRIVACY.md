# DriveSweep Privacy Policy

_Last updated: 16 November 2026_

DriveSweep is a free, open source Windows app maintained by Roy Otieno ("we"). This policy explains what data the app handles and where it goes.

## Summary

* DriveSweep has **no accounts, no analytics, no telemetry and no advertising**.
* Scans, settings, history and logs **stay on your PC**. We never receive them.
* The only network connection is the **optional update check**, which is **off by default**.

## Data stored on your PC

DriveSweep stores the following in `%LOCALAPPDATA%\DriveSweep` (or the equivalent folder on other systems):

| File | Contents | Purpose |
| --- | --- | --- |
| `settings.json` | Theme, language, Always Keep list, custom cleanup folders, reminder settings | Remembers your choices |
| `history.jsonl` | Date, amount freed and paths of items you cleaned | Cleanup Log and lifetime total |
| `drivesweep.log` (plus up to 3 backups of 1 MB each) | Errors and actions, which can include file and folder paths | Troubleshooting |

You can delete this data at any time: **Settings & Updates > Clear Logs**, **Cleanup Log > Clear History**, or by deleting the folder. When you uninstall DriveSweep, the uninstaller offers to delete it for you.

Exported scan reports (CSV or JSON) are saved only where you choose.

When you run DriveSweep as Administrator, verified update installers and temporary helper scripts are kept briefly in `%ProgramData%\DriveSweep`, a folder only Administrators can change. The uninstaller removes it.

## Network connections

**Update check (optional, off by default).** If you turn on "Check GitHub Releases on startup", or click **Check for Updates**, DriveSweep sends a standard HTTPS request to GitHub (`api.github.com` and `github.com`). GitHub receives your **IP address** and a **User-Agent containing the DriveSweep version**. No file names, scan results, logs, settings or device identifiers are sent. GitHub, Inc. handles that request under the [GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). We do not receive or see this data.

If you choose to install an update, DriveSweep downloads the installer and `SHA256SUMS.txt` from the project's GitHub Releases page.

DriveSweep makes no other network connections.

## Legal basis (GDPR and similar laws)

DriveSweep processes data locally on your device under your control. The optional update check is based on your **consent**, which you give by turning it on and can withdraw at any time by turning it off.

## Children

DriveSweep does not knowingly collect any personal data from anyone, including children.

## Changes and contact

Changes to this policy are published in this file in the [project repository](https://github.com/rauell1/drive-sweep). Questions can be raised in [GitHub Issues](https://github.com/rauell1/drive-sweep/issues).
