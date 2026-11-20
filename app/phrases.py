"""Translations for the few texts the Python side shows without the interface.

The interface's translations live in app/ui/i18n.js (PHRASES). The scheduled cleanup runs from
Task Scheduler with no window, and the preview report is written by Python, so this module reads
the same table instead of keeping a second copy. English is the fallback for anything missing.
"""

from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from app.storage import load_settings

_LANG_BLOCK = re.compile(r"^    (es|fr|de|pt): \{\n(.*?)^    \},", re.M | re.S)
# One generated entry per line: "English": "Translation",
_ENTRY = re.compile(r'^\s*("(?:[^"\\]|\\.)*"): ("(?:[^"\\]|\\.)*"),\s*$', re.M)


def _i18n_path() -> Path | None:
    candidates = [Path(__file__).resolve().parent / "ui" / "i18n.js"]
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "app" / "ui" / "i18n.js")
    return next((p for p in candidates if p.is_file()), None)


@lru_cache(maxsize=1)
def _tables() -> dict[str, dict[str, str]]:
    path = _i18n_path()
    if not path:
        return {}
    src = path.read_text(encoding="utf-8")
    start = src.find("const PHRASES = {")
    if start < 0:
        return {}
    tables: dict[str, dict[str, str]] = {}
    for lang, body in _LANG_BLOCK.findall(src[start:]):
        table = {}
        for en, tr in _ENTRY.findall(body):
            try:
                table[json.loads(en)] = json.loads(tr)
            except json.JSONDecodeError:
                continue
        tables.setdefault(lang, table)
    return tables


def current_language() -> str:
    try:
        return str(load_settings().get("language", "en"))
    except Exception:
        return "en"


def phrase(text: str, lang: str | None = None, **values) -> str:
    """Translate ``text`` (an English phrase from i18n.js) and fill in {placeholders}."""
    lang = lang or current_language()
    out = _tables().get(lang, {}).get(text, text) if lang != "en" else text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
