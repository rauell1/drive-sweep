# Publishing DriveSweep on winget

Goal: anyone can install DriveSweep with

```powershell
winget install rauell1.DriveSweep
```

## Files in this folder

| File | Purpose |
| --- | --- |
| `rauell1.DriveSweep*.yaml` | Templates (manifest schema 1.12.0). On every release CI fills in the installer hash and attaches them to the GitHub Release. |
| `submission/manifests/r/rauell1/DriveSweep/<version>/` | A ready to submit copy for a published version, with the real hash and release date, already checked against winget's official JSON schemas. |

To build the submission folder for a new release (needs Python; add `--schemas` with a path to `microsoft/winget-cli/schemas/JSON/manifests` to validate):

```powershell
python scripts\prepare_winget.py --version 0.7.6 --out packaging\winget\submission
```

## First submission (one time)

The package is new to winget, so the first version goes in through a pull request to [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs). The easiest way is Microsoft's **wingetcreate** tool on a Windows PC.

1. **Install the tools**
   ```powershell
   winget install Microsoft.WingetCreate
   ```
2. **Check the manifests** (from the repository folder)
   ```powershell
   winget validate --manifest packaging\winget\submission\manifests\r\rauell1\DriveSweep\0.7.6
   ```
3. **Test install from the manifest** (optional but recommended; run PowerShell as Administrator for the first command)
   ```powershell
   winget settings --enable LocalManifestFiles
   ```
   ```powershell
   winget install --manifest packaging\winget\submission\manifests\r\rauell1\DriveSweep\0.7.6
   ```
   Then check that DriveSweep starts from the Start menu, and uninstall it again with `winget uninstall rauell1.DriveSweep`.
4. **Submit.** Create a GitHub personal access token (classic) with the `public_repo` scope at https://github.com/settings/tokens, then run:
   ```powershell
   wingetcreate submit --token <your-token> packaging\winget\submission\manifests\r\rauell1\DriveSweep\0.7.6
   ```
   wingetcreate forks winget-pkgs under your account and opens the pull request for you. Delete the token afterwards if you only made it for this.

   Without wingetcreate: fork https://github.com/microsoft/winget-pkgs on GitHub, add the three files at `manifests/r/rauell1/DriveSweep/0.7.6/`, and open a pull request, ticking the checklist in its template.
5. **Follow the pull request.** A bot asks you to accept the Microsoft Contributor License Agreement once; reply as it instructs. Automated validation then installs DriveSweep in a test machine and scans it. A moderator reviews and merges it, which can take a few days. If a label such as `Needs-Author-Feedback` appears, read the bot's comment and fix what it asks.

**Keep your fork until the pull request is merged.** wingetcreate opens the pull request from your fork of winget-pkgs (`<your-account>/winget-pkgs`). Deleting that fork, or its branch, closes the pull request with unmerged commits, and it cannot be reopened.

### If the pull request was closed before it was merged

This happens if the fork or its branch was deleted, or if a moderator closed it. Submit the newest version again as a new pull request; nothing else needs undoing.

1. Build the submission folder for the newest release (already in this repository for the latest version):
   ```powershell
   python scripts\prepare_winget.py --version 0.7.6 --out packaging\winget\submission
   ```
2. Submit it with the same command as above. wingetcreate creates the fork again if it is gone:
   ```powershell
   wingetcreate submit --token <your-token> packaging\winget\submission\manifests\r\rauell1\DriveSweep\0.7.6
   ```
3. Accept the Contributor License Agreement again if the bot asks, then leave the fork alone until a moderator merges the pull request.

Use `wingetcreate submit` (not `update`) until the first version is merged: `update` only works for a package that is already in winget.

Unsigned installers are accepted by winget. The automated scan may still take longer for a new, unsigned publisher.

## Later versions

After the first version is accepted, each new release only needs a version update:

```powershell
wingetcreate update rauell1.DriveSweep --version 0.7.1 --urls https://github.com/rauell1/drive-sweep/releases/download/v0.7.1/DriveSweep-Setup-0.7.1.exe --submit --token <your-token>
```

wingetcreate downloads the installer, computes its hash and opens the pull request. Alternatively run `scripts\prepare_winget.py` for the new version and submit that folder.
