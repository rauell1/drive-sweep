"""Write THIRD_PARTY_NOTICES.txt with the full license text of every component DriveSweep ships.

Run from the build virtual environment so the installed package metadata matches the bundle:

    .venv\\Scripts\\python.exe scripts\\collect_licenses.py

Use --path to read package metadata from another folder (for example a `pip install --target`
folder of the Windows wheels) when generating the notices on a non Windows machine.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Python packages bundled into DriveSweep.exe (runtime dependencies of requirements.txt on Windows).
RUNTIME_PACKAGES = (
    "pywebview",
    "bottle",
    "proxy_tools",
    "pythonnet",
    "clr_loader",
    "cffi",
    "pycparser",
    "typing_extensions",
    "Send2Trash",
    "psutil",
)

# proxy_tools is published only as a source package, so its metadata may be missing
# when notices are generated from a folder of Windows wheels.
_FALLBACK = {"proxy_tools": ("0.1.0", "MIT")}

PROXY_TOOLS_MIT = """MIT License

Copyright (c) Jonathan Tushman

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
(proxy_tools 0.1.0 declares the MIT License in its package metadata but ships no license file.)
"""

HEADER = """DriveSweep: Third Party Notices
================================

DriveSweep itself is licensed under the MIT License (see LICENSE).

The DriveSweep executables and installer also contain the third party components listed
below. Each remains under its own license, reproduced here as those licenses require.
DriveSweep is an independent project and is not affiliated with or endorsed by any of
these projects or by the companies whose applications it can clean.
"""

STATIC_SECTIONS = """
------------------------------------------------------------------------
Python runtime (CPython 3.12)
License: Python Software Foundation License Version 2 (PSF-2.0)
https://docs.python.org/3/license.html

The bundled Python runtime includes components under their own licenses, among them
OpenSSL (Apache-2.0), libffi (MIT), zlib (zlib License), bzip2 (bzip2-1.0.6 License),
XZ Utils / liblzma (0BSD), Expat (MIT) and mpdecimal (BSD-2-Clause). Their full texts
are listed in the "Licenses and Acknowledgements for Incorporated Software" section of
https://docs.python.org/3/license.html

------------------------------------------------------------------------
PyInstaller bootloader
License: GNU General Public License v2.0 or later, with the PyInstaller Bootloader Exception
https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt

The exception allows the bootloader to be distributed as part of applications under any
license, including DriveSweep's MIT License.

------------------------------------------------------------------------
Microsoft Edge WebView2 SDK (Microsoft.Web.WebView2.Core.dll, Microsoft.Web.WebView2.WinForms.dll,
WebView2Loader.dll; shipped inside pywebview)
Copyright (C) Microsoft Corporation. All rights reserved.
License: Microsoft WebView2 SDK license (BSD-3-Clause style)
https://www.nuget.org/packages/Microsoft.Web.WebView2/ (see the package license)

The Microsoft Edge WebView2 Runtime itself is part of Windows and is not distributed with
DriveSweep.
"""


def _license_texts(dist: md.Distribution) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for f in dist.files or []:
        name = f.name.lower()
        parent = str(f.parent).lower()
        if ".dist-info" in parent and (name.startswith(("license", "licence", "copying", "notice", "authors"))):
            try:
                texts.append((f.name, Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace").strip()))
            except OSError:
                continue
    return texts


def build_notices(search_path: str | None = None) -> str:
    paths = [search_path] if search_path else None
    parts = [HEADER, STATIC_SECTIONS]
    for pkg in RUNTIME_PACKAGES:
        dist = next(iter(md.distributions(name=pkg, path=paths) if paths else md.distributions(name=pkg)), None)
        version = dist.version if dist else _FALLBACK.get(pkg, ("unknown", ""))[0]
        meta = dist.metadata if dist else {}
        lic = ""
        if dist:
            lic = meta.get("License-Expression") or ""
            if not lic:
                raw = (meta.get("License") or "").strip().splitlines()
                lic = raw[0] if raw else ""
        parts.append("\n------------------------------------------------------------------------")
        lic = lic or _FALLBACK.get(pkg, ("", ""))[1]
        parts.append(f"{pkg} {version}" + (f"\nLicense: {lic}" if lic else ""))
        home = (meta.get("Home-page") if dist else "") or ""
        if home:
            parts.append(home)
        texts = _license_texts(dist) if dist else []
        if not texts and pkg.lower() == "proxy_tools":
            texts = [("LICENSE", PROXY_TOOLS_MIT.strip())]
        for fname, text in texts:
            parts.append(f"\n[{fname}]\n{text}")
        if not texts:
            parts.append("\n(License file not found in package metadata; see the project page.)")
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", help="Folder to read package metadata from (default: current environment)")
    ap.add_argument("--out", default=str(ROOT / "THIRD_PARTY_NOTICES.txt"))
    args = ap.parse_args()
    Path(args.out).write_text(build_notices(args.path), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
