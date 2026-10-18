"""Live channel members use the sidebar's keyed widget reconciliation."""

from textual.containers import VerticalGroup

from toad.screens.session_view import SessionView
from toad.widgets.observed_thread_activity import StatusThread
from toad.widgets.sidebar_tree import KeyedRows, SidebarModelView, UnpaintedChannel


class ChannelActivity(SidebarModelView, KeyedRows, VerticalGroup):
    def __init__(self, view):
        self.view = view
        self._members = VerticalGroup()
        super().__init__()

    def compose(self):
        yield self._members

    @property
    def member_container(self):
        return self._members

    @property
    def rows(self):
        return {row.target.name: row for row in self.member_container.children if not row.is_leaving}

    @property
    def member_keys(self):
        model = self.model_state.shown
        channel = model.channels.rows.get(self.view.target, UnpaintedChannel(self.view.target))
        return tuple(name for name in channel.members if model.threads.rows[name].active)

    def accepts_observation(self) -> bool:
        return (self.view.query_ancestor(SessionView).is_current
                and self.model_state.serves(self.view._bound_root))

    def model_replaced(self) -> None:
        self.member_container.remove_children()

    def sync(self, *, channels, threads, reorder=False) -> None:
        self.call_next(self.sync_members)

    def create_row(self, name):
        row = self.view.conversation_kind.activity_details(name)
        row.thread = StatusThread.for_root(
            self.model_state.root(), name, self.app.coordination_access)
        return row

    def sync_members(self) -> None:
        if self.is_attached and not self.is_leaving:
            self.reconcile_keys(self.member_keys, changed=frozenset())
