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
    runtime: LaunchRuntime

    def finish(self) -> None:
        self.runtime.require_available()
        executable = str(self.runtime.interpreter.with_name("toad"))
        os.execve(
            executable,
            [executable, *sys.argv[1:]],
            self.runtime.environment(os.environ),
        )
