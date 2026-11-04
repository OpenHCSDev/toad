from __future__ import annotations

from toad.core import session_requests, input_events
from toad.core.preference_events import PreferenceChanged
from toad.core_event_carrier import CoreEventReceiver
from metaclass_registry.mro_dispatch import handles
from toad.preferences import SETTINGS
from collections.abc import Iterator
from contextlib import suppress
from itertools import zip_longest
from random import shuffle
from typing import Literal, Self

from toad.widget_actions import DismissibleControl, CyclesFocus, Launches, WidgetAction, ProfileKeys
from textual.document._editing import EditingMode, VimMode
from textual.screen import Screen
from textual import events
from textual import work
from textual import getters
from textual import on
from textual.app import ComposeResult
from textual.content import Content
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual import containers
from textual import widgets
from textual.css.native import Keyword, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.view import AUTO, FILL
from ui_theme.scheme import (
    ForegroundColour, PanelColour, PrimaryColour, SecondaryColour, SuccessColour, WarningColour,
)
from toad.native_style import (
    AutoHeight,
    AutoWidth,
    EllipsisOverflow,
    FullWidth,
    NoMargin,
    NoWrap,
    PointerCursor,
    RightPadding,
    SecondaryText,
    SideMargin,
    SidePadding,
    TransparentBackground,
)
from textual.widgets._footer import FooterKeyComponent
from toad.widgets.footer import ToadFooter, ToadFooterKey

import toad
from toad.app import ToadApp
from toad.format_path import format_path
from agent_comms.repo import Checkout
from toad.pill import pill
from toad.widgets.directory_input import DirectoryInput
from toad.widgets.mandelbrot import Mandelbrot
from toad.widgets.condensed_path import CondensedPath
from toad.widgets.grid_select import GridCell, GridSelect
from toad.agent_schema import AgentDefinition
from toad.agents import AgentReadError, read_agents
from toad.app_node import ToadNode
from textual.widget import Widget


QR = """\
█▀▀▀▀▀█ ▄█ ▄▄█▄▄█ █▀▀▀▀▀█
█ ███ █ ▄█▀█▄▄█▄  █ ███ █
█ ▀▀▀ █ ▄ █ ▀▀▄▄▀ █ ▀▀▀ █
▀▀▀▀▀▀▀ ▀ ▀ ▀ █ █ ▀▀▀▀▀▀▀
█▀██▀ ▀█▀█▀▄▄█   ▀ █ ▀ █ 
 █ ▀▄▄▀▄▄█▄▄█▀██▄▄▄▄ ▀ ▀█
▄▀▄▀▀▄▀ █▀▄▄▄▀▄ ▄▀▀█▀▄▀█▀
█ ▄ ▀▀▀█▀ █ ▀ █▀ ▀ ██▀ ▀█
▀  ▀▀ ▀▀▄▀▄▄▀▀▄▀█▀▀▀█▄▀  
█▀▀▀▀▀█ ▀▄█▄▀▀  █ ▀ █▄▀▀█
█ ███ █ ██▄▄▀▀█▀▀██▀█▄██▄
█ ▀▀▀ █ ██▄▄ ▀  ▄▀ ▄▄█▀ █
▀▀▀▀▀▀▀ ▀▀▀  ▀   ▀▀▀▀▀▀▀▀"""



class PointerHover(Widget):
    """While the pointer is anywhere over the widget, children included, its hover look applies.

    The resting look (in ``native_theme``) declares every property the hover look changes.
    """

    hover_theme: tuple[NativeDeclaration, ...] = ()
    pointer_theme: tuple[NativeDeclaration, ...] = ()

    def native_declarations(self) -> tuple[NativeDeclaration, ...]:
        return (*super().native_declarations(), *self.pointer_theme)

    @on(events.Enter)
    @on(events.Leave)
    def pointer_moved(self) -> None:
        self.pointer_theme = ((), self.hover_theme)[self.is_mouse_over]
        self.app.update_styles(self)


class ProjectPath(
    FullWidth,
    TransparentBackground,
    PointerCursor,
    PointerHover,
    CondensedPath,
):
    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(WarningColour.name)), NativeDeclaration.of(Styles.text_style, Keyword("none")))
    hover_theme = (
        NativeDeclaration.of(Styles.background, Variable(ForegroundColour.name), Percent(4)),
        NativeDeclaration.of(Styles.text_style, Keyword("underline")),
    )



