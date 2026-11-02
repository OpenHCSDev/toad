"""A tool publication's uncoordinated or original coordinated source identity."""
from dataclasses import dataclass

from agent_comms.sent_message import AssignedSourceIdentity
from agent_comms.nominal.declared_family import DeclaredFamily


@dataclass(frozen=True)
class ToolCallSource(DeclaredFamily, affix="ToolCallSource"):
    """The source identity retained by an application tool publication."""


class UncoordinatedToolCallSource(ToolCallSource):
    """A native SDK session without a coordinated BUS source."""


@dataclass(frozen=True)
class AssignedToolCallSource(ToolCallSource, AssignedSourceIdentity):
    """Inherit the original source fields and birth-aware identity semantics."""
