"""What the application does when its terminal session ends: print a notice, or exec the runtime
it upgraded to. Its own module, so a widget typing an App's return value imports this family and
not the application lifetime that opens screens. Changing bus ends nothing: the running app
switches its connection in place (ClientApplication.switch_bus)."""

from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_comms.execution.launch_runtime import LaunchRuntime

from toad.version import VersionMonitor


class ApplicationOutcome(ABC):
    @abstractmethod
    def finish(self) -> None: ...


@dataclass(frozen=True)
class Ended(ApplicationOutcome):
    version: VersionMonitor

    def finish(self) -> None:
        self.version.status.print_notice()


@dataclass(frozen=True)
class Succeeded(ApplicationOutcome):
    """Ends this session by exec'ing the runtime it switched to in place, opening whatever
    this launch already opened."""

    runtime: LaunchRuntime

    def arguments(self) -> tuple[str, ...]:
        """What the replacement launch is given, after its own program name."""
        return tuple(sys.argv[1:])

    def finish(self) -> None:
        self.runtime.require_available()
        executable = str(self.runtime.interpreter.with_name("toad"))
        os.execve(
            executable,
            [executable, *self.arguments()],
            self.runtime.environment(os.environ),
        )
