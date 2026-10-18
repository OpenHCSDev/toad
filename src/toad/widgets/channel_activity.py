"""Live channel members, reconciled from the shared sidebar's keyed rows."""

from textual.containers import VerticalGroup

from toad.screens.session_view import SessionView
from toad.widgets.observed_thread_activity import StatusThread
from toad.widgets.sidebar_tree import SidebarModelView, UnpaintedChannel


class ChannelActivity(SidebarModelView, VerticalGroup):
    def __init__(self, view):
        self.view = view
        super().__init__()

    def accepts_observation(self) -> bool:
        return (self.view.query_ancestor(SessionView).is_current
                and self.model_state.serves(self.view._bound_root))

    def sync(self, *, channels, threads, reorder=False) -> None:
        self.call_next(self.sync_members)

    async def sync_members(self) -> None:
        model = self.model_state.shown
        channel = model.channels.rows.get(self.view.target, UnpaintedChannel(self.view.target))
        members = tuple(name for name in channel.members if model.threads.rows[name].active)
        present = {row.target.name: row for row in self.children}
        for name, row in present.items():
            if name not in members:
                await row.remove()
        for name in members:
            if name not in present:
                await self.mount(self.view.conversation_kind.activity_details(name))
        for row in self.children:
            row.bind(StatusThread.for_root(
                self.model_state.root(), row.target.name, self.app.coordination_access))
        present = {row.target.name: row for row in self.children}
        positions = {present[name]: index for index, name in enumerate(members)}
        if tuple(self.children) != tuple(positions):
            self.sort_children(key=lambda row: positions[row])
