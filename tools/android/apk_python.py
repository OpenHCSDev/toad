"""Fail unless the APK's interpreter is the Python version it was built for.

    python tools/android/apk_python.py APK VERSION

The version is read from the APK's own libpython (the string Py_GetVersion answers), so a
recipe that fell back to p4a's pinned CPython can't ship unnoticed.
"""
import re
import sys
import zipfile

apk, wanted = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(apk) as archive:
    names = [name for name in archive.namelist() if re.fullmatch(r"lib/[^/]+/libpython3\.\d+\.so", name)]
    if not names:
        sys.exit(f"error: {apk} holds no libpython")
    for name in names:
        found = set(re.findall(rb"\x00(3\.\d+\.\d+)\x00", archive.read(name)))  # PY_VERSION, a bare C string
        if found != {wanted.encode()}:
            sys.exit(f"error: {name} is Python {sorted(v.decode() for v in found)}, not {wanted}")
print(f"the APK's interpreter is Python {wanted}")