class DirectoryDisplay(
    DismissibleControl,
    CoreEventReceiver,
    containers.HorizontalGroup,
):
    native_theme = (
        NativeDeclaration.of(
            Styles.border_bottom, Keyword("solid"), Variable(ForegroundColour.name), Percent(10)
        ),
    )
    path = reactive("")
    edit = reactive(False)

    directory_input = getters.query_one(DirectoryInput)
    condensed_path = getters.query_one(ProjectPath)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 1, 0, 2)

    def on_mount(self) -> None:
        self.watch(self.app, ToadApp.project_dir.name, self.project_changed)

    def project_changed(self, project: Checkout) -> None:
        self.path = format_path(project.path, directory=True)

    def focus(self, scroll_visible=True) -> Self:
        self.edit = True
        self.directory_input.focus(scroll_visible=scroll_visible)
        return self

    @on(events.Click, "CondensedPath")
    def on_click(self) -> None:
        self.edit = True
        self.directory_input.focus()

    @on(events.DescendantBlur)
    def on_blur(self):
        self.dismiss_control()

    @on(widgets.Input.Submitted)
    def on_input_submitted(self, event: widgets.Input.Submitted) -> None:
        self.edit = False
        self.publish_core(input_events.ChangeDirectory(event.value))

    def dismiss_control(self) -> None:
        self.edit = False
        self.directory_input.value = self.path

    def watch_edit(self, edit: bool) -> None:
        self.condensed_path.display = not edit
        self.directory_input.display = edit
        if not edit and self.directory_input.has_focus:
            self.directory_input.blur()

    def compose(self) -> ComposeResult:
        yield widgets.Label("📁 ")
        yield ProjectPath(self.path, directory=True).data_bind(
            path=DirectoryDisplay.path
        ).with_tooltip("Project directory for new agent sessions (click to edit)")
        yield DirectoryInput(self.path, select_on_focus=True, compact=True).data_bind(
            value=DirectoryDisplay.path
        )


class GridItem(
    GridCell,
    PointerHover,
    TransparentBackground,
    SidePadding,
    PointerCursor,
):
    """A selectable entry in one of the store's grids."""

    native_theme = (NativeDeclaration.of(Styles.border, Keyword("tall"), Keyword("transparent")),)
    hover_theme = (NativeDeclaration.of(Styles.background, Variable(PanelColour.name)),)



class AgentItemGrid(AutoHeight, containers.Grid):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_size_columns = 2
        self.styles.grid_size_rows = 1
        self.styles.grid_columns = (FILL, AUTO)


class AgentKindTag(widgets.Label):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_align = "right"


class AgentAuthor(SecondaryText, widgets.Label):

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_style = "italic"


