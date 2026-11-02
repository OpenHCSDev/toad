"""Strict candidate-build operations, separate from installed resource observation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

# Only explicit execution admits this frozen tool dependency, never installed packages.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))

from agent_comms.installer.probes.resolution import RuntimeResolutionProbe
from agent_comms.installer.runtime_resolution import RuntimeResolution
from tools.physical_ui_remote import (
    ObserveOperation, ObservedResult, PhysicalOperation, PhysicalResult,
    RunObservation, RunResources, StartOperation,
)


@dataclass(frozen=True)
class RunTarget(RunResources):
    build: RuntimeResolution

    def __post_init__(self):
        super().__post_init__()
        self.build.interpreter.require_recorded()

    def require_build(self, actual: RuntimeResolution) -> None:
        self.build.require_runtime(actual)


@dataclass(frozen=True)
class AdmittedResult(ObservedResult):
    """Build evidence for one frontend birth, not a fresh hash on every UI read."""

    build: RuntimeResolution

    def admitted(self, target: RunResources) -> AdmittedResult:
        target.require_build(self.build)
        target.require_resources(self.value)
        return self

    def require_build(self) -> RuntimeResolution:
        return self.build

    def finish(self, target: RunResources, current: PhysicalResult) -> None:
        super().finish(target, current)
        actual = current.require_build()
        target.require_build(actual)
        if actual != self.build:
            raise ValueError("The verified runtime build changed during the physical run")


@dataclass(frozen=True)
class StartAdmittedOperation(StartOperation):
    target: RunTarget


@dataclass(frozen=True)
class AdmitOperation(ObserveOperation):
    """Full disk-artifact verification at entry and successful retirement only."""

    target: RunTarget

    def observed_result(self, observed: RunObservation, directory: Path) -> PhysicalResult:
        build = RuntimeResolutionProbe(
            self.target.build.core_commit, self.target.build.wheel_inputs()
        ).run()
        return AdmittedResult(observed, build).admitted(self.target)


if __name__ == "__main__":
    PhysicalOperation.execute_file(Path(__file__))
