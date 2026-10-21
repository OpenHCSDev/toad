"""Live channel members use the sidebar's keyed widget reconciliation."""

from agent_comms.channel_targets import ThreadTarget
from textual import widgets
from textual.content import Content
from textual.containers import VerticalGroup

from toad.session_scope import SessionScope
from toad.widgets.observed_thread_activity import StatusThread
from toad.widgets.sidebar_tree import KeyedRows, SidebarChange, SidebarModelView


class ChannelActivity(SidebarModelView, KeyedRows, VerticalGroup):
    def __init__(self, view):
        self.view = view
        self._members = VerticalGroup()
        self.details = widgets.Collapsible(self._members, title="0 active", collapsed=True)
        self.details.styles.padding = 0
        super().__init__()
        self.styles.overflow_y = "auto"
        self.styles.max_height = "33vh"

    def compose(self):
        yield self.details

    @property
    def member_container(self):
        return self._members

    @property
    def rows(self):
        return {row.target.name: row for row in self.member_container.children if not row.is_leaving}

    @property
    def members(self):
        return self.view.conversation.active_members(self.model_state.shown)

    @property
    def member_keys(self):
        return tuple(row.name for row in self.members)

    def accepts_observation(self) -> bool:
        return (self.view.query_ancestor(SessionScope).is_current
                and self.model_state.serves(self.view._bound_root))

    def model_replaced(self) -> None:
        self.member_container.remove_children()

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        change.apply_activity(self)

    def create_row(self, name):
        row = self.view.conversation.activity_details(ThreadTarget(name))
        row.thread = StatusThread.for_root(
            self.model_state.root(), name, self.app.coordination_access)
        return row

    def sync_members(self, changed: frozenset[str]) -> None:
        if self.is_attached and not self.is_leaving:
            members = self.members
            names = ", ".join(row.name for row in members[:2])
            remaining = f" +{len(members) - 2}" if len(members) > 2 else ""
            self.details.title = Content(f"{len(members)} active · {names}{remaining}")
            self.reconcile_keys(tuple(row.name for row in members), changed=changed)
