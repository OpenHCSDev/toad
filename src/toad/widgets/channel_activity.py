"""Live channel members, reconciled from the shared sidebar's keyed rows."""

from textual.containers import VerticalScroll

from toad.widgets.observed_thread_activity import StatusThread
from toad.widgets.sidebar_tree import SidebarModelView


class ChannelActivity(SidebarModelView, VerticalScroll):
    DEFAULT_CSS = """
    ChannelActivity { height: auto; max-height: 30vh; }
    """

    def __init__(self, view):
        self.view = view
        self.rows = {}
        super().__init__()

    def accepts_observation(self) -> bool:
        from toad.screens.session_view import SessionView

        return self.view.query_ancestor(SessionView).is_current

    def model_replaced(self) -> None:
        for row in self.rows.values():
            row.remove()
        self.rows.clear()

    def sync(self, *, channels, threads, reorder=False) -> None:
        model = self.model_state.shown
        channel = model.channels.rows.get(self.view.target)
        members = () if channel is None else tuple(
            name for name in channel.members if model.threads.rows[name].active)
        for name in tuple(self.rows):
            if name not in members:
                self.rows.pop(name).remove()
        for name in members:
            if name not in self.rows:
                row = self.view.conversation_kind.activity_details(name)
                row.thread = StatusThread.for_root(
                    self.model_state.root(), name, self.app.coordination_access)
                self.rows[name] = row
                self.mount(row)
        positions = {self.rows[name]: index for index, name in enumerate(members)}
        if tuple(child for child in self.children if child in positions) != tuple(positions):
            self.sort_children(key=lambda row: positions.get(row, len(positions)))
