"""Shared session scope: the logical answers every session view provides.

Native sessions compose this with their framework base (ToadNode for Textual,
QWidget for Qt). The shared contract owns identity, display, navigation and
source answers without importing any toolkit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agent_comms.nominal.field_codec import AcpSessionId


class SessionScope(ABC):
    """The logical session: identity, display name, navigation and source.

    Native subclasses add their framework base. Textual adds ToadNode,
    COMMANDS, sidebars, keyboard_scopes and _pre_process. Qt adds its
    QWidget and native lifecycle.
    """

    @property
    @abstractmethod
    def is_current(self) -> bool: ...

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @property
    @abstractmethod
    def navigation_target(self) -> object: ...

    @property
    @abstractmethod
    def origin(self) -> object: ...

    @property
    @abstractmethod
    def thread_identity(self) -> object: ...

    @property
    def sidebar_thread_identity(self) -> object:
        return self.thread_identity

    @abstractmethod
    def belongs_to_wire(self, root: Path) -> bool: ...

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return False
