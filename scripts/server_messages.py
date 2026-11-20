"""List the fixed English messages the Python side shows to users, for translation.

DriveSweep's interface translates these on screen (see phrase() in app/ui/i18n.js). A message
with a variable part, such as f"Folder does not exist: {target_path}", becomes the template
"Folder does not exist: {target_path}"; the interface matches it and keeps the variable as is.

Collected:
- string values of the keys error, message, reason, risk_reason and note in dict literals
- note= keyword arguments (cleanup item notes)
- every string returned by safety.explain_path_human, safety._friendly_delete_error and
  DriveSweepAPI._undo_target
- Cleanup Log action names: "action" values, action_label and *_ACTION constants

Run directly to print the list as JSON.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    "api.py", "auto_clean.py", "recycle_restore.py", "reports.py", "safety.py", "scanner.py",
    "scheduler.py", "system_tools.py", "updater.py", "presets.py",
]
# "action" names the entries in the Cleanup Log ("Cleanup", "Empty Recycle Bin", ...).
MESSAGE_KEYS = {"error", "message", "reason", "risk_reason", "note", "action"}
EXPLAIN_FUNCTIONS = {"explain_path_human", "_friendly_delete_error", "_undo_target"}


def _placeholder(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "value"


def _text(node: ast.AST | None) -> list[str]:
    """English text of a string or f-string node, with {name} for variable parts."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + _placeholder(value.value) + "}")
        return ["".join(parts)]
    if isinstance(node, ast.IfExp):
        return _text(node.body) + _text(node.orelse)
    if isinstance(node, ast.Tuple):  # return None, "reason"
        out_t: list[str] = []
        for value in node.elts:
            out_t += _text(value)
        return out_t
    if isinstance(node, ast.BoolOp):
        out: list[str] = []
        for value in node.values:
            out += _text(value)
        return out
    return []


def _keep(text: str) -> bool:
    stripped = text.strip()
    # Real sentences only: skip empty values, bare placeholders and lowercase identifiers.
    return bool(stripped) and stripped[0].isupper() and any(c.isalpha() for c in stripped.replace("{", " "))


def collect() -> list[str]:
    found: set[str] = set()
    for name in SOURCES:
        tree = ast.parse((ROOT / "app" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in MESSAGE_KEYS:
                        found.update(_text(value))
            elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and (t.id == "action_label" or t.id.endswith("_ACTION")) for t in node.targets
            ):
                found.update(_text(node.value))
            elif isinstance(node, ast.keyword) and node.arg == "note":
                found.update(_text(node.value))
            elif isinstance(node, ast.FunctionDef) and node.name in EXPLAIN_FUNCTIONS:
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Return):
                        found.update(_text(inner.value))
                    elif isinstance(inner, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id.endswith("_note") for t in inner.targets
                    ):
                        found.update(_text(inner.value))
    return sorted(t for t in found if _keep(t))


if __name__ == "__main__":
    json.dump(collect(), sys.stdout, ensure_ascii=False, indent=1)
    print()
