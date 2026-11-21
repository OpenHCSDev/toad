# Copyright (C) 2023 The Qt Company Ltd.
# SPDX-License-Identifier: LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
"""pyside6-android-deploy's PySide6 recipe for the Qt modules Toad imports, reading its
wheel from the toolchain's wheels/ (beside the SDK, as tools/android/toolchain.sh lays it out)
instead of a path written in."""
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


class PySideRecipe(PythonRecipe):
    version = "6.12.0"
    depends = ["shiboken6"]
    call_hostpython_via_targetpython = False
    install_in_hostpython = False
    modules = tuple(
        f"Qt{module}"
        for module in (Path(__file__).parents[2] / "qt-modules.txt").read_text().strip().split(",")
    )

    @property
    def wheel_path(self) -> Path:
        return next((Path(self.ctx.sdk_dir).parent / "wheels").glob(f"pyside6-{self.version}-*android_aarch64.whl"))

    def build_arch(self, arch):
        """Unzip the wheel into the target's site-packages and put the Qt libraries, the
        bindings and the Android platform plugin where the app loads them at startup."""
        libs = Path(self.ctx.get_libs_dir(arch.arch))
        info("Copying libc++_shared.so from SDK to be loaded on startup")
        shutil.copyfile(f"{self.ctx.ndk.sysroot_lib_dir}/{arch.command_prefix}/libc++_shared.so", libs / "libc++_shared.so")

        info(f"Installing {self.name} into site-packages")
        with zipfile.ZipFile(self.wheel_path, "r") as zip_ref:
            safe_extractall(zip_ref, Path(self.ctx.get_python_install_dir(arch.arch)))

        lib_dir = Path(f"{self.ctx.get_python_install_dir(arch.arch)}/PySide6/Qt/lib")
        info("Copying Qt libraries to be loaded on startup")
        shutil.copytree(lib_dir, libs, dirs_exist_ok=True)
        for binding_library in lib_dir.parent.parent.glob("libpyside6*.so"):
            shutil.copyfile(binding_library, libs / binding_library.name)
        for module in self.modules:
            shutil.copyfile(lib_dir.parent.parent / f"{module}.abi3.so", libs / f"{module}.abi3.so")

        plugin = lib_dir.parent / "plugins" / "platforms" / f"libplugins_platforms_qtforandroid_{arch.arch}.so"
        if plugin.exists():
            shutil.copyfile(plugin, libs / plugin.name)


recipe = PySideRecipe()
