"""Fail unless the APK's Qt libraries are the ones the toolchain built (tools/android/qt_libs.sh).

    python tools/android/apk_qt_libs.py APK TOOLCHAIN/qt

Packaging strips a library, so the files differ byte for byte: what is compared is the GNU
build id the linker wrote into each, which stripping keeps. An app folder whose cache still
holds the wheel's library, or a build that skipped the copy, cannot ship unnoticed.
"""
import re
import sys
import zipfile
from pathlib import Path

# An ELF note: name size 4, description size 20 (a SHA-1), type 3 (NT_GNU_BUILD_ID), "GNU".
BUILD_ID = re.compile(rb"\x04\x00\x00\x00\x14\x00\x00\x00\x03\x00\x00\x00GNU\x00(.{20})", re.DOTALL)


def build_id(library: bytes, name: str) -> str:
    found = BUILD_ID.search(library)
    if found is None:
        sys.exit(f"error: {name} carries no GNU build id")
    return found.group(1).hex()


apk, built = sys.argv[1], Path(sys.argv[2])
libraries = sorted(built.glob("*.so"))
if not libraries:
    sys.exit(f"error: {built} holds no built Qt library")
with zipfile.ZipFile(apk) as archive:
    for library in libraries:
        packaged = [name for name in archive.namelist() if re.fullmatch(rf"lib/[^/]+/{re.escape(library.name)}", name)]
        if not packaged:
            sys.exit(f"error: {apk} holds no {library.name}")
        wanted = build_id(library.read_bytes(), str(library))
        for name in packaged:
            if build_id(archive.read(name), name) != wanted:
                sys.exit(f"error: {name} is not the toolchain's build of it ({library})")
print(f"the APK's {', '.join(library.name for library in libraries)} is the toolchain's build ({(built / 'BUILT').read_text().splitlines()[0]})")
