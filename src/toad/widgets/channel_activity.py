"""Live channel members use the sidebar's keyed widget reconciliation."""

from dataclasses import dataclass
from pathlib import Path

from agent_comms.display_references import (
    RetiredThreadReference,
    ThreadDisplayReference,
    ThreadReferenceReader,
)
from agent_comms.thread_identity import ThreadIncarnation
from textual import widgets
from textual.containers import VerticalGroup
from textual.content import Content

from toad.comms_root import CoordinationAccess
from toad.status_thread import NoStatusThread, StatusThread
from toad.widgets.session_details import ConversationSessionDetails
from toad.widgets.sidebar_tree import KeyedRows, SidebarChange, SidebarModelView


@dataclass(frozen=True)
class PeerStatus(ThreadReferenceReader[StatusThread]):
    """A member row's status is its current thread's; a retired birth has none to show."""

    root: Path
    access: CoordinationAccess

    def current(self, reference: ThreadDisplayReference) -> StatusThread:
        return StatusThread.for_root(self.root, reference.name, self.access)

    def retired(self, reference: RetiredThreadReference) -> StatusThread:
        return NoStatusThread()


class ChannelActivity(SidebarModelView, KeyedRows[ThreadIncarnation], VerticalGroup):
    DEFAULT_CSS = """
    ChannelActivity {
        height: auto;
        max-height: 33vh;
        overflow-y: auto;

        & > Collapsible {
            /* A Collapsible draws a rule above itself and reserves a blank row below.
               Sitting under the prompt this list needs neither: the prompt's own edge
               already separates them, and the blank row only pushed the window up. */
            border-top: none;
            padding: 0;

            & > Contents {
                /* Textual indents contents by three and opens with a blank row. One
                   column is enough to show the members belong to the title. */
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

    @property
    def members(self):
        return self.view.conversation.active_members(self.model_state.shown)

    @property
    def member_keys(self):
        return tuple(row.incarnation for row in self.members)

    def accepts_observation(self) -> bool:
        return self.view.is_current_session and self.model_state.serves(self.view._bound_root)

    def model_replaced(self) -> None:
        self.member_container.remove_children()

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        change.apply_activity(self)

    def create_row(self, peer: ThreadIncarnation):
        return ConversationSessionDetails(peer)

    def update_row(self, peer: ThreadIncarnation, row) -> None:
        references = self.model_state.shown.observation.require_snapshot().references
        row.bind(references.thread(peer).read(
            PeerStatus(self.model_state.root(), self.app.coordination_access)))

    def changed_keys(self, names: frozenset[str]) -> frozenset[ThreadIncarnation]:
        return frozenset(
            member.incarnation for member in self.members if member.name in names
        ) | frozenset(
            row.peer for row in self.rows.values() if row.row.name in names
        )

    def sync_members(self, changed: frozenset[ThreadIncarnation]) -> None:
        if self.is_attached and not self.is_leaving:
            members = self.members
            names = ", ".join(row.name for row in members[:2])
            remaining = f" +{len(members) - 2}" if len(members) > 2 else ""
            self.details.title = Content(f"{len(members)} active · {names}{remaining}")
            self.reconcile_keys(tuple(row.incarnation for row in members), changed=changed)
