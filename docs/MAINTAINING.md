# Maintaining DriveSweep

## One time repository settings

These are GitHub settings that only the repository owner can change. Do them once.

### 1. Protect `main` (branch ruleset)
The file [`.github/rulesets/protect-main.json`](../.github/rulesets/protect-main.json) describes the rules:
- Changes reach `main` only through pull requests (no direct pushes, no force pushes, no deleting `main`).
- A pull request can be merged only when these checks have passed: **Unit tests (Windows)**, **Dependency audit** and **Build and smoke test (unsigned)**.
- No approving review is required, because the project has one maintainer.
- Repository admins can still merge a pull request whose checks did not run when that is intended, for example the weekly lock refresh pull request (see below). GitHub shows a "bypass" option for that.

To apply it:
1. Download `protect-main.json` from the repository.
2. Open **Settings > Rules > Rulesets**.
3. Click **New ruleset > Import a ruleset** and choose the file.
4. Check the summary and click **Create**.

Release tags (`v*`) are not affected, so tagging a release works as before.

### 2. Allow the lock refresh workflow to open pull requests
**Settings > Actions > General > Workflow permissions**: tick **Allow GitHub Actions to create and approve pull requests**, then save.

### 3. Security features
In **Settings > Advanced Security** (called **Code security** on some accounts), turn on:
- **Private vulnerability reporting**, so people can report security problems privately (see [`SECURITY.md`](../SECURITY.md)).
- **Dependabot alerts** and **Dependabot security updates**.
- **Code scanning** results appear automatically from the CodeQL workflow; nothing else to enable.

### 4. Social preview and topics
- **Settings > General > Social preview > Edit > Upload an image**: choose [`docs/images/social-preview.png`](images/social-preview.png) (1280 by 640). Links to the repository then show this card.
- On the repository's main page, click the gear next to **About** and add the topics `windows`, `disk-cleanup`, `disk-space`, `cache-cleaner`, `storage-analyzer`, `duplicate-finder`, `open-source` and `python`, so people find DriveSweep through GitHub search.

## Releasing a new version

1. Make sure everything for the release is merged and the **Unreleased** section of [`CHANGELOG.md`](../CHANGELOG.md) describes it.
2. Bump the version (this updates every file and turns Unreleased into the new version):
   ```powershell
   python scripts\bump_version.py 0.7.1
   ```
3. Commit, open a pull request and merge it once CI is green.
4. Tag the merge commit on `main` and push the tag:
   ```powershell
   git checkout main
   ```
   ```powershell
   git pull
   ```
   ```powershell
   git tag -a v0.7.1 -m "DriveSweep v0.7.1"
   ```
   ```powershell
   git push origin v0.7.1
   ```
5. The release job checks that the tag matches the app version, builds, signs (when configured), and publishes the release with the changelog section as its notes.
6. Test the update path on a real PC with [`TESTING_UPDATES.md`](TESTING_UPDATES.md): update the previous version (portable, zip folder and Setup) to the new one, and check the rollback.
7. Update winget (see [`packaging/winget/README.md`](../packaging/winget/README.md)):
   ```powershell
   wingetcreate update rauell1.DriveSweep --version 0.7.1 --urls https://github.com/rauell1/drive-sweep/releases/download/v0.7.1/DriveSweep-Setup-0.7.1.exe --submit
   ```

`python scripts\bump_version.py --check` verifies at any time that all files carry the same version; a test runs the same check in CI.

## Dependencies

- **Python packages** are installed only from the hash locked [`requirements-dev.lock`](../requirements-dev.lock). Every Monday the **Refresh dependency lock** workflow moves it to the newest allowed versions, installs them, runs the tests and the vulnerability audit on Windows, refreshes `THIRD_PARTY_NOTICES.txt`, and only then opens a pull request. Pull requests opened by a workflow do not start CI by themselves, which is why the workflow tests first; merge it with the admin bypass. To refresh by hand: `python scripts\refresh_lock.py --upgrade` (needs [uv](https://docs.astral.sh/uv/)).
- **GitHub Actions** are pinned to commit SHAs. Dependabot opens one grouped pull request a week when new versions exist. Before merging a major version, check that the action's inputs we use still exist.

## Test builds

Every pull request uploads an unsigned **drivesweep-test-build** artifact (kept 7 days) from the **Build and smoke test** job. Download it from the pull request's Checks tab to try a change on a real PC before merging. For updates, follow [`TESTING_UPDATES.md`](TESTING_UPDATES.md) once the release is published.
