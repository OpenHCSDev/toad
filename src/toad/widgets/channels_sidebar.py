"""The shared Channels view, including during a destination's loading frame.

While no tab is shown it holds the whole window (`SidebarLayout.holds_alone`) and carries
what the welcome page did: Toad's banner, the project and the buses above the search and
rows, and the key hints below them. Qt's comms sidebar shows the same parts
(`QtToadApp.present_alone`)."""

from formbridge.key_declarations import TextEntryMode
from textual import on
from textual.app import ComposeResult
from textual.containers import Center, VerticalGroup
from textual.content import Content
from textual.events import Mount
from textual.widget import Widget
from textual.widgets import Static

from toad.client.application_actions import NewSessionAction
from toad.client.welcome import WelcomeLocation
from toad.constants import WELCOME
from toad.format_path import format_path
from toad.native_style import AutoHeight, MutedText, NoWrap, SpacedAbove, StartsHidden
from toad.screens.bus_choice import ListsBuses
from toad.sidebar_layout import CHANNELS_PANEL
from toad.sidebar_placement import ChannelsSidebarPlacement
from toad.welcome_banner import WelcomeBanner
from toad.widget_actions import ToggleIrcAction, WidgetAction
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.session_sort import ChannelListSort
from toad.widgets.side_bar import SideBar
from toad.widgets.splash_text import SplashText


class SidebarBanner(WelcomeBanner, SplashText, MutedText, NoWrap):
    """The app's name at the head of the comms sidebar, swept into the theme's colours each
    time the sidebar comes to hold the window."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = self.styles.height = "auto"

    @on(Mount)
    def on_mount(self) -> None:
        self.watch(self.app, "app_focus", self.focus_changed, init=False)

    @property
    def plays(self) -> bool:
        return (self.is_attached and self.query_ancestor(ChannelsSidebar).holds_alone
                and self.app.app_focus)

    def focus_changed(self, focused: bool) -> None:
        # An unfocused terminal runs no timer for this view.
        if not focused:
            self.stop_effect()
            self.refresh()


class SidebarNote(MutedText, SpacedAbove, Static):
    """A muted line under the banner or the rows: the project, the key hints. Centred, as
    Qt's lines are."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "100%"
        self.styles.text_align = "center"


class SidebarLocationNote(WelcomeLocation, SidebarNote):
    """The location line (`WelcomeLocation`): the project this TUI works in."""

    def __init__(self) -> None:
        super().__init__("", markup=False)

    @on(Mount)
    def name_location(self) -> None:
        self.update(self.location_line(self.app))

    def location(self, app) -> str:
        return format_path(app.project_dir.path)


class SidebarHints(SidebarNote):
    """The keys the window answers while the sidebar holds it (`ToadApp.welcome_hints`)."""

    @on(Mount)
    def name_keys(self) -> None:
        self.update(Content.from_markup(self.app.welcome_hints))


class SidebarHeading(MutedText, Static):
    """A section title that is not a sidebar group's (the buses are not sidebar-model rows)."""


class SidebarBuses(SpacedAbove, AutoHeight, ListsBuses, VerticalGroup):
    """The buses this machine can open, under the project line while the sidebar holds the
    window, in the first screen however many threads the rows list.

    Tristan: "I would like it to show the buses as well so that it would list out the buses
    that are available", and then that it "didn't list the other buses on the tailnet". It
    inherits the Open-bus dialog's own listing (ListsBuses), so the rows, the tailnet's peers
    and what choosing one does are the dialog's, not a second set that can drift from it."""

    def compose(self) -> ComposeResult:
        yield SidebarHeading(Content(self.buses_title))
        yield self.bus_rows()


class SoleNewSessionAction(WidgetAction):
    """`n` starts this launch's session while the sidebar holds the window, as the welcome's
    key did (`NewSessionAction`)."""

    title = "New session"
    keys = {TextEntryMode: ("n",)}
    show = True

    def available(self, sidebar: ChannelsSidebar) -> bool:
        return sidebar.holds_alone and sidebar.app.focused is not sidebar.search_input

    async def apply(self, sidebar: ChannelsSidebar) -> None:
        await NewSessionAction().apply(sidebar.app)


class SoleIrcAction(WidgetAction):
    """ctrl+g opens the channel view from home while the sidebar holds the window, as the
    welcome's key did (`ToggleIrcAction` on the home view); beside a tab the view's own key
    answers."""

    title = ToggleIrcAction.title
    keys = ToggleIrcAction.keys

    def available(self, sidebar: ChannelsSidebar) -> bool:
        return sidebar.holds_alone

    async def apply(self, sidebar: ChannelsSidebar) -> None:
        await sidebar.app.workspace_sessions.origin(WELCOME).require().toggle_irc()


class ChannelsSidebar(SideBar, actions=(SoleNewSessionAction, SoleIrcAction)):
    COMPOSITING_LAYER = True

    def __init__(self, *, observe: bool = True, defer_mount: bool = False) -> None:
        self.roster = CommsSidebar(observe=observe)
        super().__init__(
            SideBar.Panel(
                title=CHANNELS_PANEL.title,
                widget=self.roster,
                flex=CHANNELS_PANEL.flex,
                header_control=ChannelListSort(),
            ),
            placement_identity=ChannelsSidebarPlacement,
            defer_mount=defer_mount,
        )

    def lead_parts(self) -> tuple[Widget, ...]:
        # The banner keeps its own width (its sweep's frames are built for it), centred
        # across the window it holds, as Qt's `Banner` and the welcome drew it.
        # The buses sit under the location, in the first screen however many threads the
        # rows below list (Qt's `QtSidebarBuses` sits there too).
        self.banner = SidebarBanner()
        return (Center(self.banner), SidebarLocationNote(), SidebarBuses())

    def tail_parts(self) -> tuple[Widget, ...]:
        return (SidebarHints(),)

    @on(Mount)
    def show_alone_parts(self) -> None:
        self.present_alone()

    def present_alone(self) -> None:
        """Show the banner, project, buses and hints while the sidebar holds the window, and
        sweep the banner each time it comes to; hide them beside a tab."""
        super().present_alone()
        alone = self.holds_alone
        for part in (*self.shell_lead, *self.shell_tail):
            part.display = alone
        if not self.banner.is_attached:
            return
        if alone:
            self.banner.play()
        else:
            self.banner.stop_effect()


class ChannelsSlot(StartsHidden):
    """A tab declares where shared navigation belongs; it owns no channel rows."""
