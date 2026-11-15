"""Exact duplicate file finder operating on already-scanned DriveScanner nodes."""

from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from typing import Callable

from app.safety import classify_path_risk, format_bytes, is_os_protected_path, to_os_path
from app.storage import get_exclusions, is_path_excluded

_PARTIAL_CHUNK = 8192
_STREAM_CHUNK = 131072


def _partial_digest(os_path: str, file_size: int) -> str | None:
    """Compute a fast fingerprint from head and tail chunks of a file."""
    hasher = hashlib.blake2b(digest_size=16)
    try:
        with open(os_path, "rb") as fh:
            head = fh.read(_PARTIAL_CHUNK)
            hasher.update(head)
            if file_size > _PARTIAL_CHUNK * 2:
                fh.seek(max(0, file_size - _PARTIAL_CHUNK))
                hasher.update(fh.read(_PARTIAL_CHUNK))
        return hasher.hexdigest()
    except OSError:
        return None


def _full_sha256(os_path: str, cancel_event: threading.Event | None = None) -> str | None:
    """Stream full file contents to compute SHA-256."""
    hasher = hashlib.sha256()
    try:
        with open(os_path, "rb") as fh:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return None
                chunk = fh.read(_STREAM_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def find_duplicates(
    nodes: dict,
    *,
    min_size_bytes: int = 102400,
    max_groups: int = 250,
    exclusions: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict:
    """Find byte-for-byte duplicate files across indexed scanner nodes."""
    min_bytes = max(1, int(min_size_bytes))
    ex_list = exclusions if exclusions is not None else get_exclusions()

    if progress_cb:
        progress_cb("Grouping files by size...", 0, 1)

    by_size: dict[int, list[tuple[str, str, float]]] = defaultdict(list)
    for dpath, node in nodes.items():
        if cancel_event is not None and cancel_event.is_set():
            return {"cancelled": True, "groups": [], "total_groups": 0, "reclaimable_bytes": 0, "reclaimable_human": "0 B"}
        if getattr(node, "is_protected", False):
            continue
        for fname, fsize, fmtime, _fext in getattr(node, "files", ()):
            if fsize < min_bytes:
                continue
            fpath = os.path.join(dpath, fname)
            by_size[fsize].append((fpath, fname, fmtime))

    size_candidates = [(sz, items) for sz, items in by_size.items() if len(items) >= 2]
    total_phase = sum(len(items) for _, items in size_candidates) or 1
    processed = 0

    partial_buckets: dict[tuple[int, str], list[tuple[str, str, float]]] = defaultdict(list)
    for fsize, items in size_candidates:
        for fpath, fname, fmtime in items:
            if cancel_event is not None and cancel_event.is_set():
                return {"cancelled": True, "groups": [], "total_groups": 0, "reclaimable_bytes": 0, "reclaimable_human": "0 B"}
            processed += 1
            if progress_cb and (processed == 1 or processed % 40 == 0):
                progress_cb("Checking quick signatures...", processed, total_phase)
            if is_os_protected_path(fpath):
                continue
            p_sig = _partial_digest(to_os_path(fpath), fsize)
            if p_sig:
                partial_buckets[(fsize, p_sig)].append((fpath, fname, fmtime))

    hash_candidates = [(k[0], items) for k, items in partial_buckets.items() if len(items) >= 2]
    total_hash = sum(len(items) for _, items in hash_candidates) or 1
    hashed_count = 0

    exact_buckets: dict[tuple[int, str], list[tuple[str, str, float]]] = defaultdict(list)
    for fsize, items in hash_candidates:
        for fpath, fname, fmtime in items:
            if cancel_event is not None and cancel_event.is_set():
                return {"cancelled": True, "groups": [], "total_groups": 0, "reclaimable_bytes": 0, "reclaimable_human": "0 B"}
            hashed_count += 1
            if progress_cb and (hashed_count == 1 or hashed_count % 10 == 0):
                progress_cb("Verifying exact SHA-256 matches...", hashed_count, total_hash)
            digest = _full_sha256(to_os_path(fpath), cancel_event=cancel_event)
            if digest:
                exact_buckets[(fsize, digest)].append((fpath, fname, fmtime))

    groups: list[dict] = []
    total_reclaimable = 0

    for (fsize, digest), copies in exact_buckets.items():
        if len(copies) < 2:
            continue
        # Keep the newest (or shortest-path if timestamps tie) copy as primary
        ordered = sorted(copies, key=lambda c: (-c[2], len(c[0]), c[0].lower()))
        reclaim = (len(ordered) - 1) * fsize
        total_reclaimable += reclaim

        copy_entries = []
        for idx, (fpath, fname, fmtime) in enumerate(ordered):
            excluded = is_path_excluded(fpath, ex_list)
            protected = is_os_protected_path(fpath)
            risk = classify_path_risk(fpath, is_dir=False, age_days=0)
            copy_entries.append({
                "path": fpath,
                "name": fname,
                "dir_path": os.path.dirname(fpath),
                "size_bytes": fsize,
                "size_human": format_bytes(fsize),
                "mtime": fmtime,
                "keep_recommended": idx == 0,
                "excluded": excluded,
                "is_protected": protected,
                "risk_level": risk["risk_level"],
                "risk_reason": risk["risk_reason"],
            })

        groups.append({
            "sha256_short": digest[:12],
            "name": ordered[0][1],
            "size_bytes": fsize,
            "size_human": format_bytes(fsize),
            "copy_count": len(ordered),
            "reclaimable_bytes": reclaim,
            "reclaimable_human": format_bytes(reclaim),
            "copies": copy_entries,
        })

    groups.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)
    return {
        "cancelled": False,
        "total_groups": len(groups),
        "reclaimable_bytes": total_reclaimable,
        "reclaimable_human": format_bytes(total_reclaimable),
        "groups": groups[:max_groups],
    }
