"""MCP decisions own their CLI spelling, labels and eligibility."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
import os

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from toad.mcp_declarations import Declaration, Inventory


@dataclass(frozen=True)
class MCPSelection:
    inventory: Inventory
    row: Declaration

    @property
    def eligible(self) -> bool:
        return self.row.effective and self.row.enabled and self.inventory.project_trusted_saved

    def matches(self, inventory: Inventory | None) -> bool:
        return inventory == self.inventory


class MCPDecision(Command, DeclaredFamily, affix="Command"):
    @property
    @abstractmethod
    def label(self) -> str: ...

    @abstractmethod
    def arguments(self) -> tuple[str, str]: ...

    @abstractmethod
    def permits(self, row: Declaration) -> bool: ...

    @property
    def button_id(self) -> str:
        return self.declared_name

    def available(self, selection: MCPSelection) -> bool:
        if os.name != 'posix' or not selection.eligible:
            return False
        return selection.row in selection.inventory.rows and self.permits(selection.row)

    def apply(self, selection: MCPSelection) -> tuple[str, ...]:
        if not self.available(selection):
            raise ValueError("Unsupported MCP decision")
        row = selection.row
        return (*self.arguments(), '--id', row.id, '--digest', row.digest,
                '--project', selection.inventory.project_root)


class ProjectTrustDecision(MCPDecision):
    def arguments(self) -> tuple[str, str]:
        return 'trust', self.declared_name

    def permits(self, row: Declaration) -> bool:
        return row.scope.allows_trust_decision()


class CallDecision(MCPDecision):
    def arguments(self) -> tuple[str, str]:
        return 'calls', self.declared_name

    def permits(self, row: Declaration) -> bool:
        return row.status.allows_call_decision()


class ApproveCommand(ProjectTrustDecision):
    label = 'Approve project'


class DenyCommand(ProjectTrustDecision):
    label = 'Deny project'


class AskCommand(CallDecision):
    label = 'Require call asks'


class AllowCommand(CallDecision):
    label = 'Allow autonomous calls'
