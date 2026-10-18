"""Live channel members use the sidebar's keyed widget reconciliation."""

from textual import widgets
from textual.content import Content
from textual.containers import VerticalGroup

from toad.screens.session_view import SessionView
from toad.widgets.observed_thread_activity import StatusThread
from toad.widgets.sidebar_tree import KeyedRows, SidebarChange, SidebarModelView


class ChannelActivity(SidebarModelView, KeyedRows, VerticalGroup):
    def __init__(self, view):
        self.view = view
        self._members = VerticalGroup()
        self.details = widgets.Collapsible(self._members, title="0 active", collapsed=True)
        self.details.styles.border = None
        self.details.styles.padding = 0
        super().__init__()

    def compose(self):
        yield self.details

    async def on_mount(self) -> None:
        contents = self.details.query_children(self.details.Contents).first()
        contents.styles.padding = 0
        contents.styles.overflow_y = "auto"
        self.watch(self.view, "virtual_size", self.bound_members)
        await super().on_mount()

    def bound_members(self, *_args) -> None:
        budget = max(1, self.view.size.height // 3)
        self.details.styles.max_height = budget
        self.details.query_children(self.details.Contents).first().styles.max_height = max(0, budget - 1)

    @property
    def member_container(self):
        return self._members

    @property
    def rows(self):
        return {row.target.name: row for row in self.member_container.children if not row.is_leaving}

    @property
    def member_keys(self):
        return tuple(row.name for row in self.view.conversation_kind.active_members(
            self.model_state.shown, self.view.target))

    def accepts_observation(self) -> bool:
        return (self.view.query_ancestor(SessionView).is_current
                and self.model_state.serves(self.view._bound_root))

    def model_replaced(self) -> None:
        self.member_container.remove_children()

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        change.apply_activity(self)

    def create_row(self, name):
        row = self.view.conversation_kind.activity_details(name)
        row.thread = StatusThread.for_root(
            self.model_state.root(), name, self.app.coordination_access)
        return row

    def sync_members(self) -> None:
        if self.is_attached and not self.is_leaving:
            members = self.view.conversation_kind.active_members(self.model_state.shown, self.view.target)
            self.details.title = Content(f"{len(members)} active · " + ", ".join(
                f"{row.name} {row.summary}" for row in members))
            self.reconcile_keys(tuple(row.name for row in members), changed=frozenset())
