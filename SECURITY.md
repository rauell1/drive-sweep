# Security Policy

DriveSweep deletes files, can run with Administrator rights and updates itself, so security reports are taken seriously.

## Supported versions

Only the latest release receives security fixes. Please update before reporting, and check whether the problem still exists.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub: open the repository's **Security** tab and click **Report a vulnerability** (private vulnerability reporting). Only the maintainer can see the report.

Please include:
- the DriveSweep version and how it was installed (Setup, portable `DriveSweep.exe`, or the zip),
- your Windows version, and whether DriveSweep was running as Administrator,
- steps to reproduce, and what an attacker could achieve (for example deleting files outside the selection, running code with higher rights, or tampering with an update).

## What to expect

- An acknowledgement within 7 days.
- An assessment and, for confirmed problems, a fix in a new release as soon as practical. Severe issues (such as privilege escalation or arbitrary file deletion) are prioritized.
- Credit in the release notes if you would like it.

Please give a reasonable time to release a fix before disclosing details publicly.

## Scope

In scope: the DriveSweep application, its installer and updater, and this repository's release pipeline.

Out of scope: problems that need an attacker who already has Administrator rights on the PC, findings in third party components that are already fixed upstream (report those to the component's project; the weekly dependency refresh picks up fixes), and SmartScreen warnings caused by releases not yet being code signed (see the README's Code Signing Policy).