class AgentDescription(widgets.Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_style = "dim"


class AgentItem(GridItem, containers.VerticalGroup):
    """An entry in the agent grid select."""

    def __init__(self, agent: AgentDefinition) -> None:
        self._agent = agent
        super().__init__()

    @property
    def agent(self) -> AgentDefinition:
        return self._agent

    def compose(self) -> ComposeResult:
        agent = self._agent
        with AgentItemGrid():
            yield widgets.Label(agent.name)
            tag = pill(
                agent.kind.heading,
                "$primary-muted 50%",
                "$text-primary",
                filled=self.app.colours.ink.fills_pills,
            )
            yield AgentKindTag(tag)
        yield AgentAuthor(agent.author_name)
        yield AgentDescription(agent.description)


class LauncherGridSelect(Launches, CoreEventReceiver, GridSelect, ToadNode):

    HELP = """\
## Launcher

Your favorite agents.

- **1-9 a-f** Select agent
- **cursor keys** navigate agents
- **tab / shift+tab** Move to next / previous section
- **space** Launch highlighted agent
- **enter** Open agent details
"""
    BINDING_GROUP_TITLE = "Launcher"

    async def launch(self) -> None:
        if self.highlighted is None:
            return
        child = self.children[self.highlighted]
        assert isinstance(child, LauncherItem)
        self.app.session_navigation.events.publish(session_requests.LaunchAgent(child.agent.identity))


class NoAgents(widgets.Label):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.text_style = "dim italic"
        self.styles.padding = (1, 2)


class Launcher(containers.VerticalGroup, ToadNode):
    grid_select = getters.query_one(LauncherGridSelect)
    DIGITS = "123456789ABCDEF"

    def __init__(
        self,
        agents: dict[str, AgentDefinition],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self._agents = agents
        super().__init__(name=name, id=id, classes=classes)

    @property
    def highlighted(self) -> int | None:
        return self.grid_select.highlighted

    @highlighted.setter
    def highlighted(self, value: int) -> None:
        self.grid_select.highlighted = value

    def focus(self, scroll_visible: bool = True) -> Self:
        try:
            self.grid_select.focus(scroll_visible=scroll_visible)
        except NoMatches:
            pass
        return self

    def compose(self) -> ComposeResult:
        launcher_agents = list(
            dict.fromkeys(
                identity
                for identity in self.app.settings.launcher.agents.splitlines()
                if identity.strip()
            )
        )
        agents = self._agents
        if launcher_agents:
            with LauncherGridSelect(min_column_width=32, max_column_width=32):
                for digit, identity in zip_longest(self.DIGITS, launcher_agents):
                    if identity is None:
                        break
                    if identity in agents:
                        yield LauncherItem(digit or "", agents[identity])

        if not launcher_agents:
            yield NoAgents("Choose your fighter below!")

    async def launch_highlighted(self) -> None:
        await self.grid_select.launch()


class LauncherDigit(RightPadding, AutoWidth, widgets.Digits):
    native_theme = (NativeDeclaration.of(Styles.color, TextVariable(SuccessColour.name)),)



class LauncherDescription(NoWrap, EllipsisOverflow, AgentDescription):
    """Its look is its bases."""


class LauncherItem(GridItem, containers.VerticalGroup):
    """An entry in the agent grid select."""

    def __init__(self, digit: str, agent: AgentDefinition) -> None:
        self._digit = digit
        self._agent = agent
        super().__init__()

    @property
    def agent(self) -> AgentDefinition:
        return self._agent

    def compose(self) -> ComposeResult:
        agent = self._agent
        with containers.HorizontalGroup():
            if self._digit:
                yield LauncherDigit(self._digit)
            with containers.VerticalGroup():
                yield widgets.Label(agent.name)
                yield AgentAuthor(agent.author_name)
                yield LauncherDescription(agent.description)


class AgentGridSelect(Launches, GridSelect, SideMargin):
    native_theme = (
        NativeDeclaration.of(
            Styles.border, Keyword("round"), Variable(SecondaryColour.name), Percent(50)
        ),
    )


    HELP = """\
## Agent select

- **cursor keys** Navigate agents
- **tab / shift+tab** Move to next / previous section
- **enter** Open agent details
- **space** Launch the agent (if installed)
"""
    BINDING_GROUP_TITLE = "Agent Select"

    async def launch(self) -> None:
        if self.highlighted is None:
            return
        child = self.children[self.highlighted]
        if not isinstance(child, AgentItem):
            self.app.open_url("https://github.com/sponsors/willmcgugan")
            return
        self.app.session_navigation.events.publish(session_requests.LaunchAgent(child.agent.identity))


class StoreFooterKey(ToadFooterKey):
    """The store's footer keys sit on the footer itself, without a key background."""

    native_components = {
        FooterKeyComponent.KEY: (NativeDeclaration.of(Styles.background, Keyword("transparent")),),
    }


class StoreFooter(ToadFooter, setting=ToadFooter.visibility_setting):
    key_type = StoreFooterKey


class StoreHeading(NoMargin, widgets.Static):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (1, 1, 0, 2)


class SponsorItem(GridCell, TransparentBackground, SidePadding, widgets.Static):
    native_theme = (NativeDeclaration.of(Styles.color, Keyword("auto"), Percent(70)), NativeDeclaration.of(Styles.border, Keyword("tall"), Keyword("blank")))



class TitleContainer(containers.VerticalGroup):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.align = ("center", "top")
        self.styles.dock = "top"


class TitleGrid(SideMargin, AutoHeight, containers.Grid):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("block"), Keyword("black"), Percent(20)),
        NativeDeclaration.of(Styles.background, Keyword("black"), Percent(20)),
    )

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.grid_size_columns = 2
        self.styles.grid_size_rows = 1
        self.styles.grid_columns = ("24", "1fr")
        self.styles.grid_rows = (AUTO,)
        self.styles.grid_gutter_horizontal = 1
        self.styles.grid_gutter_vertical = 2
        self.styles.min_width = 40


