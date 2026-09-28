"""Thread menu declarations own presentation, input collection and execution."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

from agent_comms.command import Command
from agent_comms.comms import Comms
from agent_comms.declared_family import DeclaredFamily
from agent_comms.owner_lifecycle import OwnerStartResult
from agent_comms.thread_management import ForkSpec
from agent_comms.thread_status import ThreadStatus
from agent_comms.threads import Thread
from agent_comms.tools import (
    CommsAckTool,
    CommsArchiveTool,
    CommsForkTool,
    CommsStartTool,
    CommsStopTool,
    ToolRequest,
)

if TYPE_CHECKING:
    from toad.app import ToadApp

Result = TypeVar("Result")


@dataclass(frozen=True)
class ThreadActionContext:
    comms: Comms
    subject: str
    actor: str
    project: Path
    session_modes: tuple[str, ...]


class ChannelAction:
    """A thread action whose declared scope also includes channel views."""


class ThreadAction(DeclaredFamily, Command, Generic[Result], affix="Action"):
    """One UI command; actual domain owners enforce all mutation authority."""

    tool: ClassVar[type[ToolRequest]]
    pending: ClassVar[str]

    @classmethod
    def menu_label(cls) -> str:
        return cls.tool.action_label or cls.tool.label

    @classmethod
    def available(cls, status: ThreadStatus, owner_pid: int) -> bool:
        return status.allows_control(cls.tool.declared_name, owner_pid=owner_pid)

    @classmethod
    def menu(cls) -> tuple[type[ThreadAction], ...]:
        return tuple(sorted(cls.members_with(cls), key=lambda action: action.tool.action_order))

    @classmethod
    def request(
        cls, app: ToadApp, subject: str, actor: str, session_modes: tuple[str, ...] = ()
    ) -> None:
        app.invoke_thread_action(cls(), subject, actor, session_modes)

    @abstractmethod
    def apply(self, ctx: ThreadActionContext) -> Result:
        """Perform this command on the worker thread within route admission."""

    @abstractmethod
    async def completed(self, app: ToadApp, ctx: ThreadActionContext, result: Result) -> None:
        """Present the typed result on the UI loop."""


class StartAction(ThreadAction[OwnerStartResult]):
    tool = CommsStartTool
    pending = "Starting…"

    def apply(self, ctx: ThreadActionContext) -> OwnerStartResult:
        return ctx.comms.owners.start(ctx.subject)

    async def completed(self, app: ToadApp, ctx: ThreadActionContext, result: OwnerStartResult) -> None:
        app.notify(
            f"{'Starting' if result.launched else 'Already running'} @{result.thread}",
            title="Session action",
        )
        if result.launched:
            from toad.acp.messages import CommsUpdated
            from agent_comms.acp_extension import TranscriptChangedUpdate

            for mode_name in ctx.session_modes:
                screen = app._main_session_screen(mode_name)
                if screen is not None and screen.conversation.agent is not None:
                    await screen.conversation.agent.reconnect()
                    agent = screen.conversation.agent
                    screen.conversation.post_message(CommsUpdated(TranscriptChangedUpdate(None), agent, agent.session_id))


class FinishedAction(ThreadAction[None]):
    """Shared notification for commands without a domain return value."""

    completed_label: ClassVar[str]

    async def completed(self, app: ToadApp, ctx: ThreadActionContext, result: None) -> None:
        app.notify(f"{self.completed_label} @{ctx.subject}", title="Session action")


class StopAction(FinishedAction):
    tool = CommsStopTool
    pending = "Stopping…"
    completed_label = "Stopped"

    def apply(self, ctx: ThreadActionContext) -> None:
        ctx.comms.owners.stop(ctx.subject)


class ArchiveAction(FinishedAction):
    tool = CommsArchiveTool
    pending = "Archiving…"
    completed_label = "Archived"

    def apply(self, ctx: ThreadActionContext) -> None:
        ctx.comms.threads.archive(ctx.subject)


class AcknowledgeAction(ChannelAction, FinishedAction):
    tool = CommsAckTool
    pending = "Acknowledging…"

    def apply(self, ctx: ThreadActionContext) -> None:
        ctx.comms.views.mark_user_view_read(ctx.subject, worktree=str(ctx.project))

    async def completed(self, app: ToadApp, ctx: ThreadActionContext, result: None) -> None:
        app.notify(f"Marked {ctx.subject} read", title="Session action")


@dataclass(frozen=True)
class ForkAction(ThreadAction[Thread]):
    tool = CommsForkTool
    pending = "Forking…"
    name: str
    task: str

    @classmethod
    def request(
        cls, app: ToadApp, subject: str, actor: str, session_modes: tuple[str, ...] = ()
    ) -> None:
        from toad.comms_root import current_root, root_is_current
        from toad.widgets.comms_fork_dialog import ForkDialog

        selected_root = current_root()

        def accepted(spec: tuple[str, str] | None) -> None:
            if spec is None:
                return
            if not root_is_current(selected_root):
                app.notify("Comms route changed; reopen the thread before forking", severity="error")
                return
            app.invoke_thread_action(cls(*spec), subject, actor, session_modes)

        app.push_screen(ForkDialog(subject), accepted)

    def apply(self, ctx: ThreadActionContext) -> Thread:
        return ctx.comms.threads.fork(ForkSpec(name=self.name, parent=ctx.subject, task=self.task))

    async def completed(self, app: ToadApp, ctx: ThreadActionContext, result: Thread) -> None:
        app.notify(f"forked {result.name} from {ctx.subject}", title="Comms")
