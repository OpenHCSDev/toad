"""Where this Toad's terminal is attached from: each origin keeps its own sidebar arrangement."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from agent_comms.nominal.declared_family import DeclaredFamily

from toad.sidebar_placement import BandSplit, SidebarPlacement


class TerminalOrigin(DeclaredFamily, affix="Terminal"):
    """The kind of terminal this process draws on, read once from its environment."""

    @staticmethod
    def of(environment: Mapping[str, str] = os.environ) -> type[TerminalOrigin]:
        """The boundary: sshd exports SSH_CONNECTION into every session it starts."""
        return SshTerminal if "SSH_CONNECTION" in environment else LocalTerminal


class LocalTerminal(TerminalOrigin):
    """This machine's own terminal."""


class SshTerminal(TerminalOrigin):
    """A terminal reaching Toad over SSH, such as a phone."""


@dataclass(frozen=True)
class TerminalLayout:
    """One terminal origin's saved sidebar placements and band splits; a role it lacks keeps
    its initial placement, and an edge it lacks splits its band evenly."""

    origin: type[TerminalOrigin]
    placements: tuple[SidebarPlacement, ...] = ()
    splits: tuple[BandSplit, ...] = ()
