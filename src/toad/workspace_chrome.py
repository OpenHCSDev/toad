"""Fixed native workspace chrome; logical session switches never reparent it."""
from typing import TYPE_CHECKING
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.geometry import Offset, Region, Size, Spacing
from textual.layout import ArrangeResult, WidgetPlacement
from textual.layouts.vertical import VerticalLayout
from textual.widget import Widget
from toad.widgets.channels_sidebar import ChannelsSidebar
from toad.widgets.footer import ToadFooter
from ui_theme.scheme import HeaderToneColour
from toad.frame_presentation import TonePaint
from toad.widget_view import AUTO, FILL, WidgetView
from toad.session_presentation import NativeSessionSurface

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.session_view import SessionView


class WorkspaceHeader(TonePaint, WidgetView, Horizontal):
    tone = HeaderToneColour
    width = FILL
    height = AUTO

    def compose(self) -> ComposeResult:
        from toad.widgets.session_tabs import SessionsTabs
        from toad.widgets.side_bar import TabHistoryControls
        yield TabHistoryControls()
        yield SessionsTabs()


class WorkspaceChrome(VerticalLayout):
    def __init__(self, app: "ToadApp") -> None:
        self.navigation = WorkspaceHeader(id="tab-navigation-header")
        self.channels = ChannelsSidebar()
        self.footer = ToadFooter(id="workspace-footer")
        self.native = NativeSessionSurface(app)

    async def prepare_navigation(self, screen) -> bool:
        """Restore the single shared Channels surface independently of tab-local panels."""
        changed = self.channels.restore_navigation()
        self.channels.schedule_hydration()
        roster = self.channels.roster
        await roster.navigation.prepare()
        screen.start_sidebar_navigation(roster)
        return changed

    def refresh_layout(self) -> None:
        """Placement changes retire both native parent arrangements."""
        source = self.channels.app.workspace_sessions.source
        for parent in {bar.parent for bar in (self.channels, *source.sidebars()) if bar.is_mounted}:
            parent.refresh(repaint=False, layout=True)

    def arrange(self, parent: Widget, children: list[Widget], size: Size,
                greedy: bool = True) -> ArrangeResult:
        """Place chrome and conversation directly in the native layout pass."""
        source = parent.app.workspace_sessions.source
        layout = parent.app.sidebar_layout
        own = tuple(source.sidebars())
        bars = tuple(bar for bar in (self.channels, *own)
                     if bar.presentation_visible and bar.id in layout.placements)
        resolved = layout.resolve(size.width, {bar.id: bar.collapsed for bar in bars})
        # The outer host stays full width. Its session's own native layout
        # clears both gutters, including the shared channel surface.
        nested = parent is self.channels.parent and any(
            bar.parent.layout is self for bar in own)
        left = 0 if nested else resolved.left_gutter
        right = 0 if nested else resolved.right_gutter
        placements = [placement._replace(
            region=placement.region + Offset(left, 0),
            margin=placement.margin + Spacing(0, right, 0, left),
        ) for placement in super().arrange(
            parent, [child for child in children if child not in bars],
            Size(max(0, size.width - left - right), size.height), greedy)]
        order = {identity: index for index, identity in enumerate(layout.ordered())}
        for bar in bars:
            if bar in children:
                geometry = resolved.bars[bar.id]
                placements.append(WidgetPlacement(
                    Region(0, 0, geometry.width, size.height), Offset(geometry.x, 0),
                    Spacing(), bar, order[bar.id], overlay=True, absolute=True,
                ))
        return placements

    async def select(self, view: "SessionView") -> None:
        roster = self.channels.roster
        roster.navigation.capture()
        # The roster renders the observed service's model; a switch must not
        # capture the route again (file reads under a lock on the UI thread).
        # Route changes are the access owner's once-a-second check.
        view.app.coordination_access.observation.show_sidebar(roster)
        roster.set_enabled(view.shows_channels)
        self.channels.display = view.shows_channels
        self.footer.compact = view.footer_compact
        self.footer.call_later(self.footer.bindings_changed, view.screen)
        self.refresh_layout()
