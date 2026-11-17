"""Every interface phrase that app.js passes to L() or LH() is translated in every language."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "app" / "ui" / "app.js"
I18N_JS = ROOT / "app" / "ui" / "i18n.js"
INDEX_HTML = ROOT / "app" / "ui" / "index.html"
DASHES = ("–", "—")


def _literal_phrases() -> set[str]:
    src = APP_JS.read_text(encoding="utf-8")
    phrases = set()
    for match in re.finditer(r"\bLH?\(\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')", src):
        raw = match.group(1)
        if raw.startswith("'"):
            raw = '"' + raw[1:-1].replace('\\\'', "'").replace('"', '\\"') + '"'
        phrases.add(json.loads(raw))
    return phrases


class _MarkedText(HTMLParser):
    """Collects the English text of index.html elements marked data-l, data-l-init and data-l-attr."""

    VOID = {"input", "br", "img", "meta", "link", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[list] = []
        self.found: set[str] = set()

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for name in (d.get("data-l-attr") or "").split(","):
            if d.get(name.strip()):
                self.found.add(d[name.strip()])
        if tag not in self.VOID:
            self.stack.append([tag, d, ""])

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2] += data

    def handle_endtag(self, tag):
        while self.stack:
            open_tag, attrs, text = self.stack.pop()
            if open_tag == tag:
                if ("data-l" in attrs or "data-l-init" in attrs) and text.strip():
                    self.found.add(text.strip())
                break


def _html_phrases() -> set[str]:
    parser = _MarkedText()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser.found


def _phrase_tables() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not available")
    script = (
        "global.window = {}; global.document = { querySelectorAll: () => [] };"
        f"require({json.dumps(str(I18N_JS))});"
        "console.log(JSON.stringify(window.DriveSweepI18n.PHRASES));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def test_every_phrase_in_app_js_is_translated():
    used = _literal_phrases()
    assert len(used) > 200, "phrase extraction found too few phrases"
    tables = _phrase_tables()
    assert set(tables) == {"es", "fr", "de", "pt"}
    for lang, table in tables.items():
        missing = sorted(p for p in used if p not in table)
        assert not missing, f"{lang} is missing translations for: {missing[:10]}"


def test_every_marked_phrase_in_index_html_is_translated():
    used = _html_phrases()
    assert len(used) > 50, "index.html phrase extraction found too few phrases"
    for lang, table in _phrase_tables().items():
        missing = sorted(p for p in used if p not in table)
        assert not missing, f"{lang} is missing translations for: {missing[:10]}"


def test_translations_keep_placeholders_and_avoid_dashes():
    for lang, table in _phrase_tables().items():
        for english, translated in table.items():
            assert translated.strip(), f"{lang}: empty translation for {english!r}"
            assert sorted(re.findall(r"\{\w+\}", english)) == sorted(re.findall(r"\{\w+\}", translated)), (
                f"{lang}: placeholders differ for {english!r}"
            )
            assert not any(d in translated for d in DASHES), f"{lang}: dash in translation of {english!r}"