class Container(containers.VerticalScroll):
    BINDING_GROUP_TITLE = "View"
    native_theme = (
        NativeDeclaration.of(
            Styles.hatch, Keyword("right"), Variable(PrimaryColour.name), Percent(15)
        ),
    )

    def allow_focus(self) -> bool:
        """Only allow focus when we can scroll."""
        return super().allow_focus() and self.show_vertical_scrollbar


class LaunchSlotAction(WidgetAction):
    """Launch the agent occupying this numbered slot in the store."""

    keys = {EditingMode: tuple("123456789abcdef"), VimMode: tuple("123456789abcdeF")}

    def __init__(self, slot: int) -> None:
        self.slot = slot

    @classmethod
    def command_for_key(cls, mode: type[EditingMode], key: str) -> Self:
        return cls(cls.keys[mode].index(key))

    def key_identity(self) -> str:
        return f"{super().key_identity()}:{self.slot}"

    def key_title(self) -> str:
        return f"{self.title} {self.slot + 1}"

    @classmethod
    def offered(cls, store: StoreScreen) -> Iterator[Self]:
        return (cls(slot) for slot in range(len(cls.keys[EditingMode])))

    async def apply(self, store: StoreScreen) -> None:
        launcher = store.launcher
        if self.slot >= len(launcher.grid_select.children):
            store.notify(f"No agent in launch slot {self.slot + 1}",
                         title="Quick launch", severity="error")
            store.app.bell()
            return
        launcher.focus()
        launcher.highlighted = self.slot
        await launcher.launch_highlighted()


class StoreAction(WidgetAction, affix="Action"):
    """What the store does on its own keys."""


class ResumeAction(StoreAction):
    """Resume a previous session"""

    title = "Resume"
    keys = {EditingMode: ("ctrl+r",)}
    show = True

    def apply(self, context: StoreScreen) -> None:
        # Waiting on a dismissal needs a worker; the store owns its lifetime.
        context.run_worker(self.choose(context), group="resume", exclusive=True)

    async def choose(self, context: StoreScreen) -> None:
        from toad.screens.session_resume_modal import SessionResumeModal

        session = await context.app.push_screen_wait(SessionResumeModal())
        if session is not None:
            context.app.session_navigation.events.publish(
                session_requests.LaunchAgent(
                    session.agent_identity,
                    session.agent_session_id,
                    pk=session.id,
                )
            )


class FocusDirectoryAction(StoreAction):
    """Change project directory"""

    title = "Directory"
    keys = {EditingMode: ("ctrl+d",)}
    show = True

    async def apply(self, context: StoreScreen) -> None:
        if (directory_display := context.query_one_optional(DirectoryDisplay)) is not None:
            directory_display.focus()


