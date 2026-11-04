"""Where this Toad's terminal is attached from: each origin keeps its own workspace layout."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import ClassVar

from agent_comms.nominal.declared_family import DeclaredFamily
from formbridge.forms.declared_fields import FieldPath

from toad.preferences import SETTINGS


class TerminalOrigin(DeclaredFamily, affix="Terminal"):
    """The kind of terminal this process draws on, read once from its environment."""

    layout: ClassVar[FieldPath]
    """The saved sidebar arrangement this origin reads and writes."""

    @staticmethod
    def of(environment: Mapping[str, str] = os.environ) -> type[TerminalOrigin]:
        """The boundary: sshd exports SSH_CONNECTION into every session it starts."""
        return SshTerminal if "SSH_CONNECTION" in environment else LocalTerminal


class LocalTerminal(TerminalOrigin):
    layout = SETTINGS.layout.local


class SshTerminal(TerminalOrigin):
    layout = SETTINGS.layout.ssh
