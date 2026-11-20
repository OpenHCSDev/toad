"""Toolkit-neutral compute methods for a channel's live member activity.

The `ActivityRows` contract in `sidebar_contracts.py` declares the abstract shape;
this module ships the concrete implementations of the compute paths that any
view can reuse by inheritance — `members`, `member_keys`, `channel_name`,
`accepts_observation`, `changed_keys`.

Textual's `ChannelActivity` inherits this mixin instead of restating the bodies,
so the data source (`self.view.conversation.active_members(self.model_state.shown)`,
etc.) is owned once. A Qt channel-activity panel that follows the same architecture
can inherit it the same way.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING

from agent_comms.messaging.display_references import ReferenceContext
from agent_comms.registry.thread_identity import ThreadIncarnation

if TYPE_CHECKING:
    from agent_comms.ui_model.sidebar import SidebarModel
    from toad.client.conversation import ConversationKind
    from toad.client.connection import Observing
    from toad.sidebar_model_view import SidebarModelState


class ChannelActivityTitle:
    """What a channel's activity line says: which of its members are active, titled once for
    every frontend. The host supplies the conversation and the sidebar model it reads."""

    activity_conversation: ConversationKind
    activity_model: SidebarModel

    @property
    def members(self) -> tuple:
        """The sidebar model's active members for the channel this view shows."""
        return self.activity_conversation.active_members(self.activity_model)

    @property
    def activity_title(self) -> str:
        return self.activity_conversation.activity_title(self.members)


class ChannelActivityCompute(ChannelActivityTitle):
    """Compute methods shared by every live channel-activity view.

    The owner supplies `self.view` (with `conversation`, `is_current_session`,
    `_bound_root`), `self.model_state` (a `SidebarModelState`), `self.references`
    (`ReferenceContext`), and `self.rows` (a mapping of key → row with a `.row`
    attribute carrying the display name) via its own base classes. This mixin
    does not store state; it reads what the host already exposes.
    """

    # Attributes the host must provide. Declared here for type/clarity; host
    # classes assign them in __init__ or inherit them from their own bases.
    view: object
    model_state: SidebarModelState
    references: ReferenceContext

    @property
    def activity_conversation(self):
        return self.view.conversation

    @property
    def activity_model(self):
        return self.model_state.shown

    @property
    def member_keys(self) -> Iterable[ThreadIncarnation]:
        return tuple(row.incarnation for row in self.members)

    def channel_name(self, references: ReferenceContext) -> str:
        return self.view.conversation.destination(references).name

    def accepts_observation(self) -> bool:
        return self.view.is_current_session and self.model_state.serves(self.view._bound_root)

    def changed_keys(self, names: frozenset[str]) -> frozenset[ThreadIncarnation]:
        return frozenset(
            member.incarnation for member in self.members if member.name in names
        ) | frozenset(
            row.peer for row in self.rows.values() if row.row.name in names
        )

    @property
    @abstractmethod
    def rows(self) -> dict: ...
