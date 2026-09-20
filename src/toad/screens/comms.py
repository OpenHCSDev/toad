from pathlib import Path

from textual import containers, getters, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import ScreenResume
from textual.screen import Screen
from textual.widgets import Footer

from toad import messages
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_fork_dialog import ForkDialog
from toad.widgets.comms_sidebar import CoordinationStatus, CommsSidebar, SelectTarget
from toad.widgets.session_tabs import SessionsTabs
from toad.widgets.side_bar import SideBar


class CommsScreen(Screen, can_focus=False):
    """A channel or DM represented as a native concurrent Toad session."""

    AUTO_FOCUS = "CommsChatView Prompt TextArea"
    CSS_PATH = ["main.tcss", "comms.tcss"]
    SESSION_NAVIGATION_GROUP = Binding.Group(description="Sessions")
    BINDINGS = [
        Binding("escape", "back_to_agent", "Agent session", priority=True),
        Binding("ctrl+g", "toggle_irc", "IRC view"),
        Binding("ctrl+j", "toggle_dm", "DM view"),
        Binding("ctrl+w", "close_session", "Close session", priority=True),
        Binding(
            "ctrl+left_square_bracket",
            "session_previous",
            "Previous session",
            group=SESSION_NAVIGATION_GROUP,
        ),
        Binding(
            "ctrl+right_square_bracket",
            "session_next",
            "Next session",
            group=SESSION_NAVIGATION_GROUP,
        ),
    ]

    def __init__(
        self,
        *,
        project_path: Path,
        owner_mode: str,
        me: str,
        target: str,
        kind: str,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.owner_mode = owner_mode
        self.me = me
        self.target = target
        self.kind = kind

    app = getters.app(ToadApp)

    def compose(self) -> ComposeResult:
        with containers.Center():
            yield SideBar(
                SideBar.Panel(
                    "Sessions",
                    CommsSidebar(session_thread=self.me),
                    flex=True,
                ),
                SideBar.Panel(
                    "Coordination",
                    CoordinationStatus(self.me),
                    id="coordination-panel",
                ),
            )
            with containers.Vertical(id="comms-content"):
                yield SessionsTabs()
                yield CommsChatView(
                    self.project_path,
                    me=self.me,
                    target=self.target,
                    kind=self.kind,
                )
        yield Footer()

    def on_mount(self) -> None:
        chat = self.query_one(CommsChatView)
        chat.prepare_prompt()
        self.set_timer(0.1, chat.prepare_prompt)

    def _on_screen_resume(self, event: ScreenResume) -> None:
        self.call_after_refresh(self.query_one(CommsSidebar).sync_sessions)
        chat = self.query_one(CommsChatView)
        self.call_after_refresh(chat.prepare_prompt)
        self.set_timer(0.1, chat.prepare_prompt)

    def action_focus_prompt(self) -> None:
        self.query_one(CommsChatView).prepare_prompt()

    async def _open(self, target: str, kind: str) -> None:
        await self.app.open_comms_session(
            owner_mode=self.owner_mode,
            project_path=self.project_path,
            me=self.me,
            target=target,
            kind=kind,
        )

    @on(SelectTarget)
    async def on_select_target(self, event: SelectTarget) -> None:
        if event.kind == "session":
            await self.action_back_to_agent()
        else:
            await self._open(event.target, event.kind)

    async def action_back_to_agent(self) -> None:
        if self.app.session_tracker.get_session(self.owner_mode) is None:
            await self.app.switch_mode("store")
        else:
            await self.app.switch_mode(self.owner_mode)

    async def action_toggle_irc(self) -> None:
        if self.kind == "irc":
            await self.action_back_to_agent()
        else:
            await self._open("#all", "irc")

    async def action_toggle_dm(self) -> None:
        if self.kind == "dm":
            await self.action_back_to_agent()
            return
        sidebar = self.query_one(CommsSidebar)
        peers = [
            name for name in sorted(sidebar._comms_registry_names()) if name != self.me
        ]
        if peers:
            await self._open(peers[0], "dm")

    def action_session_previous(self) -> None:
        if self.id is not None:
            self.post_message(messages.SessionNavigate(self.id, -1))

    def action_session_next(self) -> None:
        if self.id is not None:
            self.post_message(messages.SessionNavigate(self.id, +1))

    async def action_close_session(self) -> None:
        if self.id is not None:
            await self.app.close_session_mode(self.id)

    @on(CommsSidebar.ThreadAction)
    async def on_thread_action(self, event: CommsSidebar.ThreadAction) -> None:
        if event.action != "fork":
            return
        parent = event.name

        def do_fork(spec: tuple[str, str] | None) -> None:
            if not spec:
                return
            import os

            from agent_comms.operations import ForkSpec, wire

            root = os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")
            try:
                wire(root).fork(ForkSpec(name=spec[0], parent=parent, task=spec[1]))
                self.notify(f"forked {spec[0]} from {parent}", title="Comms")
            except Exception as error:
                self.notify(str(error), title="Comms fork failed", severity="error")

        self.app.push_screen(ForkDialog(parent), do_fork)
