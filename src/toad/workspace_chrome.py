"""Fixed native workspace chrome; logical session switches never reparent it."""
from typing import TYPE_CHECKING
from textual.app import ComposeResult
from textual.containers import Horizontal
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.footer import Footer
from toad.session_presentation import BlankSessionSurface

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.session_view import SessionView


class WorkspaceHeader(Horizontal):
    def compose(self) -> ComposeResult:
        from toad.widgets.session_tabs import SessionsTabs
        from toad.widgets.side_bar import TabHistoryControls
        yield TabHistoryControls()
        yield SessionsTabs()


class WorkspaceChrome:
    def __init__(self, app: "ToadApp") -> None:
        self.navigation = WorkspaceHeader(id="tab-navigation-header")
        self.channels = ChannelsSidebar()
        self.footer = Footer(id="workspace-footer")
        self.blank = BlankSessionSurface(app)

    async def select(self, view: "SessionView") -> None:
        roster = self.channels.roster
        await roster.bind_wire(view.app.coordination_wire)
        actor, target = view.channels_context()
        roster.session_thread = actor
        roster.selected = target
        roster.set_observation_enabled(view.shows_channels)
        self.channels.display = view.shows_channels
        self.footer.compact = view.footer_compact
        self.footer.call_later(self.footer.bindings_changed, view.screen)
