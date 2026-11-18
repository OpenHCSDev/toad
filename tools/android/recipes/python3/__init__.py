"""p4a's python3 recipe at the runtime's own Python version.

The APK's interpreter is the version of the agent-comms runtime it is built from
(build.sh exports it as TOAD_ANDROID_PYTHON). That runtime compiles the bytecode the APK
ships and runs every check of the bundle, so one version answers for all three. p4a's pin
(3.14.2 at p4a 58d21141) predates CPython 3.14.5, which reverted the incremental GC: on the
phone, its mark_stacks read a NULL type from a worker thread's stack and killed the process
(SIGSEGV in _PyObject_IS_GC under gc_collect_increment, 2026-11-18).

p4a's own patches stay p4a's: they're read from its recipe folder, not copied here.
"""
from __future__ import annotations

import os
from os.path import dirname, join
from pathlib import Path

import pythonforandroid.recipes.python3 as core
from pythonforandroid.logger import info
from pythonforandroid.recipes.python3 import Python3Recipe

# p4a's patches written against 3.14.2 whose change CPython made itself later, each with
# the source line that carries it. One is skipped only where that line is present, so a
# version without it fails the build instead of shipping without the fix.
UPSTREAM = {
    "patches/3.14_armv7l_fix.patch": ("Lib/sysconfig/__init__.py", '"arm": "armeabi_v7a",'),
    "patches/3.14_fix_remote_debug.patch": ("Python/remote_debug.h", "defined(__linux__) && HAVE_PROCESS_VM_READV"),
}


class PatchNotUpstream(RuntimeError):
    """A p4a patch declared upstream, against a source that doesn't carry its change."""


class RuntimePython3Recipe(Python3Recipe):
    version = os.environ["TOAD_ANDROID_PYTHON"]

    def apply_patch(self, filename, arch, build_dir=None):
        if filename in UPSTREAM:
            path, carried = UPSTREAM[filename]
            source = Path(build_dir if build_dir else self.get_build_dir(arch)) / path
            if carried not in source.read_text():
                raise PatchNotUpstream(f"Python {self.version}'s {path} lacks {carried!r}, which {filename} adds")
            info(f"Skipping patch {filename}: Python {self.version} carries it ({path})")
            return
        super().apply_patch(join(dirname(core.__file__), filename), arch, build_dir)


recipe = RuntimePython3Recipe()
