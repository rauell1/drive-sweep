"""Optional Windows Administrator NTFS Master File Table ($MFT) fast scanner.

Safely reads $MFT directly on local NTFS fixed drives when running elevated.
Falls back transparently to multithreaded os.scandir whenever non-admin,
non-NTFS, scanning a subfolder, or encountering unsupported $MFT structures.
"""

from __future__ import annotations

import ctypes
import os
import struct
import threading
from dataclasses import dataclass
from typing import Callable

_FILE_SHARE_ALL = 0x00000007
_OPEN_EXISTING = 3
_GENERIC_READ = 0x80000000
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_FILETIME_EPOCH_DIFF = 116444736000000000
_REPARSE_ATTR = 0x0400
_ROOT_MFT_INDEX = 5


@dataclass(frozen=True)
class NtfsVolumeGeometry:
    bytes_per_sector: int
    sectors_per_cluster: int
    cluster_size: int
    mft_lcn: int
    mft_record_size: int


def parse_ntfs_boot_sector(boot: bytes) -> NtfsVolumeGeometry | None:
    """Validate and decode an NTFS volume boot sector."""
    if len(boot) < 512 or boot[3:11] != b"NTFS    ":
        return None
    bps = struct.unpack_from("<H", boot, 0x0B)[0]
    spc = boot[0x0D]
    if bps not in (512, 1024, 2048, 4096) or spc == 0 or (spc & (spc - 1)) != 0:
        return None
    cluster_size = bps * spc
    mft_lcn = struct.unpack_from("<Q", boot, 0x30)[0]
    raw_rec = struct.unpack_from("<b", boot, 0x40)[0]
    if raw_rec < 0:
        rec_size = 1 << (-raw_rec)
    elif raw_rec > 0:
        rec_size = raw_rec * cluster_size
    else:
        return None
    if rec_size < 512 or rec_size > 4096 or (rec_size & (rec_size - 1)) != 0:
        return None
    return NtfsVolumeGeometry(
        bytes_per_sector=bps,
        sectors_per_cluster=spc,
        cluster_size=cluster_size,
        mft_lcn=mft_lcn,
        mft_record_size=rec_size,
    )


def decode_data_runs(run_bytes: bytes) -> list[tuple[int, int]] | None:
    """Decode NTFS non-resident data runs into [(start_lcn, cluster_count), ...]."""
    runs: list[tuple[int, int]] = []
    idx = 0
    current_lcn = 0
    total = len(run_bytes)
    while idx < total:
        header = run_bytes[idx]
        idx += 1
        if header == 0:
            break
        len_size = header & 0x0F
        off_size = (header >> 4) & 0x0F
        if len_size == 0 or idx + len_size + off_size > total:
            return None
        cluster_len = int.from_bytes(run_bytes[idx : idx + len_size], "little", signed=False)
        idx += len_size
        if cluster_len <= 0:
            return None
        if off_size == 0:
            # Sparse unallocated cluster run inside $MFT
            runs.append((-1, cluster_len))
            continue
        lcn_delta = int.from_bytes(run_bytes[idx : idx + off_size], "little", signed=True)
        idx += off_size
        current_lcn += lcn_delta
        if current_lcn < 0:
            return None
        runs.append((current_lcn, cluster_len))
    return runs


def apply_usa_fixup(record: bytearray, sector_size: int) -> bool:
    """Apply NTFS Update Sequence Array fixups in-place."""
    if len(record) < 48 or record[:4] != b"FILE":
        return False
    usa_off = struct.unpack_from("<H", record, 4)[0]
    usa_cnt = struct.unpack_from("<H", record, 6)[0]
    if usa_cnt < 2 or usa_off + usa_cnt * 2 > len(record):
        return False
    expected_sectors = len(record) // sector_size
    if usa_cnt - 1 != expected_sectors:
        return False
    usn = record[usa_off : usa_off + 2]
    for s_idx in range(1, usa_cnt):
        end_pos = s_idx * sector_size - 2
        if end_pos + 2 > len(record):
            return False
        if record[end_pos : end_pos + 2] != usn:
            return False
        fix_pos = usa_off + s_idx * 2
        record[end_pos : end_pos + 2] = record[fix_pos : fix_pos + 2]
    return True


def _filetime_to_unix(ft: int) -> float:
    if ft <= _FILETIME_EPOCH_DIFF:
        return 0.0
    return (ft - _FILETIME_EPOCH_DIFF) / 10_000_000.0


