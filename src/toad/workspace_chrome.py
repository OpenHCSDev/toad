"""Fixed native workspace chrome; logical session switches never reparent it."""
from typing import TYPE_CHECKING
from textual.app import ComposeResult
from textual.containers import Horizontal
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.footer import Footer
from toad.session_presentation import NativeSessionSurface

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
        self.native = NativeSessionSurface(app)

    def prepare_navigation(self, screen) -> bool:
        """Restore the single shared Channels surface independently of tab-local panels."""
        changed = self.channels.restore_navigation()
        self.channels.schedule_hydration()
        roster = self.channels.roster
        roster.navigation.prepare()
        screen.frame_presentation.defer(roster, roster.navigation.start)
        return changed

    def sidebar_geometry(self, screen):
        """Resolve both mounted bars in the workspace's screen coordinates."""
        from toad.widgets.side_bar import SideBar

        bars = {bar.id: bar for bar in screen.query(SideBar)
                if bar.id in screen.app.sidebar_layout.placements and bar.display
                and all(ancestor.display for ancestor in bar.ancestors)}
        resolved = screen.app.sidebar_layout.resolve(
            screen.size.width, {identity: bar.collapsed for identity, bar in bars.items()})
        channels = bars.get(self.channels.id)
        gutters = {"left": 0, "right": 0}
        if channels is not None:
            placement = screen.app.sidebar_layout.get(channels.id)
            if channels.collapsed or not placement.floating:
                gutters[placement.side] = resolved.bars[channels.id].width
        return resolved, gutters

    async def select(self, view: "SessionView") -> None:
        roster = self.channels.roster
        roster.navigation.capture()
        await roster.observation.bind(view.app.coordination_access.service)
        actor, target = view.channels_context()
        roster.session_thread = actor
        roster.selected = target
        roster.observation.set_enabled(view.shows_channels)
        self.channels.display = view.shows_channels
        self.footer.compact = view.footer_compact
        self.footer.call_later(self.footer.bindings_changed, view.screen)
