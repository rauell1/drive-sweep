"""Fast, memory-lean, cancellable drive & directory scanner with age filtering."""

from __future__ import annotations

import os
import stat
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psutil

from app.safety import (
    CAUTION_EXTENSIONS,
    ScanGuard,
    classify_path_risk,
    format_bytes,
    is_os_protected_path,
    is_personal_guarded_path,
    strip_long_prefix,
    to_os_path,
)

FILE_CATEGORIES = (
    ("Archives & Images", {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".iso", ".img", ".vhdx", ".vmdk", ".vhd", ".msi", ".exe"}, "#8b5cf6"),
    ("Media & Video", {".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".wav", ".flac", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".psd"}, "#ec4899"),
    ("Code & Packages", {".js", ".ts", ".tsx", ".py", ".pyc", ".whl", ".jar", ".dll", ".so", ".lib", ".pdb", ".map", ".node", ".rs", ".go"}, "#3b82f6"),
    ("Documents & Data", {".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".json", ".parquet", ".db", ".sqlite", ".sqlite3", ".sql"}, "#06b6d4"),
    ("Logs, Cache & Temp", {".log", ".tmp", ".temp", ".cache", ".bak", ".dmp", ".old", ".etl"}, "#10b981"),
)

DEV_BLOAT_NAMES = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".turbo",
    ".parcel-cache",
    "target",
}


def _format_mtime(ts: float) -> tuple[str, int]:
    if not ts or ts <= 0:
        return "", 0
    try:
        date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        age_days = max(0, int((time.time() - ts) // 86400))
        return date_str, age_days
    except (OSError, OverflowError, ValueError):
        return "", 0


def list_drives() -> list[dict]:
    """Return available local/fixed/removable drives with capacity details."""
    drives: list[dict] = []
    seen: set[str] = set()

    for part in psutil.disk_partitions(all=False):
        mount = part.mountpoint
        norm = os.path.normcase(os.path.normpath(mount))
        if norm in seen:
            continue
        try:
            usage = psutil.disk_usage(mount)
        except OSError:
            continue
        seen.add(norm)
        total = usage.total
        used = usage.used
        free = usage.free
        pct = round((used / total) * 100, 1) if total > 0 else 0.0
        drives.append({
            "path": mount,
            "name": mount.rstrip("\\") or mount,
            "fstype": part.fstype or "",
            "opts": part.opts or "",
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "total_human": format_bytes(total),
            "used_human": format_bytes(used),
            "free_human": format_bytes(free),
            "used_percent": pct,
        })
    return drives


@dataclass
class DirNode:
    path: str
    name: str
    parent_path: str | None
    own_size: int = 0
    total_size: int = 0
    own_file_count: int = 0
    total_file_count: int = 0
    latest_mtime: float = 0.0
    child_dirs: list[str] = field(default_factory=list)
    # Compact file tuples stored once: (name, size, mtime, ext)
    files: list[tuple[str, int, float, str]] = field(default_factory=list)
    is_protected: bool = False
    is_personal: bool = False
    is_dev_bloat: bool = False


class DriveScanner:
    """Indexes a drive or folder into a single-copy tree with age & size queries."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

        self.status: str = "idle"
        self.error_message: str = ""
        self.root_path: str = ""
        self.files_scanned: int = 0
        self.dirs_scanned: int = 0
        self.bytes_scanned: int = 0
        self.skipped_count: int = 0
        self.current_path: str = ""
        self.started_at: float = 0.0
        self.finished_at: float = 0.0

        self._nodes: dict[str, DirNode] = {}
        self._largest_files: list[dict] = []
        self._dev_artifacts: list[dict] = []
        self.is_cached: bool = False
        self._scan_cache: dict[str, dict] = {}

    def start_scan(self, root_path: str, *, force: bool = False) -> dict:
        norm_root = os.path.abspath(os.path.normpath(root_path))
        if not os.path.exists(to_os_path(norm_root)):
            raise FileNotFoundError(f"Path does not exist: {norm_root}")

        cache_key = os.path.normcase(norm_root)
        self.cancel_scan()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            if not force and cache_key in self._scan_cache:
                snap = self._scan_cache[cache_key]
                self._cancel_event.clear()
                self.status = "done"
                self.error_message = ""
                self.root_path = snap["root_path"]
                self.files_scanned = snap["files_scanned"]
                self.dirs_scanned = snap["dirs_scanned"]
                self.bytes_scanned = snap["bytes_scanned"]
                self.skipped_count = snap["skipped_count"]
                self.current_path = snap["root_path"]
                self.started_at = 0.0
                self.finished_at = snap["elapsed_sec"]
                self._nodes = snap["nodes"]
                self._largest_files = snap["largest_files"]
                self._dev_artifacts = snap["dev_artifacts"]
                self.is_cached = True
                return self.get_status()

            self._cancel_event.clear()
            self.status = "scanning"
            self.error_message = ""
            self.root_path = norm_root
            self.files_scanned = 0
            self.dirs_scanned = 0
            self.bytes_scanned = 0
            self.skipped_count = 0
            self.current_path = norm_root
            self.started_at = time.monotonic()
            self.finished_at = 0.0
            self.is_cached = False
            self._nodes = {}
            self._largest_files = []
            self._dev_artifacts = []

        self._thread = threading.Thread(target=self._run_scan, args=(norm_root,), daemon=True)
        self._thread.start()
        return self.get_status()

    def cancel_scan(self) -> None:
        self._cancel_event.set()

    def get_status(self) -> dict:
        with self._lock:
            if self.is_cached:
                elapsed = self.finished_at
            else:
                elapsed = (
                    (self.finished_at - self.started_at)
                    if self.finished_at > 0
                    else (time.monotonic() - self.started_at if self.started_at > 0 else 0.0)
                )
            return {
                "status": self.status,
                "error": self.error_message,
                "root_path": self.root_path,
                "files_scanned": self.files_scanned,
                "dirs_scanned": self.dirs_scanned,
                "bytes_scanned": self.bytes_scanned,
                "bytes_human": format_bytes(self.bytes_scanned),
                "skipped_count": self.skipped_count,
                "current_path": self.current_path,
                "elapsed_sec": round(max(0.0, elapsed), 2),
                "dev_artifacts_count": len(self._dev_artifacts),
                "largest_files_count": len(self._largest_files),
                "cached": self.is_cached,
            }

    @staticmethod
    def _is_reparse_or_symlink(entry: os.DirEntry) -> bool:
        if entry.is_symlink():
            return True
        if os.name == "nt":
            try:
                st = entry.stat(follow_symlinks=False)
                attrs = getattr(st, "st_file_attributes", 0)
                return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
            except OSError:
                return True
        return False

    def _rebuild_derived_views(
        self,
        nodes: dict[str, DirNode],
        dev_paths: list[str] | None = None,
    ) -> tuple[list[dict], list[dict]]:
        """Recompute bottom-up sizes, latest_mtime, largest files, and dev artifacts."""
        sorted_paths = sorted(nodes.keys(), key=lambda p: p.count(os.sep), reverse=True)
        for p in sorted_paths:
            node = nodes[p]
            node.total_size = node.own_size
            node.total_file_count = node.own_file_count
            if node.files:
                max_f = max(f[2] for f in node.files)
                if max_f > node.latest_mtime:
                    node.latest_mtime = max_f

        for p in sorted_paths:
            node = nodes[p]
            if node.parent_path and node.parent_path in nodes:
                parent = nodes[node.parent_path]
                parent.total_size += node.total_size
                parent.total_file_count += node.total_file_count
                if node.latest_mtime > parent.latest_mtime:
                    parent.latest_mtime = node.latest_mtime

        # Collect top 300 largest files using a single pass without duplicating full file list
        import heapq

        top_heap: list[tuple[int, str, str, float, str]] = []
        for dpath, node in nodes.items():
            for fname, fsize, fmtime, fext in node.files:
                if len(top_heap) < 300:
                    heapq.heappush(top_heap, (fsize, dpath, fname, fmtime, fext))
                elif fsize > top_heap[0][0]:
                    heapq.heapreplace(top_heap, (fsize, dpath, fname, fmtime, fext))

        top_heap.sort(key=lambda x: x[0], reverse=True)
        largest_files: list[dict] = []
        for fsize, dpath, fname, fmtime, fext in top_heap:
            fpath = os.path.join(dpath, fname)
            dnode = nodes.get(dpath)
            mtime_str, age_days = _format_mtime(fmtime)
            risk = classify_path_risk(fpath, is_dir=False, age_days=age_days)
            largest_files.append({
                "path": fpath,
                "dir_path": dpath,
                "name": fname,
                "size_bytes": fsize,
                "size_human": format_bytes(fsize),
                "mtime": fmtime,
                "mtime_str": mtime_str,
                "age_days": age_days,
                "ext": fext,
                "is_protected": (dnode.is_protected if dnode else False) or is_os_protected_path(fpath),
                "is_personal": dnode.is_personal if dnode else is_personal_guarded_path(dpath),
                "risk_level": risk["risk_level"],
                "risk_reason": risk["risk_reason"],
            })

        target_dev_paths = dev_paths if dev_paths is not None else [p for p, n in nodes.items() if n.is_dev_bloat]
        dev_artifacts: list[dict] = []
        for dp in target_dev_paths:
            dnode = nodes.get(dp)
            if not dnode or dnode.total_size <= 0:
                continue
            mtime_str, age_days = _format_mtime(dnode.latest_mtime)
            risk = classify_path_risk(dnode.path, is_dir=True, age_days=age_days, is_dev_bloat=True)
            dev_artifacts.append({
                "path": dnode.path,
                "name": dnode.name,
                "parent_name": Path(dnode.parent_path).name if dnode.parent_path else "",
                "size_bytes": dnode.total_size,
                "size_human": format_bytes(dnode.total_size),
                "file_count": dnode.total_file_count,
                "mtime": dnode.latest_mtime,
                "mtime_str": mtime_str,
                "age_days": age_days,
                "is_protected": dnode.is_protected,
                "is_personal": dnode.is_personal,
                "risk_level": risk["risk_level"],
                "risk_reason": risk["risk_reason"],
            })
        dev_artifacts.sort(key=lambda x: x["size_bytes"], reverse=True)
        return largest_files, dev_artifacts

    def _run_scan(self, root_path: str) -> None:
        guard = ScanGuard()
        root_name = Path(root_path).name or root_path
        root_name_lower = root_name.lower()
        root_prot, root_pers = guard.check_dir(root_path, root_name_lower)
        try:
            root_mtime = os.stat(to_os_path(root_path), follow_symlinks=False).st_mtime
        except OSError:
            root_mtime = 0.0

        root_node = DirNode(
            path=root_path,
            name=root_name,
            parent_path=None,
            latest_mtime=root_mtime,
            is_protected=root_prot,
            is_personal=root_pers,
            is_dev_bloat=root_name_lower in DEV_BLOAT_NAMES,
        )
        nodes: dict[str, DirNode] = {root_path: root_node}
        dev_paths: list[str] = [root_path] if root_node.is_dev_bloat else []

        work_queue: deque[DirNode] = deque([root_node])
        queue_lock = threading.Lock()
        stats_lock = threading.Lock()
        active_workers = 0
        condition = threading.Condition(queue_lock)

        local_files_scanned = 0
        local_dirs_scanned = 0
        local_bytes_scanned = 0
        local_skipped = 0
        worker_outputs: list[tuple[dict[str, DirNode], list[str]]] = []

        is_nt = os.name == "nt"
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        s_islnk = stat.S_ISLNK
        s_isdir = stat.S_ISDIR
        s_isreg = stat.S_ISREG
        splitext = os.path.splitext
        sep = os.sep
        dev_bloat_names = DEV_BLOAT_NAMES
        cancel_event = self._cancel_event

        def worker() -> None:
            nonlocal active_workers, local_files_scanned, local_dirs_scanned, local_bytes_scanned, local_skipped
            w_nodes: dict[str, DirNode] = {}
            w_dev_paths: list[str] = []
            b_dirs = 0
            b_files = 0
            b_bytes = 0
            b_skipped = 0
            last_dir = ""

            while not cancel_event.is_set():
                with condition:
                    while not work_queue and active_workers > 0 and not cancel_event.is_set():
                        condition.wait(timeout=0.05)
                    if cancel_event.is_set():
                        break
                    if not work_queue and active_workers == 0:
                        break
                    parent_node = work_queue.popleft()
                    active_workers += 1

                current_dir = parent_node.path
                parent_protected = parent_node.is_protected
                parent_personal = parent_node.is_personal
                base_prefix = current_dir if current_dir.endswith(sep) else (current_dir + sep)

                child_dirs: list[str] = []
                child_nodes: list[DirNode] = []
                dir_files: list[tuple[str, int, float, str]] = []
                own_size = 0
                own_count = 0
                skipped_here = 0
                dir_mtime = parent_node.latest_mtime

                try:
                    os_dir = to_os_path(current_dir) if (is_nt and len(current_dir) >= 240) else current_dir
                    with os.scandir(os_dir) as it:
                        for entry in it:
                            if cancel_event.is_set():
                                break
                            try:
                                st = entry.stat(follow_symlinks=False)
                                mode = st.st_mode
                                if s_islnk(mode):
                                    continue
                                if is_nt and (getattr(st, "st_file_attributes", 0) & reparse_flag):
                                    continue

                                if s_isdir(mode):
                                    cname = entry.name
                                    cpath = base_prefix + cname
                                    cname_lower = cname.lower()
                                    is_dev = cname_lower in dev_bloat_names
                                    c_prot, c_pers = guard.check_dir(
                                        cpath,
                                        cname_lower,
                                        parent_protected,
                                        parent_personal,
                                    )
                                    cnode = DirNode(
                                        path=cpath,
                                        name=cname,
                                        parent_path=current_dir,
                                        latest_mtime=st.st_mtime,
                                        is_protected=c_prot,
                                        is_personal=c_pers,
                                        is_dev_bloat=is_dev,
                                    )
                                    w_nodes[cpath] = cnode
                                    child_dirs.append(cpath)
                                    child_nodes.append(cnode)
                                    if is_dev:
                                        w_dev_paths.append(cpath)
                                elif s_isreg(mode):
                                    fsize = st.st_size
                                    fmtime = st.st_mtime
                                    fname = entry.name
                                    ext = splitext(fname)[1].lower()
                                    dir_files.append((fname, fsize, fmtime, ext))
                                    own_size += fsize
                                    own_count += 1
                                    if fmtime > dir_mtime:
                                        dir_mtime = fmtime
                            except OSError:
                                skipped_here += 1
                except OSError:
                    skipped_here += 1

                parent_node.own_size = own_size
                parent_node.own_file_count = own_count
                parent_node.latest_mtime = dir_mtime
                parent_node.files = dir_files
                parent_node.child_dirs = child_dirs

                b_dirs += 1
                b_files += own_count
                b_bytes += own_size
                b_skipped += skipped_here
                last_dir = current_dir

                if b_dirs >= 32:
                    with stats_lock:
                        local_dirs_scanned += b_dirs
                        local_files_scanned += b_files
                        local_bytes_scanned += b_bytes
                        local_skipped += b_skipped
                        self.dirs_scanned = local_dirs_scanned
                        self.files_scanned = local_files_scanned
                        self.bytes_scanned = local_bytes_scanned
                        self.skipped_count = local_skipped
                        self.current_path = last_dir
                    b_dirs = 0
                    b_files = 0
                    b_bytes = 0
                    b_skipped = 0

                with condition:
                    if child_nodes:
                        work_queue.extend(child_nodes)
                    active_workers -= 1
                    condition.notify_all()

            with stats_lock:
                local_dirs_scanned += b_dirs
                local_files_scanned += b_files
                local_bytes_scanned += b_bytes
                local_skipped += b_skipped
                worker_outputs.append((w_nodes, w_dev_paths))

        try:
            worker_count = min(20, max(10, (os.cpu_count() or 4) * 2))
            workers = [threading.Thread(target=worker, daemon=True) for _ in range(worker_count)]
            for w in workers:
                w.start()
            for w in workers:
                w.join()

            for w_nodes, w_dev_paths in worker_outputs:
                nodes.update(w_nodes)
                if w_dev_paths:
                    dev_paths.extend(w_dev_paths)

            largest_files, dev_artifacts = self._rebuild_derived_views(nodes, dev_paths)
            finished_mono = time.monotonic()

            with self._lock:
                self._nodes = nodes
                self._largest_files = largest_files
                self._dev_artifacts = dev_artifacts
                self.dirs_scanned = local_dirs_scanned
                self.files_scanned = local_files_scanned
                self.bytes_scanned = local_bytes_scanned
                self.skipped_count = local_skipped
                self.finished_at = finished_mono
                cancelled = self._cancel_event.is_set()
                self.status = "cancelled" if cancelled else "done"
                if not cancelled:
                    cache_key = os.path.normcase(root_path)
                    if cache_key not in self._scan_cache and len(self._scan_cache) >= 6:
                        oldest_key = next(iter(self._scan_cache))
                        del self._scan_cache[oldest_key]
                    self._scan_cache[cache_key] = {
                        "root_path": root_path,
                        "nodes": nodes,
                        "largest_files": largest_files,
                        "dev_artifacts": dev_artifacts,
                        "files_scanned": local_files_scanned,
                        "dirs_scanned": local_dirs_scanned,
                        "bytes_scanned": local_bytes_scanned,
                        "skipped_count": local_skipped,
                        "elapsed_sec": max(0.0, finished_mono - self.started_at),
                    }
        except Exception as exc:
            with self._lock:
                self.error_message = str(exc)
                self.finished_at = time.monotonic()
                self.status = "error"

    def browse_folder(
        self,
        folder_path: str | None = None,
        *,
        sort_by: str = "size",
        query: str = "",
        offset: int = 0,
        limit: int = 250,
    ) -> dict:
        with self._lock:
            target = os.path.normpath(folder_path) if folder_path else self.root_path
            node = self._nodes.get(target)
            if not node:
                return {"error": f"Folder not indexed: {target}", "items": [], "total_items": 0}

            q = query.strip().lower()
            entries: list[dict] = []

            for cpath in node.child_dirs:
                cnode = self._nodes.get(cpath)
                if not cnode:
                    continue
                if q and q not in cnode.name.lower():
                    continue
                mtime_str, age_days = _format_mtime(cnode.latest_mtime)
                risk = classify_path_risk(
                    cnode.path,
                    is_dir=True,
                    age_days=age_days,
                    is_dev_bloat=cnode.is_dev_bloat,
                )
                entries.append({
                    "kind": "dir",
                    "path": cnode.path,
                    "name": cnode.name,
                    "size_bytes": cnode.total_size,
                    "size_human": format_bytes(cnode.total_size),
                    "file_count": cnode.total_file_count,
                    "mtime": cnode.latest_mtime,
                    "mtime_str": mtime_str,
                    "age_days": age_days,
                    "ext": "",
                    "is_protected": cnode.is_protected,
                    "is_personal": cnode.is_personal,
                    "is_dev_bloat": cnode.is_dev_bloat,
                    "risk_level": risk["risk_level"],
                    "risk_reason": risk["risk_reason"],
                })

            for fname, fsize, fmtime, ext in node.files:
                if q and q not in fname.lower():
                    continue
                fpath = os.path.join(node.path, fname)
                mtime_str, age_days = _format_mtime(fmtime)
                risk = classify_path_risk(fpath, is_dir=False, age_days=age_days)
                entries.append({
                    "kind": "file",
                    "path": fpath,
                    "name": fname,
                    "size_bytes": fsize,
                    "size_human": format_bytes(fsize),
                    "file_count": 1,
                    "mtime": fmtime,
                    "mtime_str": mtime_str,
                    "age_days": age_days,
                    "ext": ext,
                    "is_protected": node.is_protected or is_os_protected_path(fpath),
                    "is_personal": node.is_personal,
                    "is_dev_bloat": False,
                    "risk_level": risk["risk_level"],
                    "risk_reason": risk["risk_reason"],
                })

            if sort_by == "name":
                entries.sort(key=lambda e: (0 if e["kind"] == "dir" else 1, e["name"].lower()))
            elif sort_by == "mtime":
                entries.sort(key=lambda e: e["mtime"], reverse=True)
            elif sort_by == "oldest":
                entries.sort(key=lambda e: e["mtime"] or float("inf"))
            else:
                entries.sort(key=lambda e: e["size_bytes"], reverse=True)

            total_items = len(entries)
            page = entries[offset : offset + limit]

            breadcrumbs: list[dict] = []
            cur: str | None = node.path
            while cur and cur in self._nodes:
                n = self._nodes[cur]
                breadcrumbs.append({"name": n.name, "path": n.path})
                cur = n.parent_path
            breadcrumbs.reverse()

            return {
                "path": node.path,
                "parent_path": node.parent_path,
                "total_size": node.total_size,
                "total_size_human": format_bytes(node.total_size),
                "total_file_count": node.total_file_count,
                "breadcrumbs": breadcrumbs,
                "total_items": total_items,
                "offset": offset,
                "limit": limit,
                "items": page,
            }

    def search_all_files(
        self,
        *,
        query: str = "",
        min_size_mb: float = 0.0,
        min_age_days: int = 0,
        ext: str = "",
        sort_by: str = "size",
        offset: int = 0,
        limit: int = 200,
    ) -> dict:
        """Search and paginate across ALL scanned files without duplicating file storage."""
        with self._lock:
            q = query.strip().lower()
            ext_norm = ext.strip().lower()
            if ext_norm and not ext_norm.startswith("."):
                ext_norm = "." + ext_norm
            min_bytes = int(max(0.0, min_size_mb) * 1024 * 1024)
            cutoff_ts = (time.time() - (min_age_days * 86400)) if min_age_days > 0 else None

            matched: list[tuple[str, str, int, float, str]] = []
            for dpath, node in self._nodes.items():
                d_lower = dpath.lower() if q else ""
                for fname, fsize, fmtime, fext in node.files:
                    if fsize < min_bytes:
                        continue
                    if ext_norm and fext != ext_norm:
                        continue
                    if cutoff_ts is not None and (not fmtime or fmtime > cutoff_ts):
                        continue
                    if q and (q not in fname.lower() and q not in d_lower):
                        continue
                    matched.append((dpath, fname, fsize, fmtime, fext))

            if sort_by == "name":
                matched.sort(key=lambda f: f[1].lower())
            elif sort_by == "mtime":
                matched.sort(key=lambda f: f[3], reverse=True)
            elif sort_by == "oldest":
                matched.sort(key=lambda f: f[3] or float("inf"))
            else:
                matched.sort(key=lambda f: f[2], reverse=True)

            total_matches = len(matched)
            total_matched_bytes = sum(f[2] for f in matched)
            page = matched[offset : offset + limit]

            items = []
            for dpath, fname, fsize, fmtime, fext in page:
                fpath = os.path.join(dpath, fname)
                dnode = self._nodes.get(dpath)
                mtime_str, age_days = _format_mtime(fmtime)
                risk = classify_path_risk(fpath, is_dir=False, age_days=age_days)
                items.append({
                    "kind": "file",
                    "path": fpath,
                    "dir_path": dpath,
                    "name": fname,
                    "size_bytes": fsize,
                    "size_human": format_bytes(fsize),
                    "mtime": fmtime,
                    "mtime_str": mtime_str,
                    "age_days": age_days,
                    "ext": fext,
                    "is_protected": (dnode.is_protected if dnode else False) or is_os_protected_path(fpath),
                    "is_personal": dnode.is_personal if dnode else is_personal_guarded_path(dpath),
                    "risk_level": risk["risk_level"],
                    "risk_reason": risk["risk_reason"],
                })

            return {
                "total_matches": total_matches,
                "total_matched_bytes": total_matched_bytes,
                "total_matched_human": format_bytes(total_matched_bytes),
                "offset": offset,
                "limit": limit,
                "items": items,
            }

    def get_largest_files(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(self._largest_files[:limit])

    def get_dev_artifacts(self, limit: int = 200, min_age_days: int = 0) -> list[dict]:
        with self._lock:
            if min_age_days <= 0:
                return list(self._dev_artifacts[:limit])
            return [a for a in self._dev_artifacts if a.get("age_days", 0) >= min_age_days][:limit]

    def get_analytics(self, folder_path: str | None = None) -> dict:
        """Compute visual chart datasets: top folders, file type categories, age buckets, and risk totals."""
        with self._lock:
            root = os.path.normpath(folder_path) if folder_path else self.root_path
            root_node = self._nodes.get(root)
            if not root_node:
                return {"top_folders": [], "by_category": [], "by_age": [], "risk_summary": {}}

            total_root_bytes = max(1, root_node.total_size)
            top_folders = []
            for cpath in root_node.child_dirs:
                cnode = self._nodes.get(cpath)
                if not cnode or cnode.total_size <= 0:
                    continue
                _, age_days = _format_mtime(cnode.latest_mtime)
                risk = classify_path_risk(
                    cnode.path,
                    is_dir=True,
                    age_days=age_days,
                    is_dev_bloat=cnode.is_dev_bloat,
                )
                top_folders.append({
                    "name": cnode.name,
                    "path": cnode.path,
                    "size_bytes": cnode.total_size,
                    "size_human": format_bytes(cnode.total_size),
                    "file_count": cnode.total_file_count,
                    "percent": round((cnode.total_size / total_root_bytes) * 100, 1),
                    "risk_level": risk["risk_level"],
                })
            top_folders.sort(key=lambda x: x["size_bytes"], reverse=True)
            top_folders = top_folders[:12]

            # Category and age rollups across all indexed files
            ext_lookup: dict[str, tuple[str, str]] = {}
            for cat_name, exts, color in FILE_CATEGORIES:
                for e in exts:
                    ext_lookup[e] = (cat_name, color)

            cat_stats: dict[str, list] = {
                cat_name: [0, 0, color] for cat_name, _, color in FILE_CATEGORIES
            }
            cat_stats["Other Files"] = [0, 0, "#64748b"]

            age_buckets = [
                ("< 30 days", 0, 0, "#3b82f6"),
                ("30 to 90 days", 0, 0, "#06b6d4"),
                ("90 to 365 days", 0, 0, "#f59e0b"),
                ("> 1 year", 0, 0, "#ef4444"),
            ]
            age_counts = [[0, 0] for _ in age_buckets]

            risk_bytes = {"critical": 0, "caution": 0, "safe": 0}
            risk_files = {"critical": 0, "caution": 0, "safe": 0}

            now = time.time()
            total_all_bytes = 0
            for _dpath, node in self._nodes.items():
                for fname, fsize, fmtime, fext in node.files:
                    total_all_bytes += fsize
                    cat_name, _color = ext_lookup.get(fext, ("Other Files", "#64748b"))
                    cat_stats[cat_name][0] += fsize
                    cat_stats[cat_name][1] += 1

                    age_days = max(0, int((now - fmtime) // 86400)) if fmtime > 0 else 0
                    if age_days < 30:
                        idx = 0
                    elif age_days < 90:
                        idx = 1
                    elif age_days < 365:
                        idx = 2
                    else:
                        idx = 3
                    age_counts[idx][0] += fsize
                    age_counts[idx][1] += 1

                    if node.is_protected:
                        rk = "critical"
                    elif node.is_personal or fext in CAUTION_EXTENSIONS:
                        rk = "caution"
                    else:
                        rk = "safe"
                    risk_bytes[rk] += fsize
                    risk_files[rk] += 1

            denom = max(1, total_all_bytes)
            by_category = [
                {
                    "name": name,
                    "size_bytes": vals[0],
                    "size_human": format_bytes(vals[0]),
                    "file_count": vals[1],
                    "percent": round((vals[0] / denom) * 100, 1),
                    "color": vals[2],
                }
                for name, vals in cat_stats.items()
                if vals[0] > 0
            ]
            by_category.sort(key=lambda x: x["size_bytes"], reverse=True)

            by_age = [
                {
                    "name": age_buckets[i][0],
                    "size_bytes": age_counts[i][0],
                    "size_human": format_bytes(age_counts[i][0]),
                    "file_count": age_counts[i][1],
                    "percent": round((age_counts[i][0] / denom) * 100, 1),
                    "color": age_buckets[i][3],
                }
                for i in range(len(age_buckets))
            ]

            risk_summary = {
                k: {
                    "size_bytes": risk_bytes[k],
                    "size_human": format_bytes(risk_bytes[k]),
                    "file_count": risk_files[k],
                    "percent": round((risk_bytes[k] / denom) * 100, 1),
                }
                for k in ("critical", "caution", "safe")
            }

            return {
                "root_path": root,
                "total_bytes": total_all_bytes,
                "total_human": format_bytes(total_all_bytes),
                "top_folders": top_folders,
                "by_category": by_category,
                "by_age": by_age,
                "risk_summary": risk_summary,
            }

    def remove_deleted_paths(
        self,
        deleted_paths: list[str],
        cleared_contents_paths: list[str] | None = None,
    ) -> None:
        """Update the in-memory index after full deletions and contents-only cleanups."""
        deleted_set = {os.path.normcase(os.path.normpath(p)) for p in deleted_paths}
        cleared_set = {os.path.normcase(os.path.normpath(p)) for p in (cleared_contents_paths or [])}
        if not deleted_set and not cleared_set:
            return

        with self._lock:
            def is_removed(p: str) -> bool:
                pn = os.path.normcase(os.path.normpath(p))
                if pn in deleted_set:
                    return True
                for d in deleted_set:
                    if pn.startswith(d.rstrip("\\/") + os.sep):
                        return True
                for c in cleared_set:
                    if pn.startswith(c.rstrip("\\/") + os.sep):
                        return True
                return False

            for dpath, node in list(self._nodes.items()):
                if is_removed(dpath):
                    del self._nodes[dpath]
                    continue

                dpath_norm = os.path.normcase(os.path.normpath(dpath))
                if dpath_norm in cleared_set:
                    node.child_dirs = []
                    node.files = []
                    node.own_size = 0
                    node.own_file_count = 0
                    continue

                node.child_dirs = [c for c in node.child_dirs if not is_removed(c)]
                kept_files = []
                own_size = 0
                for tup in node.files:
                    fpath = os.path.join(dpath, tup[0])
                    if not is_removed(fpath):
                        kept_files.append(tup)
                        own_size += tup[1]
                node.files = kept_files
                node.own_size = own_size
                node.own_file_count = len(kept_files)

            largest_files, dev_artifacts = self._rebuild_derived_views(self._nodes)
            self._largest_files = largest_files
            self._dev_artifacts = dev_artifacts
            self.bytes_scanned = sum(n.own_size for n in self._nodes.values())
            self.files_scanned = sum(n.own_file_count for n in self._nodes.values())
            self.dirs_scanned = len(self._nodes)

            active_key = os.path.normcase(self.root_path) if self.root_path else ""
            if active_key and active_key in self._scan_cache:
                snap = self._scan_cache[active_key]
                snap["largest_files"] = largest_files
                snap["dev_artifacts"] = dev_artifacts
                snap["bytes_scanned"] = self.bytes_scanned
                snap["files_scanned"] = self.files_scanned
                snap["dirs_scanned"] = self.dirs_scanned

            for ckey in list(self._scan_cache.keys()):
                if ckey == active_key:
                    continue
                croot_prefix = ckey.rstrip("\\/") + os.sep
                if any(
                    d == ckey or d.startswith(croot_prefix) or ckey.startswith(d.rstrip("\\/") + os.sep)
                    for d in (deleted_set | cleared_set)
                ):
                    del self._scan_cache[ckey]
