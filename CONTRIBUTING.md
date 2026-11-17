# Contributing to DriveSweep

Thanks for helping. Bug reports, ideas, translations and pull requests are all welcome. By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and ideas

- Use the issue forms under **Issues > New issue**. They ask for the details needed to reproduce a problem.
- For a crash or error, attach the relevant part of the diagnostics log (**Settings & Updates > Open Diagnostics Log**). Remove any file paths you do not want to share.
- **Security problems:** do not open a public issue; follow [SECURITY.md](SECURITY.md).

## Development setup (Windows)

```powershell
git clone https://github.com/rauell1/drive-sweep.git
cd drive-sweep
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe main.py
```

- Run the tests: `.\.venv\Scripts\python.exe -m pytest -v`. Most tests also run on Linux; Windows only tests skip there.
- Build the executables and installer locally: `.\build.ps1` (Inno Setup needed for the installer).
- The interface is plain HTML, CSS and JavaScript in `app/ui/`; the Python backend is in `app/`.

## Pull requests

1. Fork the repository and create a branch from `main`.
2. Keep each pull request focused on one change, and add or update tests for behavior changes.
3. Add a line to the **Unreleased** section of [CHANGELOG.md](CHANGELOG.md) for anything users will notice.
4. Make sure `pytest` passes. CI also builds the app, installs and uninstalls it, and uploads a test build you can try.
5. Fill in the pull request template.

### Safety rules for cleanup code

DriveSweep deletes files, sometimes with Administrator rights. Changes to `app/safety.py`, `app/presets.py`, `app/updater.py` or `app/system_tools.py` must keep these guarantees, and should come with tests:
- Never delete protected Windows paths, other user accounts, or anything on the Always Keep list.
- Never follow folder links (junctions, symbolic links, mount points) while deleting.
- Never put a file path or other untrusted text inside a command line; pass it as a separate argument or an environment variable.
- Personal folders are never selected automatically.

### Translations

Text shown in the app lives in `app/ui/i18n.js` (English, Spanish, French, German, Portuguese). When you add text, add a key for every language; `tests/test_i18n_new_strings.py` shows how the new keys are checked. Improvements to existing translations are very welcome.

## Releases

Releases are made by the maintainer; see [docs/MAINTAINING.md](docs/MAINTAINING.md).
