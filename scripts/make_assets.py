"""Generate a crisp multi-resolution Windows .ico icon for DriveSweep using pure Python."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def _encode_png(width: int, height: int, rgba: bytearray) -> bytes:
    raw_rows = bytearray()
    stride = width * 4
    for y in range(height):
        raw_rows.append(0)  # filter type 0
        raw_rows.extend(rgba[y * stride : (y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_rows), 9)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _render_icon_png(size: int) -> bytes:
    """Render a rounded gradient square with a stylized drive + sweep bar."""
    buf = bytearray(size * size * 4)
    radius = size * 0.22
    pad = size * 0.04

    for y in range(size):
        for x in range(size):
            # Rounded rectangle signed distance
            cx = min(max(x + 0.5, pad + radius), size - pad - radius)
            cy = min(max(y + 0.5, pad + radius), size - pad - radius)
            dx = (x + 0.5) - cx
            dy = (y + 0.5) - cy
            dist = (dx * dx + dy * dy) ** 0.5 - radius
            if dist > 0.8:
                continue

            alpha = int(max(0.0, min(1.0, 0.8 - dist)) * 255)
            t = (x + y) / (2.0 * size)
            # Gradient from #3b82f6 (59,130,246) to #06b6d4 (6,182,212)
            r = int(59 * (1 - t) + 6 * t)
            g = int(130 * (1 - t) + 182 * t)
            b = int(246 * (1 - t) + 212 * t)

            nx = (x + 0.5) / size
            ny = (y + 0.5) / size

            # Inner drive-tray glyph in crisp white
            in_tray = (0.20 <= nx <= 0.80) and (0.58 <= ny <= 0.78)
            in_led = (0.64 <= nx <= 0.72) and (0.65 <= ny <= 0.71)
            # Sweep/clean diagonal bars above the tray
            in_bar1 = (0.24 <= nx <= 0.76) and (0.26 <= ny <= 0.34)
            in_bar2 = (0.30 <= nx <= 0.70) and (0.41 <= ny <= 0.49)

            if in_led:
                r, g, b = 34, 197, 94
            elif in_tray or in_bar1 or in_bar2:
                r, g, b = 248, 250, 252

            idx = (y * size + x) * 4
            buf[idx] = r
            buf[idx + 1] = g
            buf[idx + 2] = b
            buf[idx + 3] = alpha

    return _encode_png(size, size, buf)


def build_ico(output_path: Path) -> None:
    sizes = [16, 32, 48, 256]
    pngs = [_render_icon_png(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = bytearray()
    for sz, data in zip(sizes, pngs):
        dim = 0 if sz >= 256 else sz
        entries.extend(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(header + bytes(entries) + b"".join(pngs))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "drivesweep.ico"
    build_ico(out)
    print(f"Generated icon: {out}")
