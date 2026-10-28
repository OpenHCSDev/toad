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

from textual.binding import ModeBinding
from toad.widget_actions import DismissibleControl, CyclesFocus, Launches, WidgetAction, ProfileKeys
from textual.document._editing import EditingMode
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
from toad.widgets.footer import ToadFooter

import toad
from toad.app import ToadApp
from toad.format_path import format_path
from agent_comms.repo import Checkout
from toad.pill import pill
from toad.widgets.directory_input import DirectoryInput
from toad.widgets.mandelbrot import Mandelbrot
from toad.widgets.condensed_path import CondensedPath
from toad.widgets.grid_select import GridSelect
from toad.agent_schema import AgentDefinition
from toad.agents import AgentReadError, read_agents


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


class DirectoryDisplay(DismissibleControl, CoreEventReceiver, containers.HorizontalGroup):


    DEFAULT_CSS = """
    DirectoryDisplay {
        CondensedPath { display: block; }
        DirectoryInput { display: none; }
        &.-edit {
            CondensedPath { display: none}
            DirectoryInput { display: block; }
        }
    }
    """

    path = reactive("")
    edit = reactive(False, toggle_class="-edit")

    directory_input = getters.query_one(DirectoryInput)
    condensed_path = getters.query_one(CondensedPath)

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
        if not edit and self.directory_input.has_focus:
            self.directory_input.blur()

    def compose(self) -> ComposeResult:
        yield widgets.Label("📁 ")
        yield CondensedPath(self.path, directory=True).data_bind(
            path=DirectoryDisplay.path
        ).with_tooltip("Project directory for new agent sessions (click to edit)")
        yield DirectoryInput(self.path, select_on_focus=True, compact=True).data_bind(
            value=DirectoryDisplay.path
        )


class AgentItem(containers.VerticalGroup):
    """An entry in the agent grid select."""

    def __init__(self, agent: AgentDefinition) -> None:
        self._agent = agent
        super().__init__()

    @property
    def agent(self) -> AgentDefinition:
        return self._agent

    def compose(self) -> ComposeResult:
        agent = self._agent
        with containers.Grid():
            yield widgets.Label(agent.name, id="name")
            tag = pill(
                agent.kind.heading,
                "$primary-muted 50%",
                "$text-primary",
                filled=not self.app.native_ansi_color,
            )
            yield widgets.Label(tag, id="type")
        yield widgets.Label(agent.author_name, id="author")
        yield widgets.Static(agent.description, id="description")


class LauncherGridSelect(Launches, CoreEventReceiver, GridSelect):

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

    app = getters.app(ToadApp)

    def action_details(self) -> None:
        if self.highlighted is None:
            return
        agent_item = self.children[self.highlighted]
        assert isinstance(agent_item, LauncherItem)
        self.publish_core(input_events.OpenAgentDetails(agent_item._agent.identity))

    def action_remove(self) -> None:
        agents = self.app.settings.launcher.agents.splitlines()
        if self.highlighted is None:
            return
        try:
            del agents[self.highlighted]
        except IndexError:
            pass
        else:
            self.app.saved_settings.set(SETTINGS.launcher.agents, "\n".join(agents))

    async def launch(self) -> None:
        if self.highlighted is None:
            return
        child = self.children[self.highlighted]
        assert isinstance(child, LauncherItem)
        self.app.session_navigation.events.publish(session_requests.LaunchAgent(child.agent.identity))


class Launcher(containers.VerticalGroup):
    app = getters.app(ToadApp)
    grid_select = getters.query_one("#launcher-grid-select", LauncherGridSelect)
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
        self.set_class(not launcher_agents, "-empty")
        if launcher_agents:
            with LauncherGridSelect(
                id="launcher-grid-select", min_column_width=32, max_column_width=32
            ):
                for digit, identity in zip_longest(self.DIGITS, launcher_agents):
                    if identity is None:
                        break
                    if identity in agents:
                        yield LauncherItem(digit or "", agents[identity])

        if not launcher_agents:
            yield widgets.Label("Choose your fighter below!", classes="no-agents")

    async def launch_highlighted(self) -> None:
        await self.grid_select.launch()


class LauncherItem(containers.VerticalGroup):
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
                yield widgets.Digits(self._digit)
            with containers.VerticalGroup():
                yield widgets.Label(agent.name, id="name")
                yield widgets.Label(agent.author_name, id="author")
                yield widgets.Static(agent.description, id="description")


class AgentGridSelect(Launches, GridSelect):
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


class Container(containers.VerticalScroll):
    BINDING_GROUP_TITLE = "View"

    def allow_focus(self) -> bool:
        """Only allow focus when we can scroll."""
        return super().allow_focus() and self.show_vertical_scrollbar


class LaunchSlotAction(WidgetAction):
    """Launch the agent occupying this numbered slot in the store."""

    keys = {EditingMode: tuple("123456789abcdef")}

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