class StoreScreen(ProfileKeys, CyclesFocus, CoreEventReceiver, Screen, ToadNode,
                  actions=(LaunchSlotAction, StoreAction)):
    BINDING_GROUP_TITLE = "Screen"

    launcher = getters.query_one(Launcher)
    container = getters.query_one(Container)


    def __init__(
        self):
        self._agents: dict[str, AgentDefinition] = {}
        super().__init__()

    @property
    def agents(self) -> dict[str, AgentDefinition]:
        return self._agents

    def compose(self) -> ComposeResult:
        with TitleContainer():
            with TitleGrid():
                yield Mandelbrot()
                yield widgets.Label(self.get_info())
        yield DirectoryDisplay()
        yield Container(can_focus=False)
        yield StoreFooter()

    def get_info(self) -> Content:
        toad_version = toad.get_version()
        version = pill(
            f"v{toad_version}",
            "$primary-muted",
            "$text-primary",
            filled=self.app.colours.ink.fills_pills,
        )
        content = Content.assemble(
            Content.from_markup("🐸 Toad"),
            version,
            ("\nThe universal interface for AI in your terminal", "$text-success"),
            (
                "\nSoftware lovingly crafted by hand (with a dash of AI) in Edinburgh, Scotland",
                "dim",
            ),
            "\n",
            (
                Content.from_markup(
                    "\nClick and hold to zoom the fractal, [b dim]ctrl+click[/] to zoom out."
                )
            ),
            "\n\n",
            (
                Content.from_markup(
                    "[dim]Code: [@click=app.open_url('https://github.com/batrachianai/toad')]Repository[/] • "
                    "Bugs: [@click=app.open_url('https://github.com/batrachianai/toad/discussions')]Discussions[/] • "
                    "Sponsor: [@click=app.open_url('https://github.com/sponsors/willmcgugan')]@willmcgugan[/]"
                )
            ),
        )

        return content

    def compose_agents(self) -> ComposeResult:
        agents = self._agents

        yield Launcher(agents)

        ordered_agents = sorted(
            agents.values(), key=lambda agent: agent.name.casefold()
        )

        recommended_agents = [
            agent for agent in ordered_agents if agent.recommended
        ]
        # Shuffle reccomended agents so none has priority
        shuffle(recommended_agents)
        if recommended_agents:
            with containers.VerticalGroup():
                yield StoreHeading(
                    "[$text-warning u]Recommended[/] [$text-secondary 100% i]Best of the bunch",
                )
                with AgentGridSelect(min_column_width=40):
                    for agent in recommended_agents:
                        yield AgentItem(agent)
                    yield SponsorItem(
                        "[$text-warning]Your agent here[/] — support development of Toad by [@click=app.open_url('https://github.com/sponsors/willmcgugan')]sponsoring[/] this project",
                    )

        from toad.agent_schema import AgentKind
        for section in dict.fromkeys(kind.section() for kind in AgentKind.members_with(AgentKind)):
            section_agents = [agent for agent in ordered_agents if agent.kind.section() is section]
            if not section_agents:
                continue
            yield StoreHeading(
                f'[$text-warning u]{section.heading}[/] [$text-secondary i]{section.description}',
            )
            with containers.VerticalGroup():
                with AgentGridSelect(min_column_width=40):
                    for agent in section_agents:
                        yield AgentItem(agent)

    def move_focus(self, direction: Literal[-1] | Literal[+1]) -> None:
        if isinstance(self.focused, GridSelect):
            focus_chain = list(self.query(GridSelect))
            if self.focused in focus_chain:
                index = focus_chain.index(self.focused)
                new_focus = focus_chain[(index + direction) % len(focus_chain)]
                if direction == -1:
                    new_focus.highlight_last()
                else:
                    new_focus.highlight_first()
                new_focus.focus(scroll_visible=False)

    @on(GridSelect.LeaveUp)
    def on_grid_select_leave_up(self, event: GridSelect.LeaveUp):
        event.stop()
        self.move_focus(-1)

    @on(GridSelect.LeaveDown)
    def on_grid_select_leave_down(self, event: GridSelect.LeaveUp):
        event.stop()
        self.move_focus(+1)

    @on(GridSelect.Selected, "AgentGridSelect")
    @work
    async def on_grid_select_selected(self, event: GridSelect.Selected):
        if not isinstance(event.widget, AgentItem):
            self.app.open_url("https://github.com/sponsors/willmcgugan")
            return
        assert isinstance(event.widget, AgentItem)
        await self.show_agent(event.widget.agent)

    @on(GridSelect.Selected, "LauncherGridSelect")
    @work
    async def on_launcher_selected(self, event: GridSelect.Selected):
        launcher_item = event.widget
        assert isinstance(launcher_item, LauncherItem)

        await self.show_agent(launcher_item.agent)

    async def show_agent(self, agent: AgentDefinition) -> None:
        from toad.screens.agent_modal import AgentModal

        modal_response = await self.app.push_screen_wait(AgentModal(agent))
        await self.app.saved_settings.save()
        if modal_response is not None:
            self.app.session_navigation.events.publish(modal_response)

    @work
    async def on_mount(self) -> None:
        self.observe_core(self.app.saved_settings.events)
        try:
            self._agents = await read_agents()
        except AgentReadError as error:
            self.app.show_error(error, "Failed to read agents data")
        else:
            await self.container.mount_compose(self.compose_agents())
            with suppress(NoMatches):
                first_grid = self.container.query(GridSelect).first()
                first_grid.focus(scroll_visible=False)

    @handles(PreferenceChanged)
    async def _preferences_changed(self, event: PreferenceChanged) -> None:
        if SETTINGS.launcher.agents.matches(event.field):
            await self.launcher.recompose()

            def focus_screen():
                self.screen.query(GridSelect).focus()

            self.call_later(focus_screen)