def _parse_mft_runs_from_record0(rec0: bytearray, sector_size: int) -> tuple[int, list[tuple[int, int]]] | None:
    """Extract total $MFT size and cluster runs from record 0."""
    if not apply_usa_fixup(rec0, sector_size):
        return None
    attr_off = struct.unpack_from("<H", rec0, 0x14)[0]
    rec_len = len(rec0)
    while attr_off + 8 <= rec_len:
        a_type = struct.unpack_from("<I", rec0, attr_off)[0]
        if a_type == 0xFFFFFFFF:
            break
        a_len = struct.unpack_from("<I", rec0, attr_off + 4)[0]
        if a_len < 16 or attr_off + a_len > rec_len:
            return None
        if a_type == 0x20:
            # $ATTRIBUTE_LIST spans multiple MFT records; let standard scanner handle safely
            return None
        if a_type == 0x80 and rec0[attr_off + 9] == 0:
            non_res = rec0[attr_off + 8]
            if non_res != 1 or attr_off + 56 > rec_len:
                return None
            run_off = struct.unpack_from("<H", rec0, attr_off + 32)[0]
            real_size = struct.unpack_from("<Q", rec0, attr_off + 48)[0]
            runs = decode_data_runs(bytes(rec0[attr_off + run_off : attr_off + a_len]))
            if not runs:
                return None
            return real_size, runs
        attr_off += a_len
    return None


@dataclass
class _MftRecordInfo:
    is_dir: bool
    parent_idx: int
    name: str
    size: int
    mtime: float


def _parse_single_record(rec: bytearray, sector_size: int) -> tuple[int, _MftRecordInfo] | None:
    """Parse one MFT record header and attributes into compact metadata."""
    if not apply_usa_fixup(rec, sector_size):
        return None
    flags = struct.unpack_from("<H", rec, 0x16)[0]
    if not (flags & 0x0001):
        return None
    # Skip extension MFT records; base record carries primary metadata and index
    if len(rec) >= 0x28 and struct.unpack_from("<Q", rec, 0x20)[0] != 0:
        return None

    mft_idx = struct.unpack_from("<I", rec, 0x2C)[0]
    is_dir = bool(flags & 0x0002)
    attr_off = struct.unpack_from("<H", rec, 0x14)[0]
    rec_len = len(rec)

    mtime = 0.0
    reparse = False
    best_name = ""
    best_ns = 99
    best_parent = -1
    fn_size = 0
    data_size: int | None = None

    while attr_off + 8 <= rec_len:
        a_type = struct.unpack_from("<I", rec, attr_off)[0]
        if a_type == 0xFFFFFFFF:
            break
        a_len = struct.unpack_from("<I", rec, attr_off + 4)[0]
        if a_len < 16 or attr_off + a_len > rec_len:
            break
        non_res = rec[attr_off + 8]
        name_len = rec[attr_off + 9]

        if a_type == 0x10 and non_res == 0 and attr_off + 24 <= rec_len:
            val_len = struct.unpack_from("<I", rec, attr_off + 16)[0]
            val_off = struct.unpack_from("<H", rec, attr_off + 20)[0]
            if attr_off + val_off + min(36, val_len) <= attr_off + a_len and val_len >= 36:
                ft = struct.unpack_from("<Q", rec, attr_off + val_off + 8)[0]
                mtime = _filetime_to_unix(ft)
                fattrs = struct.unpack_from("<I", rec, attr_off + val_off + 32)[0]
                if fattrs & _REPARSE_ATTR:
                    reparse = True
        elif a_type == 0x30 and non_res == 0 and attr_off + 24 <= rec_len:
            val_len = struct.unpack_from("<I", rec, attr_off + 16)[0]
            val_off = struct.unpack_from("<H", rec, attr_off + 20)[0]
            base = attr_off + val_off
            if val_len >= 66 and base + 66 <= attr_off + a_len:
                nchars = rec[base + 64]
                ns = rec[base + 65]
                if base + 66 + nchars * 2 <= attr_off + a_len:
                    cand_name = bytes(rec[base + 66 : base + 66 + nchars * 2]).decode("utf-16-le", errors="ignore")
                    parent_ref = struct.unpack_from("<Q", rec, base)[0] & 0x0000FFFFFFFFFFFF
                    fn_alloc_or_real = struct.unpack_from("<Q", rec, base + 48)[0]
                    # Prefer Win32 (1) or Win32+DOS (3) over pure DOS 8.3 (2)
                    rank = 0 if ns in (1, 3) else (1 if ns == 0 else 2)
                    if rank < best_ns:
                        best_ns = rank
                        best_name = cand_name
                        best_parent = parent_ref
                        fn_size = fn_alloc_or_real
        elif a_type == 0x80 and name_len == 0 and data_size is None:
            if non_res == 0 and attr_off + 20 <= rec_len:
                data_size = struct.unpack_from("<I", rec, attr_off + 16)[0]
            elif non_res == 1 and attr_off + 56 <= rec_len:
                data_size = struct.unpack_from("<Q", rec, attr_off + 48)[0]

        attr_off += a_len

    if reparse or not best_name or best_parent < 0:
        return None
    final_size = data_size if data_size is not None else fn_size
    return mft_idx, _MftRecordInfo(
        is_dir=is_dir,
        parent_idx=best_parent,
        name=best_name,
        size=0 if is_dir else max(0, int(final_size)),
        mtime=mtime,
    )


