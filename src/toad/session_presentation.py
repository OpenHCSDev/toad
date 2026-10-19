"""Session-owned mounted presentation, with one bounded workspace owner."""

import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from toad.resource_release import AsyncResourceRelease
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import ref

from textual.widget import Widget
from textual.widgets.text_area import TextAreaState

from agent_comms.acp_extension import CoordinationChangedUpdate
from agent_comms.session_load import EnsuringSessionLoadPlan
from toad.owner_preparation import ExistingOwnerPlan
from toad.acp.agent_session import SessionDisposition

from toad.input_history import InputHistories
from toad.agent_surface import AttachedSurfaceBinding
from toad.agent_binding import NoAgentBound
from toad.widgets.conversation import Conversation
from toad.widgets.history_anchor import ParkedPosition
from toad.widgets.message_filter import MessageCategory

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.screens.main import MainScreen


class SessionSurfaceSlot(Widget):
    """The session's stable placement for its accepted native presentation."""

    DEFAULT_CSS = "SessionSurfaceSlot { display: none; }"


@dataclass(frozen=True)
class SessionViewState:
    """The actual editor document/history and reader intent, not a transcript copy."""

    editor: TextAreaState
    visible_categories: frozenset[type[MessageCategory]]
    reader_position: ParkedPosition
    shell_mode: bool
    input_histories: InputHistories
    initial_prompt: str | None

    @classmethod
    def capture(cls, conversation: Conversation) -> "SessionViewState":
        editor = conversation.prompt.prompt_text_area
        return cls(
            editor.capture_editor_state(), conversation.visible_categories,
            conversation.window.park_reader(conversation.contents),
            editor.shell_mode, conversation.input_histories, conversation.take_initial_prompt(),
        )

    def prepare_transcript(self, conversation: Conversation) -> None:
        conversation.visible_categories = self.visible_categories
        conversation.window.reader_position = self.reader_position

    def restore(self, conversation: Conversation) -> None:
        conversation.input_histories = self.input_histories
        editor = conversation.prompt.prompt_text_area
        editor.restore_editor_state(self.editor)
        editor.shell_mode = self.shell_mode


