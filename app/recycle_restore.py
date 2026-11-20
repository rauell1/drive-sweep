"""Put items from the Windows Recycle Bin back where they were deleted from.

Windows keeps each item in the Recycle Bin as two files in ``X:\\$Recycle.Bin\\<user SID>\\``:
``$I<id>`` holds the original path, the size and the deletion time, and ``$R<id>`` is the item
itself. Restoring moves ``$R<id>`` back to its original path and removes ``$I<id>``, which is
what Explorer's Restore does. Both files are on the same drive as the original location, so
the move is a rename and never copies data.

Used by Undo last cleanup: only items deleted while that cleanup ran, from inside the folders it
cleaned, are restored, and nothing that already exists is overwritten.
"""

from __future__ import annotations

import os
import string
import struct
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.safety import find_link_in_path, format_bytes

# FILETIME counts 100 ns steps since 1601-01-01; the Unix epoch is this many steps later.
_FILETIME_UNIX_EPOCH = 116444736000000000
_V1_PATH_BYTES = 520  # Windows Vista, 7 and 8: fixed size path field (260 UTF-16 characters)
_MAX_INFO_FILE_BYTES = 70000  # a version 2 record holds at most 32767 UTF-16 characters
# Recycle Bin deletion times can be stamped slightly before or after the cleanup's own clock.
DEFAULT_SLACK = timedelta(seconds=10)


@dataclass(frozen=True)
class RecycledItem:
    info_path: Path
    data_path: Path
    original_path: str
    size_bytes: int
    deleted_at: datetime


def parse_info_file(data: bytes) -> tuple[str, int, datetime] | None:
    """Read a ``$I`` record: (original path, size in bytes, deletion time in UTC), or None."""
    if len(data) < 24:
        return None
    version, size, filetime = struct.unpack_from("<qqq", data, 0)
    if version == 1:
        raw = data[24 : 24 + _V1_PATH_BYTES]
        path = raw.decode("utf-16-le", errors="ignore").split("\x00", 1)[0]
    elif version == 2:
        if len(data) < 28:
            return None
        (chars,) = struct.unpack_from("<i", data, 24)
        if chars <= 0 or 28 + chars * 2 > len(data):
            return None
        path = data[28 : 28 + chars * 2].decode("utf-16-le", errors="ignore").split("\x00", 1)[0]
    else:
        return None
    if not path:
        return None
    try:
        deleted_at = datetime.fromtimestamp((filetime - _FILETIME_UNIX_EPOCH) / 10_000_000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return path, max(0, int(size)), deleted_at


def default_bin_roots() -> list[Path]:
    """The ``$Recycle.Bin`` folder of every drive that has one (Windows only)."""
    if os.name != "nt":
        return []
    roots = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\$Recycle.Bin")
        try:
            if root.is_dir():
                roots.append(root)
        except OSError:
            continue
    return roots


def list_recycled(bin_roots: Iterable[Path] | None = None) -> list[RecycledItem]:
    """Every item in the Recycle Bin folders this user can read."""
    items: list[RecycledItem] = []
    for root in default_bin_roots() if bin_roots is None else bin_roots:
        try:
            user_dirs = [p for p in Path(root).iterdir() if p.is_dir()]
        except OSError:
            continue
        for user_dir in user_dirs:
            try:
                info_files = [p for p in user_dir.iterdir() if p.name.upper().startswith("$I")]
            except OSError:
                continue  # another account's Recycle Bin
            for info in info_files:
                try:
                    if info.stat().st_size > _MAX_INFO_FILE_BYTES:
                        continue
                    parsed = parse_info_file(info.read_bytes())
                except OSError:
                    continue
                if not parsed:
                    continue
                data = info.with_name("$R" + info.name[2:])
                if not os.path.lexists(data):
                    continue
                path, size, deleted_at = parsed
                items.append(RecycledItem(info, data, path, size, deleted_at))
    return items


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


@lru_cache(maxsize=4096)
def _canon(path: str) -> str:
    """Comparable form of a path. realpath turns short 8.3 names (C:\\Users\\JOHNSM~1) into long
    ones for the parts that exist, so a TEMP folder given in short form still matches the long
    path Windows records in the Recycle Bin. Parts that no longer exist are kept as written."""
    try:
        return _norm(os.path.realpath(path))
    except (OSError, ValueError):
        return _norm(path)


def _is_within(path: str, root: str) -> bool:
    for p, r in ((_norm(path), _norm(root)), (_canon(path), _canon(root))):
        if p == r or p.startswith(r.rstrip("\\/") + os.sep):
            return True
    return False


def find_cleanup_items(
    roots: Iterable[str],
    started_at: datetime,
    finished_at: datetime,
    bin_roots: Iterable[Path] | None = None,
    slack: timedelta = DEFAULT_SLACK,
    recycled: list[RecycledItem] | None = None,
) -> list[RecycledItem]:
    """Recycle Bin items deleted between start and finish from inside one of ``roots``.

    Pass ``recycled`` (from list_recycled) to check several cleanups with one read of the bin.
    """
    roots = [r for r in roots if r]
    if not roots:
        return []
    _canon.cache_clear()  # folders may have been created or removed since the last search
    low, high = started_at - slack, finished_at + slack
    found = [
        item
        for item in (list_recycled(bin_roots) if recycled is None else recycled)
        if low <= item.deleted_at <= high and any(_is_within(item.original_path, r) for r in roots)
    ]
    # Parents first, so a restored folder is in place before anything that belonged inside it.
    return sorted(found, key=lambda it: (len(_norm(it.original_path)), it.original_path))


def _same_drive(item: RecycledItem) -> bool:
    return os.path.splitdrive(_norm(item.original_path))[0] == os.path.splitdrive(_norm(str(item.info_path)))[0]


def restore_items(items: Iterable[RecycledItem]) -> dict:
    """Move each item back to its original path. Existing files are never overwritten."""
    restored: list[str] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    restored_bytes = 0
    for item in items:
        target = item.original_path
        if not os.path.isabs(target) or os.path.normpath(target) != target.rstrip("\\/") or not _same_drive(item):
            failed.append({"path": target, "error": "Not a valid original location for this Recycle Bin item."})
            continue
        if os.path.lexists(target):
            skipped.append({"path": target, "error": "A file or folder with this name already exists, so it was left in the Recycle Bin."})
            continue
        try:
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            link = find_link_in_path(parent)
            if link:
                failed.append({"path": target, "error": f"Not restored: {link} is a folder link."})
                continue
            os.rename(item.data_path, target)
        except OSError as exc:
            failed.append({"path": target, "error": f"Could not restore: {exc.strerror or exc}"})
            continue
        try:
            os.remove(item.info_path)
        except OSError:
            pass  # Windows ignores a leftover $I file without its $R partner
        restored.append(target)
        restored_bytes += item.size_bytes
    return {
        "ok": not failed,
        "restored": restored,
        "restored_count": len(restored),
        "restored_bytes": restored_bytes,
        "restored_human": format_bytes(restored_bytes),
        "skipped": skipped,
        "failed": failed,
    }