def scan_ntfs_mft_with_reader(
    root_path: str,
    read_at: Callable[[int, int], bytes],
    *,
    guard,
    dev_bloat_names: set[str],
    dir_node_cls,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[int, int, int, str], None] | None = None,
) -> tuple[dict, list[str], int, int, int] | None:
    """Scan an NTFS drive root using a random-access byte reader.

    Returns (nodes, dev_paths, files_scanned, dirs_scanned, bytes_scanned) or None
    if the volume does not use a supported standard MFT layout.
    """
    boot_buf = read_at(0, 4096)
    geom = parse_ntfs_boot_sector(boot_buf[:512])
    if geom is None:
        return None

    mft_byte_offset = geom.mft_lcn * geom.cluster_size
    rec0 = bytearray(read_at(mft_byte_offset, geom.mft_record_size))
    runs_info = _parse_mft_runs_from_record0(rec0, geom.bytes_per_sector)
    if runs_info is None:
        return None

    total_mft_bytes, runs = runs_info
    rec_size = geom.mft_record_size
    chunk_bytes = 256 * 1024

    records: dict[int, _MftRecordInfo] = {}
    fallback_idx = 0
    processed_bytes = 0

    for start_lcn, cluster_cnt in runs:
        if cancel_event is not None and cancel_event.is_set():
            return None
        remaining = min(cluster_cnt * geom.cluster_size, max(0, total_mft_bytes - processed_bytes))
        if start_lcn < 0:
            fallback_idx += remaining // rec_size
            processed_bytes += remaining
            continue
        run_byte_start = start_lcn * geom.cluster_size
        pos = 0
        while pos < remaining:
            if cancel_event is not None and cancel_event.is_set():
                return None
            to_read = min(chunk_bytes, remaining - pos)
            buf = read_at(run_byte_start + pos, to_read)
            if not buf:
                break
            usable = (len(buf) // rec_size) * rec_size
            for off in range(0, usable, rec_size):
                parsed = _parse_single_record(bytearray(buf[off : off + rec_size]), geom.bytes_per_sector)
                if parsed is not None:
                    r_idx, info = parsed
                    if r_idx == 0 and fallback_idx != 0:
                        r_idx = fallback_idx
                    records[r_idx] = info
                fallback_idx += 1
            pos += len(buf)
            processed_bytes += len(buf)
            if progress_cb:
                progress_cb(len(records), 0, 0, f"Reading NTFS table ({len(records):,} entries)...")

    if _ROOT_MFT_INDEX not in records:
        return None

    norm_root = os.path.normpath(root_path)
    root_name = norm_root
    root_prot, root_pers = guard.check_dir(norm_root, norm_root.lower())
    root_node = dir_node_cls(
        path=norm_root,
        name=root_name,
        parent_path=None,
        latest_mtime=records[_ROOT_MFT_INDEX].mtime,
        is_protected=root_prot,
        is_personal=root_pers,
        is_dev_bloat=False,
    )

    dir_paths: dict[int, str] = {_ROOT_MFT_INDEX: norm_root}
    nodes: dict[str, object] = {norm_root: root_node}
    dev_paths: list[str] = []

    def resolve_dir_path(idx: int) -> str | None:
        if idx in dir_paths:
            return dir_paths[idx]
        chain: list[int] = []
        seen: set[int] = set()
        cur = idx
        while cur not in dir_paths:
            if cur in seen or cur not in records or not records[cur].is_dir:
                return None
            if cur < 16 and cur != _ROOT_MFT_INDEX:
                return None
            seen.add(cur)
            chain.append(cur)
            cur = records[cur].parent_idx
        parent_path = dir_paths[cur]
        for d_idx in reversed(chain):
            info = records[d_idx]
            cpath = os.path.join(parent_path, info.name)
            pnode = nodes.get(parent_path)
            p_prot = getattr(pnode, "is_protected", False) if pnode else False
            p_pers = getattr(pnode, "is_personal", False) if pnode else False
            cname_low = info.name.lower()
            is_dev = cname_low in dev_bloat_names
            c_prot, c_pers = guard.check_dir(cpath, cname_low, p_prot, p_pers)
            node = dir_node_cls(
                path=cpath,
                name=info.name,
                parent_path=parent_path,
                latest_mtime=info.mtime,
                is_protected=c_prot,
                is_personal=c_pers,
                is_dev_bloat=is_dev,
            )
            nodes[cpath] = node
            if pnode is not None:
                pnode.child_dirs.append(cpath)
            if is_dev:
                dev_paths.append(cpath)
            dir_paths[d_idx] = cpath
            parent_path = cpath
        return parent_path

    # Pass 1: build all directories reachable from root
    for r_idx, info in records.items():
        if info.is_dir and r_idx >= 16:
            resolve_dir_path(r_idx)

    # Pass 2: attach all regular files to their resolved parent directory
    files_scanned = 0
    bytes_scanned = 0
    splitext = os.path.splitext
    for r_idx, info in records.items():
        if info.is_dir or r_idx < 16:
            continue
        if info.name.startswith("$"):
            continue
        pdir = resolve_dir_path(info.parent_idx)
        if not pdir:
            continue
        pnode = nodes.get(pdir)
        if pnode is None:
            continue
        ext = splitext(info.name)[1].lower()
        pnode.files.append((info.name, info.size, info.mtime, ext))
        pnode.own_size += info.size
        pnode.own_file_count += 1
        if info.mtime > pnode.latest_mtime:
            pnode.latest_mtime = info.mtime
        files_scanned += 1
        bytes_scanned += info.size

    return nodes, dev_paths, files_scanned, len(nodes), bytes_scanned


def _is_ntfs_drive_root(root_path: str) -> str | None:
    """Return volume device path like '\\\\.\\C:' if root_path is a local NTFS drive root."""
    if os.name != "nt":
        return None
    norm = os.path.normpath(root_path)
    if len(norm) < 2 or norm[1] != ":" or len(norm.rstrip("\\/")) != 2:
        return None
    drive_root = norm[:2].upper() + "\\"
    try:
        fs_buf = ctypes.create_unicode_buffer(64)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            drive_root,
            None,
            0,
            None,
            None,
            None,
            fs_buf,
            len(fs_buf),
        )
        if ok and fs_buf.value.upper() == "NTFS":
            return f"\\\\.\\{drive_root[:2]}"
    except Exception:
        pass
    return None


