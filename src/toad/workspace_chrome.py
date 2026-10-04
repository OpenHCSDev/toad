"""Fixed native workspace chrome; logical session switches never reparent it."""
from typing import TYPE_CHECKING
from textual.app import ComposeResult
from textual.containers import Horizontal
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.footer import Footer
from toad.session_presentation import NativeSessionSurface
from toad.core_event_carrier import CoreEventReceiver, CoreEventMessage
from toad.core.events import SidebarLayoutChanged
from agent_comms.mro_dispatch import handles

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.session_view import SessionView


class WorkspaceHeader(CoreEventReceiver, Horizontal):
    def on_mount(self) -> None:
        self.observe_core(self.app.events)

    @handles(SidebarLayoutChanged)
    async def sidebar_layout_changed(self, event: CoreEventMessage) -> None:
        self.app.workspace_chrome.layout_sidebars(self.screen)

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

    def layout_sidebars(self, screen) -> bool:
        """Resolve and publish one mounted sidebar cohort in native frame order."""
        from toad.widgets.side_bar import SideBar

        bars = tuple(bar for bar in screen.query(SideBar)
                     if bar.id in screen.app.sidebar_layout.placements)
        visible = tuple(bar for bar in bars if bar.presentation_visible)
        resolved = screen.app.sidebar_layout.resolve(
            screen.size.width, {bar.id: bar.collapsed for bar in visible})
        changed = False
        with screen.app.batch_update():
            for bar in bars:
                changed |= bar._apply_layout(resolved)
            # Sibling order belongs to their shared placement, not to each bar.
            order = {identity: index for index, identity in
                     enumerate(screen.app.sidebar_layout.ordered())}
            for parent in dict.fromkeys(bar.parent for bar in visible):
                if parent is None:
                    continue
                before = tuple(parent.children)
                after = tuple(sorted(before, key=lambda child: order.get(child.id, len(order))))
                if before != after:
                    parent.sort_children(key=lambda child: order.get(child.id, len(order)))
                    changed = True
        return changed

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
