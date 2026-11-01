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
from toad.widgets.switch_toast import SwitchToast
from ui_theme.scheme import HeaderToneColour
from toad.tone_paint import TonePaint
from toad.widget_view import AUTO, FILL, WidgetView
from toad.session_presentation import NativeSessionSurface
from toad.session_scope import SessionScope
from toad.sidebar_layout import SidebarEdge

if TYPE_CHECKING:
    from toad.app import ToadApp


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
        self.app = app
        self.navigation = WorkspaceHeader(id="tab-navigation-header")
        self.channels = ChannelsSidebar()
        self.footer = ToadFooter(id="workspace-footer")
        self.switch_toast = SwitchToast()
        self.native = NativeSessionSurface(app)

    def presented_sidebars(self):
        source = self.app.workspace_sessions.source
        layout = self.app.sidebar_layout
        return tuple(bar for bar in (self.channels, *source.sidebars())
                     if bar.presentation_visible and bar.id in layout.placements)

    def toggle_sidebar(self, side: type[SidebarEdge]) -> None:
        layout = self.app.sidebar_layout
        bars = tuple(bar for bar in self.presented_sidebars()
                     if layout.get(bar.id).side == side)
        collapsed = any(not bar.collapsed for bar in bars)
        for bar in bars:
            if bar.collapsed != collapsed:
                bar.toggle(focus=False)

    async def prepare_navigation(self, screen) -> bool:
        """Restore the single shared Channels surface independently of tab-local panels."""
        changed = self.channels.restore_navigation()
        self.channels.schedule_hydration()
        roster = self.channels.roster
        await roster.navigation.prepare()
        screen.start_sidebar_navigation(roster)
        return changed

    def refresh_layout(self) -> None:
        """Project placement intent before retiring both native arrangements."""
        bars = self.presented_sidebars()
        for bar in bars:
            bar.present_controls()
        for parent in {bar.parent for bar in bars}:
            parent.refresh(repaint=False, layout=True)

    def arrange(
        self, parent: Widget, children: list[Widget], size: Size, greedy: bool = True
    ) -> ArrangeResult:
        """Place chrome and conversation directly in the native layout pass."""
        layout = self.app.sidebar_layout
        bars = self.presented_sidebars()
        resolved = layout.resolve(size, {bar.id: bar.collapsed for bar in bars})
        # The outer host stays full width. Its session's own native layout
        # clears both gutters, including the shared channel surface.
        nested = parent is self.channels.parent and any(
            bar.parent is not parent and bar.parent.layout is self for bar in bars
        )
        gutter = Spacing() if nested else resolved.gutter
        placements = [
            placement._replace(
                region=placement.region + Offset(gutter.left, gutter.top),
                margin=placement.margin + gutter,
            )
            for placement in super().arrange(
                parent,
                [child for child in children if child not in bars],
                Size(max(0, size.width - gutter.width), max(0, size.height - gutter.height)),
                greedy,
            )
        ]
        order = {identity: index for index, identity in enumerate(layout.ordered())}
        for bar in bars:
            if bar in children:
                geometry = resolved.bars[bar.id]
                placements.append(
                    WidgetPlacement(
                        geometry.reset_offset,
                        geometry.offset,
                        Spacing(),
                        bar,
                        order[bar.id],
                        overlay=True,
                        absolute=True,
                    )
                )
        return placements

    async def select(self, view: "SessionScope") -> None:
        roster = self.channels.roster
        roster.navigation.capture()
        roster.set_enabled(view.shows_channels)
        self.channels.display = view.shows_channels
        self.footer.compact = view.footer_compact
        self.footer.call_later(self.footer.bindings_changed, view.screen)
        self.refresh_layout()