def try_ntfs_mft_scan(
    root_path: str,
    *,
    guard,
    dev_bloat_names: set[str],
    dir_node_cls,
    cancel_event: threading.Event | None = None,
    progress_cb: Callable[[int, int, int, str], None] | None = None,
):
    """Attempt fast raw NTFS $MFT scan when elevated on Windows; returns None on fallback."""
    vol_path = _is_ntfs_drive_root(root_path)
    if not vol_path:
        return None

    k32 = ctypes.windll.kernel32
    handle = k32.CreateFileW(
        vol_path,
        _GENERIC_READ,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_SEQUENTIAL_SCAN,
        None,
    )
    if not handle or handle == _INVALID_HANDLE_VALUE:
        return None

    try:
        def read_at(offset: int, length: int) -> bytes:
            if length <= 0 or offset < 0:
                return b""
            # Align raw volume reads to 4096-byte boundaries for both 512e and 4Kn drives
            align = 4096
            aligned_off = (offset // align) * align
            end_off = offset + length
            aligned_end = ((end_off + align - 1) // align) * align
            aligned_len = aligned_end - aligned_off

            new_pos = ctypes.c_longlong(0)
            if not k32.SetFilePointerEx(handle, ctypes.c_longlong(aligned_off), ctypes.byref(new_pos), 0):
                return b""
            buf = ctypes.create_string_buffer(aligned_len)
            bytes_read = ctypes.c_ulong(0)
            if not k32.ReadFile(handle, buf, aligned_len, ctypes.byref(bytes_read), None):
                return b""
            lead = offset - aligned_off
            raw = buf.raw[: bytes_read.value]
            return raw[lead : lead + length]

        return scan_ntfs_mft_with_reader(
            root_path,
            read_at,
            guard=guard,
            dev_bloat_names=dev_bloat_names,
            dir_node_cls=dir_node_cls,
            cancel_event=cancel_event,
            progress_cb=progress_cb,
        )
    finally:
        k32.CloseHandle(handle)
