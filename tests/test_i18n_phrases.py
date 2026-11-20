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
DASHES = ("\u2013", "\u2014")


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


def _cleanup_error_phrases() -> list[str]:
    src = APP_JS.read_text(encoding="utf-8")
    block = re.search(r"const CLEANUP_ERROR_PHRASES = \[(.*?)\];", src, re.S)
    assert block, "CLEANUP_ERROR_PHRASES not found in app.js"
    return [json.loads(m) for m in re.findall(r'"(?:[^"\\]|\\.)*"', block.group(1))]


def test_cleanup_engine_messages_are_translated():
    """The fixed skip messages from app/safety.py are listed in app.js and translated."""
    listed = set(_cleanup_error_phrases())
    safety_src = (ROOT / "app" / "safety.py").read_text(encoding="utf-8")
    func = re.search(r"def _friendly_delete_error\(.*?\n(?=def )", safety_src, re.S)
    assert func, "_friendly_delete_error not found"
    returned = set(re.findall(r'return "([^"]+)"', func.group(0)))
    returned |= set(re.findall(r'return \w+ or "([^"]+)"', func.group(0)))
    assert returned, "no fixed messages found in _friendly_delete_error"
    assert returned <= listed, f"add these to CLEANUP_ERROR_PHRASES in app.js: {sorted(returned - listed)}"
    for lang, table in _phrase_tables().items():
        missing = sorted(p for p in listed if p not in table)
        assert not missing, f"{lang} is missing translations for: {missing}"


# Hard coded English shown to the user, outside L(), LH() or tr(). Catches text set directly on a
# button or message, shown in a toast, or used as a fallback after "||".
_ENGLISH_LITERAL = r"""["'`][A-Z][a-z]+(?:[ .!]|\.\.\.)[^"'`]*["'`]"""
_UNTRANSLATED_PATTERNS = [
    re.compile(r"(?:textContent|innerText)\s*=\s*[^;]*?(?:\?|:|\|\||=)\s*" + _ENGLISH_LITERAL),
    re.compile(r"showToast\(\s*[^;]*?" + _ENGLISH_LITERAL),
    re.compile(r"\btext:\s*[^,]*?" + _ENGLISH_LITERAL),
    re.compile(r"(?:textContent|innerText)\s*=\s*[\"'`][A-Z][a-z]"),
]
# Lines that may keep English: fallbacks used only when the translation file did not load, and
# messages sent to the local diagnostics log rather than shown to the user.
_ALLOWED = ("window.DriveSweepI18n ?", "report_ui_error(", ': "Large Files & Folders"', ": \"Review large files")


def test_no_hard_coded_english_in_app_js():
    offenders = []
    for number, line in enumerate(APP_JS.read_text(encoding="utf-8").splitlines(), 1):
        if any(a in line for a in _ALLOWED):
            continue
        stripped = re.sub(r"\b(?:LH?|tr)\(\s*(\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')", "L(_)", line)
        if any(p.search(stripped) for p in _UNTRANSLATED_PATTERNS):
            offenders.append(f"{number}: {line.strip()[:120]}")
    assert not offenders, "Wrap these in L() and add translations:\n" + "\n".join(offenders)


def _server_messages() -> list[str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("server_messages", ROOT / "scripts" / "server_messages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.collect()


def test_every_backend_message_is_translated():
    """Errors, statuses and explanations from app/*.py are translated in every language.

    When this fails after adding a message in Python, add its translation to app/ui/i18n.js.
    """
    messages = _server_messages()
    assert len(messages) > 150, "message extraction found too few messages"
    for lang, table in _phrase_tables().items():
        missing = sorted(m for m in messages if m not in table)
        assert not missing, f"{lang} is missing translations for backend messages: {missing[:10]}"


def test_server_templates_match_backend_messages():
    """SERVER_TEMPLATES in i18n.js lists exactly the backend messages with a variable part."""
    src = I18N_JS.read_text(encoding="utf-8")
    block = re.search(r"const SERVER_TEMPLATES = \[(.*?)\];", src, re.S)
    assert block, "SERVER_TEMPLATES not found in i18n.js"
    listed = {json.loads(m) for m in re.findall(r'"(?:[^"\\]|\\.)*"', block.group(1))}
    expected = {m for m in _server_messages() if re.search(r"\{\w+\}", m)}
    assert listed == expected, f"regenerate SERVER_TEMPLATES: missing {sorted(expected - listed)[:5]}, extra {sorted(listed - expected)[:5]}"


def test_phrase_translates_messages_with_variable_parts():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not available")
    script = (
        "global.window = {}; global.document = { querySelectorAll: () => [] };"
        f"require({json.dumps(str(I18N_JS))});"
        "const I = window.DriveSweepI18n; I.setLanguage('de');"
        "console.log(JSON.stringify(["
        "I.phrase('Folder does not exist: C:\\\\Fotos (2024)'),"
        "I.phrase('JavaScript packages for a project. Inactive for 45 days. Safe to delete if inactive; restore anytime with npm or pnpm install.'),"
        "I.phrase('holiday photo.jpg')]));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    folder, js_note, filename = json.loads(out.stdout)
    assert folder == "Der Ordner existiert nicht: C:\\Fotos (2024)"
    assert "Seit 45 Tagen inaktiv." in js_note and js_note.startswith("JavaScript-Pakete")
    assert filename == "holiday photo.jpg"