class SessionSurfaceLifetime(ABC):
    """A session declares its own UI placement and activation lifetime."""

    @property
    def operational_binding(self):
        return NoAgentBound()

    @abstractmethod
    def compose_content(self, screen: "MainScreen") -> Widget: ...

    @abstractmethod
    async def prepare(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def retire(self, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def close(self, screen: "MainScreen") -> None: ...


class EditorSessionSurfaceLifetime(SessionSurfaceLifetime):
    """Own retained editor state and active shell close semantics."""

    def __init__(self) -> None:
        self.state: SessionViewState | None = None

    @abstractmethod
    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None: ...

    @abstractmethod
    async def attach_binding(self, conversation: Conversation) -> None: ...



class OperationalSessionSources:
    """Own existing operational resources while the view is detached."""

    def __init__(self) -> None:
        self.agent_binding = NoAgentBound()
        self.shell = None
        self.load_plan = EnsuringSessionLoadPlan()

    def status_row(self, conversation: Conversation):
        row = self.activity_row(conversation).with_delivery(conversation.input_delivery)
        return conversation.agent_binding.session_disposition.present(row, row.disconnected)

    def activity_row(self, conversation: Conversation):
        # A Core history source owns status even when its ACP load fails.
        if conversation.transcript.readable:
            return conversation.thread_activity.row
        return conversation.turns.binding.status_row(conversation.thread_activity.row)

    def agent_info(self, conversation: Conversation) -> str:
        return "shell"

    def make_conversation(self, screen: "MainScreen") -> Conversation:
        return Conversation(
            screen.project_path, screen._agent, screen._agent_session_id,
            screen._session_pk, screen.app.session_tracker.sessions[screen.id].initial_title,
            initial_prompt=screen._initial_prompt,
            transcript=screen.presentation.transcript,
        )

    def external_transcript_changed(self, conversation: Conversation) -> None:
        """Native sessions receive their text through their own ACP stream."""

    def prompt(self, conversation: Conversation):
        from toad.widgets.prompt import Prompt

        return Prompt(turns=conversation.turns, submissions=conversation.submissions)

    async def submit(self, owner, event):
        from toad.conversation_submission import InputSubmission

        return await InputSubmission.from_event(event, owner.view).execute(owner)

    def input_ready(self, conversation: Conversation) -> bool:
        agent = conversation.agent_binding
        if not agent.ready:
            return False
        if agent.configuration.model.requires_selection:
            return False
        if conversation.transcript.readable:
            presentation = conversation.thread_presentation
            return (presentation is not None
                    and ExistingOwnerPlan.from_binding(presentation.binding) is not None)
        return True

    def unavailable_reason(self, conversation: Conversation) -> str:
        presentation = conversation.thread_presentation
        agent = conversation.agent_binding
        if (conversation.transcript.readable and presentation is not None
                and ExistingOwnerPlan.from_binding(presentation.binding) is None):
            line = "Thread is stopped. Choose Start thread from its menu; your draft is kept."
        elif agent.configuration.model.requires_selection:
            line = "Choose a model or connect a provider (click here). Your draft is kept."
        else:
            line = self.activity_row(conversation).presentation.summary
        return self.activity_row(conversation).status.with_disconnection(
            line, lambda: agent.session_disposition.present(line, lambda status: status.notice))

    def start_agent(self, conversation: Conversation) -> None:
        conversation.agent_binding.start_agent(self, conversation)

    def create_agent(self, conversation: Conversation) -> None:
        """The unbound state requests a new operational connection."""
        from toad.acp.agent import Agent
        from toad.core import events as core_events

        assert conversation._agent_data is not None
        agent = Agent(conversation.project_path, conversation._agent_data,
                      conversation._agent_session_id, conversation._session_pk,
                      app_events=conversation.app.events,
                      transcripts=conversation.app.coordination_access.transcripts)
        agent.session.load_plan = self.load_plan
        conversation._native_agent_started_here = True
        conversation.bind_agent(agent)
        agent.controller.start_operation(agent.start(conversation.app.session_navigation.processes))
        conversation.publish_core(core_events.SessionSubtitleChanged(conversation.agent_title))

    def attach_started(self, screen: "MainScreen", plan) -> None:
        """An explicit Start action may attach the same retained view to its new owner."""
        self.load_plan = plan
        screen._agent = screen._agent or screen.app.agent_data
        conversation = screen.presentation.widget
        if conversation is not None:
            conversation._agent_data = screen._agent
            if screen.is_current:
                conversation.start_native_session()

    def wire(self, conversation: Conversation) -> None:
        """The view borrows its agent during present, through bind_agent."""

    async def present(self, conversation: Conversation) -> None:
        shell, self.shell = self.shell, None
        if shell is not None:
            conversation._shell = shell
            await shell.attach(AttachedSurfaceBinding(conversation, shell.events))
        conversation.bind_agent(self.agent_binding)

    async def detach(self, conversation: Conversation, screen: "MainScreen") -> None:
        self.agent_binding = conversation.agent_binding
        self.shell = conversation._shell
        conversation._shell = None
        if self.shell is not None:
            await self.shell.detach()
        self.agent_binding.detach_surface(conversation)

    async def close(self) -> None:
        agent, self.agent_binding = self.agent_binding, NoAgentBound()
        shell, self.shell = self.shell, None
        async with AsyncResourceRelease() as release:
            if shell is not None:
                release.push_async_callback(shell.close)
            release.push_async_callback(agent.stop)


class MailboxSessionSources(OperationalSessionSources):
    """CLI execution receives user messages through Core's inbox, not ACP."""

    def activity_row(self, conversation: Conversation):
        return conversation.thread_activity.row

    def agent_info(self, conversation: Conversation) -> str:
        return conversation.thread_activity.row.presentation.title

    def prompt(self, conversation: Conversation):
        from toad.conversation_kind import DmConversation

        root, name = conversation.transcript_scope()
        return DmConversation.prompt(name)

    def input_ready(self, conversation: Conversation) -> bool:
        return conversation.transcript.readable

    def external_transcript_changed(self, conversation: Conversation) -> None:
        from toad.transcript_publication import CanonicalSourcePublication

        conversation.transcript.source_requests.request(CanonicalSourcePublication)

    async def present(self, conversation: Conversation) -> None:
        await super().present(conversation)
        self.external_transcript_changed(conversation)

    async def submit(self, owner, event):
        from toad.conversation_kind import DmConversation

        view = owner.view
        scope = view.transcript.binding.thread_scope
        if scope is None:
            view.delivery_refused("CLI transcript is not ready", event.body)
            return
        root, target = scope

        async def presented(sent):
            view.run_worker(view.input_histories.prompt.record(event.body), group="history")
            view.window.jump_to_latest()
            self.external_transcript_changed(view)

        await view.submit_comms_message(
            root, DmConversation, target, event.body,
            lambda: view.is_attached and view.transcript.binding.thread_scope == scope,
            presented,
        )


class OperationalSessionPresentation(EditorSessionSurfaceLifetime):
    """Own the editor and logical transcript independently of native membership."""

    def __init__(self) -> None:
        super().__init__()
        from toad.transcript_publication import SessionTranscriptPresentation

        self.transcript = SessionTranscriptPresentation()
        self.sources = OperationalSessionSources()
        self.widget: Conversation | None = None

    @property
    def operational_binding(self):
        return self.widget.agent_binding if self.widget is not None else self.sources.agent_binding

    @property
    def retained_widget_count(self) -> int:
        """The retained native view includes its complete widget tree."""
        return 1 + self.widget.descendant_count if self.widget is not None else 0

    @property
    def retained_source_bytes(self) -> int:
        return self.transcript.retained_source_bytes

    @property
    def retained_paint_bytes(self) -> int:
        # Drawn history rows: about one cell of text and style per column.
        if self.widget is None:
            return 0
        return sum(page.line_count * page.line_width * 8
                   for history in self.widget.window.histories for page in history.pages)

    def compose_content(self, screen: "MainScreen") -> Widget:
        return SessionSurfaceSlot()

    async def prepare(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.activate(screen)

    async def retire(self, screen: "MainScreen") -> None:
        await screen.app.workspace_chrome.native.retire(screen)

    async def release_binding(self, conversation: Conversation, screen: "MainScreen") -> None:
        await self.sources.detach(conversation, screen)

    async def attach_binding(self, conversation: Conversation) -> None:
        await self.sources.present(conversation)

    async def apply_coordination(self, screen: "MainScreen", event: CoordinationChangedUpdate) -> None:
        """Apply a coordination update's view work to this session's conversation.

        The workspace accepts one session's native tree at a time, so the
        widget may be parked or not yet built. Its work waits for mounting,
        which applies the screen's retained fact.
        """
        conversation = self.widget
        if conversation is None:
            return
        if event.worktree is not None and (project := Path(event.worktree)) != conversation.project_path:
            await conversation.sync_project_path(project)
        conversation.input_histories.bind_scope(f"thread:{event.thread.name}")

    @asynccontextmanager
    async def acquire(self, screen: "MainScreen"):
        """Mount owned resources before the workspace opens the view, then restore them.

        The workspace accepts the yielded native tree before operational
        attachment can await or publish its restored presentation.
        """
        conversation = self.widget
        returning = conversation is not None
        if conversation is None:
            slot = screen.query_one(SessionSurfaceSlot)
            content = slot.parent
            assert isinstance(content, Widget)
            with screen._context():
                conversation = self.sources.make_conversation(screen)
            self.widget = conversation
            screen._initial_prompt = None
            conversation.display = False
        self.sources.wire(conversation)
        if not returning:
            if self.state is not None:
                conversation._initial_prompt = self.state.initial_prompt
            await content.mount(conversation, before=slot)
            screen.thread_identity.bind_history(conversation.input_histories)
        yield conversation
        if self.state is not None:
            self.state.prepare_transcript(conversation)
        await self.transcript.bind(conversation).restore_documents(self.transcript)
        if self.state is not None:
            self.state.restore(conversation)
            self.state = None
        await self.attach_binding(conversation)
        await self.transcript.bind(conversation).restore(self.transcript)
        conversation.display = True
        if returning:
            conversation.start_native_session()
        conversation.prompt.focus()

    async def close(self, screen: "MainScreen") -> None:
        self.state = None
        async with AsyncResourceRelease() as release:
            release.push_async_callback(self.sources.close)
            release.push_async_callback(self.transcript.close)
            await screen.app.workspace_chrome.native.dispose(screen)

    async def evict(self) -> None:
        """Release the owned native tree while retaining its actual editor resource."""
        if (conversation := self.widget) is None:
            return
        self.state = SessionViewState.capture(conversation)
        await self.remove_native_tree()

    def external_transcript_changed(self) -> None:
        """Refresh the owned CLI view; an unbuilt view reads its source on attach."""
        if self.widget is not None:
            self.sources.external_transcript_changed(self.widget)

    async def remove_native_tree(self) -> None:
        if (conversation := self.widget) is None:
            return
        self.widget = None
        async with AsyncResourceRelease() as release:
            release.push_async_callback(conversation.remove)
            await conversation.release_native_session()


class NativeSessionSurface:
    """Accept session-owned trees without moving their ancestry or copying their state."""

    def __init__(self, app: "ToadApp") -> None:
        self._app = ref(app)
        self.view: MainScreen | None = None
        self._lock = asyncio.Lock()

    @property
    def widget(self) -> Conversation | None:
        return self.view.presentation.widget if self.view is not None else None

    def _presentations(self):
        app = self._app()
        return tuple(presentation for view in app.workspace_sessions.views.values()
                     for presentation in view.retained_native_presentations())

    async def retire(self, screen: "MainScreen") -> None:
        async with self._lock:
            if self.view is not screen or self.widget is None:
                return
            conversation = self.widget
            await conversation.transcript.suspend()
            for history in tuple(conversation.window.histories):
                await history.retire_source(parked=True)
            await screen.presentation.release_binding(conversation, screen)
            conversation.display = False
            self.view = None

    async def activate(self, screen: "MainScreen") -> None:
        async with self._lock:
            if self.view is screen:
                return
            assert self.view is None, "Departing source must retire before accepting the next source"
            async with screen.presentation.acquire(screen) as conversation:
                self.view = screen
            await self._trim_retained(conversation)

    async def reconcile(self, screen: "MainScreen") -> None:
        """Completed rich-panel hydration changes the same native working set."""
        async with self._lock:
            if self.view is screen and self.widget is not None:
                await self._trim_retained(self.widget)

    async def _trim_retained(self, selected: Conversation) -> None:
        """Bound inactive native trees using the existing viewport resource policy.

        The selected presentation is required; its costs participate in the
        same resource limits as inactive trees. Tab order owns recency and the logical
        session registry owns native membership. Eviction preserves source and
        editor/reader state through the presentation's existing lifetime.
        """
        app = self._app()
        budget = selected.window.presentation_budget
        candidates = {}
        for screen, owner in self._presentations():
            candidates.setdefault(screen.id, []).append(owner)
        required = (self.view.presentation, *(
            owner for owner in candidates.get(self.view.id, ())
            if owner is not self.view.presentation))
        ordered = dict.fromkeys((*required, *(
            owner for identity in app.tab_order.recent
            for owner in candidates.get(identity, ()))))
        kept = budget.fit(
            ordered, required, app.size.height, app.preparation.max_bytes,
        )
        for owner in ordered:
            if owner not in kept:
                await owner.evict()

    async def dispose(self, screen: "MainScreen") -> None:
        """Finalize a live tree before pruning; a closed tab retains no editor."""
        async with self._lock:
            owner = screen.presentation
            async with AsyncResourceRelease() as release:
                release.push_async_callback(owner.remove_native_tree)
                if self.view is screen:
                    self.view = None
                    await owner.release_binding(owner.widget, screen)

    async def close(self) -> None:
        async with self._lock:
            if self.view is not None:
                await self.view.presentation.release_binding(self.widget, self.view)
            self.view = None
