"""p4a's hostpython3 recipe at the runtime's Python version, which p4a requires to equal
the target python3's (see tools/android/recipes/python3). Its patches stay p4a's."""
from __future__ import annotations

import os
from os.path import dirname, join

import pythonforandroid.recipes.hostpython3 as core
from pythonforandroid.recipes.hostpython3 import HostPython3Recipe


class RuntimeHostPython3Recipe(HostPython3Recipe):
    version = os.environ["TOAD_ANDROID_PYTHON"]

    def apply_patch(self, filename, arch, build_dir=None):
        super().apply_patch(join(dirname(core.__file__), filename), arch, build_dir)


recipe = RuntimeHostPython3Recipe()
