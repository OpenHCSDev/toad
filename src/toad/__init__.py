from __future__ import annotations

import platform as _platform
from typing import TYPE_CHECKING, ClassVar, Literal, Mapping

if TYPE_CHECKING:
    from toad.setting_choices import DesktopService

NAME = "toad"
TITLE = "Toad"

type OS = Literal["linux", "macos", "windows", "*"]


class Platform:
    """The operating system Toad runs on; each member owns what differs there."""

    system: ClassVar[str]
    key: ClassVar[OS]
    application_name: ClassVar[str] = "Toad"
    members: ClassVar[dict[str, type[Platform]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        Platform.members[cls.system] = cls

    @classmethod
    def select[V](cls, matrix: Mapping[OS, V]) -> V | None:
        """The catalog's exact platform entry, or its declared wildcard."""
        return matrix.get(cls.key, matrix.get("*"))

    @classmethod
    def desktop(cls) -> DesktopService:
        from toad.setting_choices import DesktopService

        return DesktopService()


class LinuxPlatform(Platform):
    system = "Linux"
    key = "linux"

    @classmethod
    def desktop(cls) -> DesktopService:
        from toad.setting_choices import UncheckedDBusDesktop

        return UncheckedDBusDesktop()


class MacPlatform(Platform):
    system = "Darwin"
    key = "macos"
    application_name = "🐸 Toad"


class WindowsPlatform(Platform):
    system = "Windows"
    key = "windows"


platform: type[Platform] = Platform.members.get(_platform.system(), LinuxPlatform)


def get_version() -> str:
    """Get the current version of Toad.

    Returns:
        str: Version string, e.g "1.2.3"
    """
    from importlib.metadata import version

    return version("batrachian-toad")