class StoreScreen(ProfileKeys, CyclesFocus, CoreEventReceiver, Screen, actions=(LaunchSlotAction,)):
    BINDING_GROUP_TITLE = "Screen"
    CSS_PATH = "store.tcss"

    agents_view = getters.query_one("#agents-view", AgentGridSelect)
    launcher = getters.query_one("#launcher", Launcher)
    container = getters.query_one("#container", Container)

    app = getters.app(ToadApp)

    def __init__(
        self, name: str | None = None, id: str | None = None, classes: str | None = None
    ):
        self._agents: dict[str, AgentDefinition] = {}
        super().__init__(name=name, id=id, classes=classes)

    @property
    def agents(self) -> dict[str, AgentDefinition]:
        return self._agents

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup(id="title-container"):
            with containers.Grid(id="title-grid"):
                yield Mandelbrot()
                yield widgets.Label(self.get_info(), id="info")
        yield DirectoryDisplay()
        yield Container(id="container", can_focus=False)
        yield ToadFooter()

    def get_info(self) -> Content:
        toad_version = toad.get_version()
        version = pill(
            f"v{toad_version}",
            "$primary-muted",
            "$text-primary",
            filled=not self.app.native_ansi_color,
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
                    "[dim]Code: [@click=screen.url('https://github.com/batrachianai/toad')]Repository[/] • "
                    "Bugs: [@click=screen.url('https://github.com/batrachianai/toad/discussions')]Discussions[/] • "
                    "Sponsor: [@click=screen.url('https://github.com/sponsors/willmcgugan')]@willmcgugan[/]"
                )
            ),
        )

        return content

    def action_url(self, url: str) -> None:
        import webbrowser

        webbrowser.open(url)

    def compose_agents(self) -> ComposeResult:
        agents = self._agents

        yield Launcher(agents, id="launcher")

        ordered_agents = sorted(
            agents.values(), key=lambda agent: agent.name.casefold()
        )

        recommended_agents = [
            agent for agent in ordered_agents if agent.recommended
        ]
        # Shuffle reccomended agents so none has priority
        shuffle(recommended_agents)
        if recommended_agents:
            with containers.VerticalGroup(id="sponsored-agents", classes="recommended"):
                yield widgets.Static(
                    "[$text-warning u]Recommended[/] [$text-secondary 100% i]Best of the bunch",
                    classes="heading",
                )
                with AgentGridSelect(classes="agents-picker", min_column_width=40):
                    for agent in recommended_agents:
                        yield AgentItem(agent)
                    yield widgets.Static(
                        "[$text-warning]Your agent here[/] — support development of Toad by [@click=screen.url('https://github.com/sponsors/willmcgugan')]sponsoring[/] this project",
                        classes="sponsor-me",
                    )

        from toad.agent_schema import AgentKind
        for section in dict.fromkeys(kind.section() for kind in AgentKind.members_with(AgentKind)):
            section_agents = [agent for agent in ordered_agents if agent.kind.section() is section]
            if not section_agents:
                continue
            yield widgets.Static(
                f'[$text-warning u]{section.heading}[/] [$text-secondary i]{section.description}',
                classes='heading',
            )
            with containers.VerticalGroup():
                with AgentGridSelect(classes='agents-picker', min_column_width=40):
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

    @on(GridSelect.Selected, ".agents-picker")
    @work
    async def on_grid_select_selected(self, event: GridSelect.Selected):
        if not isinstance(event.widget, AgentItem):
            self.app.open_url("https://github.com/sponsors/willmcgugan")
            return
        assert isinstance(event.widget, AgentItem)
        await self.show_agent(event.widget.agent)

    @handles(input_events.OpenAgentDetails)
    @work
    async def open_agent_detail(self, event: input_events.OpenAgentDetails) -> None:
        try:
            agent = self._agents[event.identity]
        except KeyError:
            return
        await self.show_agent(agent)

    @on(GridSelect.Selected, "#launcher GridSelect")
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
            self.app.show_error(f"Failed to read agents data ({error})", "Agents data")
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

    @work
    async def resume(self) -> None:
        from toad.screens.session_resume_modal import SessionResumeModal

        session = await self.app.push_screen_wait(SessionResumeModal())
        if session is not None:
            self.app.session_navigation.events.publish(
                session_requests.LaunchAgent(
                    session.agent_identity,
                    session.agent_session_id,
                    pk=session.id,
                )
            )

    async def focus_directory(self) -> None:
        if (directory_display := self.query_one_optional(DirectoryDisplay)) is not None:
            directory_display.focus()

    MODE_BINDINGS = (
        ModeBinding("ctrl+r", resume, "Resume", mode=EditingMode,
                    tooltip="Resume a previous session"),
        ModeBinding("ctrl+d", focus_directory, "Directory", mode=EditingMode,
                    tooltip="Change project directory"),
    )
