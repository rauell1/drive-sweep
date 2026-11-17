"""Every string added for the first run notice, warnings and update text is translated."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KEYS = [
    "fr_title", "fr_intro", "fr_backup_b", "fr_backup", "fr_recycle_b", "fr_recycle", "fr_protect_b",
    "fr_protect", "fr_local_b", "fr_local", "fr_updates_opt", "fr_affiliation", "fr_ok", "recycle_note",
    "winold_title", "winold_body", "wsl_title", "wsl_heading", "wsl_body", "wsl_confirm", "wsl_prompt",
    "upd_method_exe", "upd_method_folder", "upd_method_setup", "upd_folder_in", "upd_check_label",
    "upd_check_desc", "clear_logs", "clear_logs_tip", "logs_cleared", "restart_admin", "restart_admin_tip",
]

# Translations that are correctly identical to English.
SAME_AS_ENGLISH = {("de", "upd_folder_in")}


def test_new_strings_have_own_translation_in_every_language():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not available")
    script = (
        "global.window = {}; global.document = { querySelectorAll: () => [] };"
        f"require({json.dumps(str(ROOT / 'app' / 'ui' / 'i18n.js'))});"
        "const S = window.DriveSweepI18n.STRINGS; const out = {};"
        "for (const [lang, d] of Object.entries(S)) out[lang] = d;"
        "console.log(JSON.stringify(out));"
    )
    packs = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
    assert set(packs) == {"en", "es", "fr", "de", "pt"}
    for key in KEYS:
        english = packs["en"].get(key)
        assert english, f"en.{key} missing"
        for lang in ("es", "fr", "de", "pt"):
            value = packs[lang].get(key)
            assert value, f"{lang}.{key} is missing"
            if (lang, key) not in SAME_AS_ENGLISH:
                assert value != english, f"{lang}.{key} is still English"
            for placeholder in ("{name}", "{folder}", "{path}"):
                assert (placeholder in english) == (placeholder in value), f"{lang}.{key} placeholder {placeholder}"
