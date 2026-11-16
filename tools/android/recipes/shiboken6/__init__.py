# Copyright (C) 2023 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
"""pyside6-android-deploy's shiboken6 recipe, reading its wheel from the toolchain's wheels/
(beside the SDK, as tools/android/toolchain.sh lays it out) instead of a path written in."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from pythonforandroid.logger import info
from pythonforandroid.recipe import PythonRecipe


def safe_extractall(zip_ref: zipfile.ZipFile, target_path: Path) -> None:
    """Extract every member of zip_ref into target_path, refusing any that resolves outside it."""
    resolved_target = target_path.resolve()
    for member in zip_ref.infolist():
        member_path = (target_path / member.filename).resolve()
        if not member_path.is_relative_to(resolved_target):
            raise RuntimeError(f"Refusing to extract '{member.filename}': path resolves outside the extraction directory")
        zip_ref.extract(member, target_path)


class ShibokenRecipe(PythonRecipe):
    version = "6.12.0"
    call_hostpython_via_targetpython = False
    install_in_hostpython = False

    @property
    def wheel_path(self) -> Path:
        return next((Path(self.ctx.sdk_dir).parent / "wheels").glob(f"shiboken6-{self.version}-*android_aarch64.whl"))

    def build_arch(self, arch):
        """Unzip the wheel into the target's site-packages."""
        info(f"Installing {self.name} into site-packages")
        with zipfile.ZipFile(self.wheel_path, "r") as zip_ref:
            safe_extractall(zip_ref, Path(self.ctx.get_python_install_dir(arch.arch)))
        lib_dir = Path(f"{self.ctx.get_python_install_dir(arch.arch)}/shiboken6")
        shutil.copyfile(lib_dir / "libshiboken6.abi3.so", Path(self.ctx.get_libs_dir(arch.arch)) / "libshiboken6.abi3.so")


recipe = ShibokenRecipe()
