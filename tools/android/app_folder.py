"""What the APK's app folder holds besides the Python closure: each entry, who writes it, and
whether the APK ships it.

The app folder is reused between builds for buildozer's cache, so assemble.py owns its whole
set of entries: the closure's packages and modules, plus the entries declared here. Anything
else is a leftover of an older build (a package that left the closure, an earlier layout's
folders) and assemble removes it, since buildozer packs every file under the folder whose
extension it includes. The entries that are not shipped fill buildozer.spec's exclusions, so
the build's own files stay out of the APK.
"""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(frozen=True)
class Entry:
    pattern: str
    """The entry's name in the app folder, or a glob for a family of names."""
    written_by: str
    ships: bool
    folder: bool = False


ENTRIES = (
    Entry("main.py", "assemble.py: the APK's entry point (tools/android/main.py)", ships=True),
    Entry("profile.json", "assemble.py: the UI profile the phone holds first", ships=True),
    Entry("cacert.pem", "assemble.py: the CA bundle (SSL_CERT_FILE, toad.qt.android_app)", ships=True),
    Entry("wal", "assemble.py: the pywal theme the phone reads (PYWAL_CACHE_DIR)", ships=True, folder=True),
    Entry("__pycache__", "assemble.py: the bytecode of the closure's top-level modules", ships=True, folder=True),
    Entry("jar", "assemble.py: PySide6's jars, which buildozer.spec's android.add_jars names", ships=False, folder=True),
    Entry("buildozer.spec", "assemble.py, from buildozer.spec.in", ships=False),
    Entry("keepalive.aar", "assemble.py: the keep-alive service's manifest library", ships=False),
    Entry("closure.json", "check.sh: closure.py's package list", ships=False),
    Entry(".build.lock", "build.sh: one build at a time", ships=False),
    Entry("build.log", "build.sh: buildozer's log", ships=False),
    Entry(".buildozer", "buildozer: its build cache", ships=False, folder=True),
    Entry("bin", "buildozer: its default output folder", ships=False, folder=True),
    Entry("toadcomms-*.apk", "buildozer: the built APK (buildozer.spec's bin_dir is this folder)", ships=False),
)


def declared(name: str) -> bool:
    return any(fnmatch(name, entry.pattern) for entry in ENTRIES)


def stale(app: Path, closure_names: set[str]) -> list[Path]:
    """The app folder's entries that are neither the closure's nor declared here."""
    return sorted(path for path in app.iterdir() if path.name not in closure_names and not declared(path.name))


def excluded_folders() -> str:
    """buildozer.spec's source.exclude_dirs: the declared folders the APK does not ship."""
    return ", ".join(entry.pattern for entry in ENTRIES if entry.folder and not entry.ships)


def excluded_files() -> str:
    """buildozer.spec's source.exclude_patterns: the declared files the APK does not ship."""
    return ", ".join(entry.pattern for entry in ENTRIES if not entry.folder and not entry.ships)
