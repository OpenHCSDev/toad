"""Live channel members use the sidebar's keyed widget reconciliation."""

from dataclasses import dataclass
from pathlib import Path

from agent_comms.messaging.display_references import (
    ReferenceContext,
    RetiredThreadReference,
    ThreadDisplayReference,
    ThreadReferenceReader,
)
from agent_comms.registry.thread_identity import ThreadIncarnation
from textual import widgets
from textual.containers import VerticalGroup
from textual.content import Content

from toad.channel_activity_dispatch import ChannelActivityCompute
from toad.client.connection import CoordinationAccess
from toad.keyed_rows import KeyedRows
from toad.sidebar_changes import SidebarChange
from toad.sidebar_contracts import ActivityRows
from toad.sidebar_model_view import SidebarModelView
from toad.status_thread import NoStatusThread, StatusThread
from toad.widgets.session_details import ConversationSessionDetails


@dataclass(frozen=True)
class PeerStatus(ThreadReferenceReader[StatusThread]):
    """A member row's status is its current thread's; a retired birth has none to show."""

    root: Path
    access: CoordinationAccess

    def current(self, reference: ThreadDisplayReference) -> StatusThread:
        return StatusThread.for_root(self.root, reference.name, self.access)

    def retired(self, reference: RetiredThreadReference) -> StatusThread:
        return NoStatusThread()


class ChannelActivity(ChannelActivityCompute, SidebarModelView, ActivityRows, KeyedRows[ThreadIncarnation], VerticalGroup):
    DEFAULT_CSS = """
    ChannelActivity {
        height: auto;
        max-height: 33vh;
        overflow-y: auto;

        & > Collapsible {
            border-top: none;
            padding: 0;

            & > Contents {
                padding: 0 0 0 1;
            }
        }
    }
    """

    def __init__(self, view):
        self.view = view
        self._members = VerticalGroup()
        self.details = widgets.Collapsible(
            self._members, title="0 active", collapsed=True
        )
        super().__init__()

    def compose(self):
        yield self.details

    @property
    def member_container(self):
        return self._members

    @property
    def rows(self):
        return {
            row.peer: row
            for row in self.member_container.children
            if not row.is_leaving
        }

    def model_replaced(self) -> None:
        self.member_container.remove_children()

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        change.apply_activity(self)

    def create_row(self, peer: ThreadIncarnation):
        return ConversationSessionDetails(peer)

    def update_row(self, peer: ThreadIncarnation, row) -> None:
        row.bind(self.references.thread(peer).read(
            PeerStatus(self.model_state.root(), self.app.coordination_access)))

    def sync_members(self, changed: frozenset[ThreadIncarnation]) -> None:
        if self.is_attached and not self.is_leaving:
            members = self.members
            self.details.title = Content(self.view.conversation.activity_title(members))
            self.reconcile_keys(tuple(row.incarnation for row in members), changed=changed)
