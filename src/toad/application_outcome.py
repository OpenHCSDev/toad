"""What the application does when its terminal session ends: print a notice, or exec the runtime
it switched to. Its own module, so a widget typing an App's return value imports this family and
not the application lifetime that opens screens."""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_comms.launch_runtime import LaunchRuntime

from toad.version import VersionMonitor

from toad.bus_selection import BusChoice


class ApplicationOutcome(ABC):
    @abstractmethod
    def finish(self) -> None: ...


@dataclass(frozen=True)
class Ended(ApplicationOutcome):
    version: VersionMonitor

    def finish(self) -> None:
        self.version.status.print_notice()


@dataclass(frozen=True)
class ExecutedOutcome(ApplicationOutcome):
    """Ends this session by exec'ing a runtime's toad in place. Members differ only in the
    arguments the replacement is given, so the runtime and the exec live here."""

    runtime: LaunchRuntime

    @abstractmethod
    def arguments(self) -> tuple[str, ...]:
        """What the replacement launch is given, after its own program name."""

    def finish(self) -> None:
        self.runtime.require_available()
        executable = str(self.runtime.interpreter.with_name("toad"))
        os.execve(
            executable,
            [executable, *self.arguments()],
            self.runtime.environment(os.environ),
        )


@dataclass(frozen=True)
class Succeeded(ExecutedOutcome):
    """The runtime it switched to, opening whatever this launch already opened."""

    def arguments(self) -> tuple[str, ...]:
        return tuple(sys.argv[1:])


@dataclass(frozen=True)
class Reconnected(ExecutedOutcome):
    """The reader picked another bus: the same launch, selecting their choice."""

    choice: BusChoice

    def arguments(self) -> tuple[str, ...]:
        return self.choice.arguments(sys.argv[1:])
