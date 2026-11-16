"""winget manifest templates and the submission builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prepare_winget", ROOT / "scripts" / "prepare_winget.py")
prepare_winget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_winget)


def test_render_fills_version_hash_and_urls():
    text = (ROOT / "packaging" / "winget" / "rauell1.DriveSweep.installer.yaml").read_text(encoding="utf-8")
    out = prepare_winget.render(text, "9.8.7", "ab" * 32, "2030-01-02")
    assert "PackageVersion: 9.8.7" in out
    assert "ReleaseDate: 2030-01-02" in out
    assert "InstallerSha256: " + ("AB" * 32) in out
    assert "releases/download/v9.8.7/DriveSweep-Setup-9.8.7.exe" in out
    assert "REPLACE_WITH" not in out
    assert "Template:" not in out
    assert out.startswith("# yaml-language-server: $schema=")


def test_templates_share_identifier_version_and_schema():
    files = list((ROOT / "packaging" / "winget").glob("rauell1.DriveSweep*.yaml"))
    assert len(files) == 3
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert "PackageIdentifier: rauell1.DriveSweep" in text
        assert "ManifestVersion: 1.12.0" in text


def test_product_code_matches_installer_app_id():
    iss = (ROOT / "installer" / "DriveSweep.iss").read_text(encoding="utf-8")
    app_id = iss.split("AppId={{", 1)[1].split("}", 1)[0]
    manifest = (ROOT / "packaging" / "winget" / "rauell1.DriveSweep.installer.yaml").read_text(encoding="utf-8")
    assert f"ProductCode: '{{{app_id}}}_is1'" in manifest
    version = iss.split('#define MyAppVersion "', 1)[1].split('"', 1)[0]
    assert f"PackageVersion: {version}" in manifest
