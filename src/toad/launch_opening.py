"""What a launch asks to open once its tabs are back: `--open NAME` names a thread, or a
`#channel`, and the start opens it as that conversation's sidebar row does. Declared once for
every frontend: the terminal launch and Qt's desktop launch read it from their arguments
here (`LaunchOpening.startup`), and the shared start opens it (`ApplicationLifetime.start`)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from toad.core.session_requests import TargetOpen
from toad.navigation_target import NavigationTarget

if TYPE_CHECKING:
    from toad.client.application import ClientApplication


class LaunchOpening(ABC):
    """The conversation a launch names, or none."""

    argument: ClassVar[str] = "--open"

    @classmethod
    def startup(cls, arguments: list[str]) -> LaunchOpening:
        """Read this process's own `--open NAME`, removing it from ``arguments`` as the
        connection's own options are removed, so each frontend's parser never sees it. A `--`
        ends this process's options: after it the arguments belong to a command it runs."""
        own = arguments[:arguments.index("--")] if "--" in arguments else arguments
        if cls.argument not in own:
            return NoLaunchOpening()
        index = own.index(cls.argument)
        if index + 1 == len(own):
            raise ValueError(f"{cls.argument} requires a thread or #channel name")
        name = arguments[index + 1]
        del arguments[index : index + 2]
        return OpensTarget(name)

    @abstractmethod
    async def open(self, app: ClientApplication) -> None:
        """Open what the launch named, once the saved tabs are back."""


@dataclass(frozen=True)
class NoLaunchOpening(LaunchOpening):
    """The launch named nothing: the restored tabs are the start."""

    async def open(self, app: ClientApplication) -> None:
        pass


@dataclass(frozen=True)
class OpensTarget(LaunchOpening):
    """A thread or `#channel` the launch named: opened from home, as its sidebar row and a
    link naming it are (`TargetOpen`)."""

    name: str

    async def open(self, app: ClientApplication) -> None:

        await TargetOpen(NavigationTarget.named(self.name)).apply(app.session_navigation)
