# Setting up code signing for DriveSweep

Signed releases stop the "Windows protected your PC" warning from being shown as an unknown publisher, prove the files came from this project, and let DriveSweep's updater insist that every future update comes from the same publisher.

The release pipeline (`.github/workflows/ci-release.yml`) is already wired for two providers. Pick **one**:

| | SignPath Foundation | Azure Trusted Signing |
| --- | --- | --- |
| Cost | Free for approved open source projects | Paid monthly Azure subscription |
| Who can use it | Open source projects with an OSI license (MIT qualifies) | Organizations and individuals that pass Microsoft's identity validation in supported countries (check Microsoft's current eligibility) |
| Certificate shows | SignPath Foundation, on behalf of the project | Your validated legal name |
| Approval per release | You approve each signing request in SignPath | None |

**Recommendation: SignPath Foundation.** It is free, the repository already meets its published requirements, and the pipeline and artifact configurations below are ready for it.

> **Important: choose once.** After the first signed release, DriveSweep only installs updates signed by the **same publisher**. Switching providers later changes the publisher name, so existing users would have to download the next version by hand.

---

## Option A: SignPath Foundation (recommended)

### 1. What the repository already provides
SignPath Foundation reviews these before approving a project. They are already in place:
- An OSI approved license: [`LICENSE`](../LICENSE) (MIT).
- A **Code Signing Policy** section and **Project Team & Roles** in the [README](../README.md#code-signing-policy).
- A privacy policy: [`PRIVACY.md`](../PRIVACY.md).
- Builds that run only on GitHub Actions from the public repository, with pinned actions, hash locked dependencies and build provenance.
- Artifact configurations: [`.signpath/artifact-configurations/`](../.signpath/artifact-configurations/).

### 2. Apply
1. Go to the SignPath Foundation website (signpath.org) and open the application for open source projects.
2. Give the repository URL `https://github.com/rauell1/drive-sweep`, a short description, and yourself as the maintainer.
3. Wait for approval. SignPath then creates an organization and a project for DriveSweep and sends you the login details.

### 3. Configure the SignPath project (in the SignPath web app)
1. **Link GitHub.** Add GitHub.com as a trusted build system for your organization and link it to the DriveSweep project. This lets SignPath verify that each signing request really came from this repository's GitHub Actions.
2. **Create two artifact configurations** with these exact slugs, pasting the XML from the repository:
   - `executables`: contents of [`.signpath/artifact-configurations/executables.xml`](../.signpath/artifact-configurations/executables.xml)
   - `installer`: contents of [`.signpath/artifact-configurations/installer.xml`](../.signpath/artifact-configurations/installer.xml)

   SignPath checks the XML when you save it. If it reports an error, tell your developer the exact message.
3. **Signing policies.** SignPath Foundation projects come with a `test-signing` policy (test certificate, for trying the setup) and a `release-signing` policy (real certificate, each request approved by you).
4. **Create an API token** for a CI user that is allowed to submit requests to both policies. Copy the token; it is shown only once.
5. Note your **organization ID** and the **project slug** (both are shown in the SignPath web app).

### 4. Add the GitHub secrets
In GitHub: **Settings > Secrets and variables > Actions > New repository secret**. Add:

| Secret | Value |
| --- | --- |
| `SIGNPATH_API_TOKEN` | The CI user's API token |
| `SIGNPATH_ORGANIZATION_ID` | Your SignPath organization ID |
| `SIGNPATH_PROJECT_SLUG` | The project slug, for example `drive-sweep` |
| `SIGNPATH_SIGNING_POLICY_SLUG` | `test-signing` for now |

### 5. Do a test run (nothing is published)
1. In GitHub, open **Actions > Build, Test & Release > Run workflow** on `main`.
2. The run uploads the executables and then the installer to SignPath. Approve the requests in SignPath if it asks.
3. When the run finishes, download the `drivesweep-win64` artifact and check that `DriveSweep.exe` and `DriveSweep-Setup-*.exe` show a **Digital Signatures** tab (right click > Properties). A test certificate is expected to show as not trusted.

The pipeline **refuses to publish a tagged release with the test policy**, because Windows does not trust the test certificate and DriveSweep's updater would reject it.

### 6. Switch to real signing and release
1. Change the secret `SIGNPATH_SIGNING_POLICY_SLUG` to `release-signing`.
2. Bump the version and push a tag (for example `v0.7.1`).
3. While the release job runs, **approve two signing requests** in SignPath: first the executables, then the installer. The job waits up to two hours for each approval.
4. The published release notes will then include the required line: *Free code signing provided by SignPath.io, certificate by SignPath Foundation.*

### 7. Check the result
In PowerShell on Windows:

```powershell
Get-AuthenticodeSignature .\DriveSweep-Setup-0.7.1.exe | Format-List Status, SignerCertificate
```

`Status` should be `Valid`.

---

## Option B: Azure Trusted Signing

1. In the Azure portal, create a **Trusted Signing account** and complete **identity validation** (for an individual or your organization).
2. Create a **Public Trust certificate profile**.
3. Create an **app registration** (service principal) with a client secret, and give it the **Trusted Signing Certificate Profile Signer** role on the certificate profile.
4. Add these GitHub secrets:

| Secret | Value |
| --- | --- |
| `AZURE_TENANT_ID` | Directory (tenant) ID |
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_CLIENT_SECRET` | App registration client secret |
| `AZURE_SIGNING_ENDPOINT` | Your account's endpoint URL, for example `https://eus.codesigning.azure.net/` |
| `AZURE_SIGNING_ACCOUNT` | Trusted Signing account name |
| `AZURE_SIGNING_PROFILE` | Certificate profile name |

5. Test with **Run workflow** (nothing is published), then push a version tag. No per release approval is needed.

---

## How signing fits into the pipeline

1. `build.ps1 -Stage Binaries` builds `DriveSweep.exe` and the folder bundle.
2. **Executables are signed** (SignPath `executables` configuration, or Azure).
3. `build.ps1 -Stage Package` builds the zip and Setup **from the signed exe**.
4. **The installer is signed** (SignPath `installer` configuration, or Azure).
5. Checksums, SBOM and build provenance are created from the signed files, and the release is published.
