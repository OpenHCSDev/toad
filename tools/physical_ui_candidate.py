"""Candidate verification extends the installed terminal's resource lifetime."""
from functools import cache
from pathlib import Path

from agent_comms.installer.runtime_resolution import RuntimeResolution
from tools import physical_ui_admission
from tools.physical_ui import ObservedTerminalApp, OperationProgram
from tools.physical_ui_admission import AdmitOperation, RunTarget, StartAdmittedOperation


class TerminalApp(ObservedTerminalApp):
    start_operation = StartAdmittedOperation
    entry_operation = AdmitOperation
    entry_record = "build-admitted.json"
    final_record = "build-final.json"

    @classmethod
    @cache
    def operation_programs(cls):
        return (*super().operation_programs(),
                OperationProgram.capture(Path(physical_ui_admission.__file__)))

    @classmethod
    def prepare_target(cls, root, runtime) -> RunTarget:
        build = RuntimeResolution.at(runtime.prefix)
        build.interpreter.require_recorded()
        resources = super().prepare_target(root, runtime)
        return resources.extended(RunTarget, build=build)

    def check_entry(self, result):
        return result.admitted(self.target)
