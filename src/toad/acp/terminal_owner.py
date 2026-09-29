"""Nominal terminal capability shared by operational Agent controllers."""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .terminal_controller import TerminalController

if TYPE_CHECKING:
    from .agent_controller import SurfaceBinding


class OperationalTerminalOwner(ABC):
    surface: "SurfaceBinding"

    def __init__(self) -> None:
        self.terminals = TerminalController()

    @abstractmethod
    def start_operation(self, operation): ...

    def start_terminal_presentation(self, target):
        if self.surface.owns(target):
            self.start_operation(self.terminals.attach(target))

    def replace_terminal_session(self):
        from .terminal_controller import TerminalController
        previous = self.terminals
        self.terminals = TerminalController()
        if previous.executions:
            self.start_operation(previous.close())

