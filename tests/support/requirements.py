"""Things a test needs that not every machine has.

A test asks for the requirement's fixture. Where the thing is absent the test is
skipped with the requirement's reason; it never fails on a missing variable.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
from typing import ClassVar

import pytest


class Requirement:
    fixture: ClassVar[str]
    reason: ClassVar[str]

    @classmethod
    def find(cls) -> object | None:
        """The required thing, or None when this machine does not have it."""
        raise NotImplementedError

    @classmethod
    def require(cls) -> object:
        found = cls.find()
        if found is None:
            pytest.skip(cls.reason)
        return found


class NativePackage(Requirement):
    """The Pi coding-agent package Core starts as a native agent."""

    fixture = "native_package"
    variable = "TOAD_TEST_NATIVE_PACKAGE"
    reason = (f"needs a native package: set {variable} to a pi-coding-agent package "
              "that matches the installed Core")

    @classmethod
    def find(cls) -> Path | None:
        from agent_comms.native_package import NativePackageError, verify_native_package

        if (value := os.environ.get(cls.variable)) is None:
            return None
        try:
            verify_native_package(Path(value))
        except NativePackageError:
            return None
        return Path(value)


class TerminalEmulator(Requirement):
    """pyte, which reads what Toad writes to a real pseudo-terminal."""

    fixture = "terminal_emulator"
    reason = "needs pyte (a dev dependency) to read a real terminal"

    @classmethod
    def find(cls):
        return importlib.import_module("pyte") if importlib.util.find_spec("pyte") else None


class PrivateDisplay(Requirement):
    """A private X server and xclip, for clipboard transport."""

    fixture = "private_display_programs"
    reason = "needs Xvfb and xclip for a private X display"

    @classmethod
    def find(cls):
        programs = shutil.which("Xvfb"), shutil.which("xclip")
        return programs if all(programs) else None


class ImageLibrary(Requirement):
    """Pillow, for tests that read or make images."""

    fixture = "image_library"
    reason = "needs Pillow (a dev dependency)"

    @classmethod
    def find(cls):
        return importlib.import_module("PIL") if importlib.util.find_spec("PIL") else None
