"""Shared session scope: the logical answers every session view provides.

Native sessions compose this with their framework base (ToadNode for Textual,
QWidget for Qt). The shared contract owns identity, display, navigation and
source answers without importing any toolkit.
"""

from __future__ import annotations

from pathlib import Path

from agent_comms.nominal.field_codec import AcpSessionId


class SessionScope:
    """The logical session: identity, display name, navigation and source.

    A plain parent: ABCMeta would conflict with each toolkit's widget metaclass.

    Native subclasses add their framework base. Textual adds ToadNode,
    COMMANDS, sidebars, keyboard_scopes and _pre_process. Qt adds its
    QWidget and native lifecycle.
    """

    @property
    def is_current(self) -> bool:
        raise NotImplementedError

    @property
    def display_name(self) -> str:
        raise NotImplementedError

    @property
    def navigation_target(self) -> object:
        raise NotImplementedError

    @property
    def origin(self) -> object:
        raise NotImplementedError

    @property
    def thread_identity(self) -> object:
        raise NotImplementedError

    @property
    def sidebar_thread_identity(self) -> object:
        return self.thread_identity

    def belongs_to_wire(self, root: Path) -> bool:
        raise NotImplementedError

    def matches_launch(self, agent_identity: str, session_id: AcpSessionId) -> bool:
        return False
