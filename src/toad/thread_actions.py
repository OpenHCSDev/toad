"""Thread menu declarations own presentation, input collection and execution."""

from __future__ import annotations
from toad.core import events as core_events

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_comms.cli_commands import TargetAction, TargetEdit
from toad.comms_root import RouteSelection

if TYPE_CHECKING:
    from toad.app import ToadApp


class ThreadActions:
    """One actual task per subject owns pending status and guarded completion."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.requests: dict[str, ThreadActionExecution] = {}

    @property
    def pending(self) -> dict[str, str]:
        return {name: execution.action.pending for name, execution in self.requests.items()}

    def invoke(self, action: ThreadAction, subject: str, actor: str, session_modes: tuple[str, ...] = ()) -> None:
        app = self.app
        source_root = app.screen.coordination_root
        if source_root is None:
            from toad.widgets.comms_sidebar import CommsSidebar
            sidebar = app.screen.query_one_optional(CommsSidebar)
            if sidebar is not None:
                observed = sidebar.observation.service
                if observed is not None:
                    source_root = observed.root
        try:
            selected = RouteSelection.capture(source_root)
        except (OSError, ValueError, RuntimeError) as error:
            app.notify(str(error), title="Session action", severity="error")
            return
        if subject in self.requests:
            app.notify(f"An action for @{subject} is already in progress", title="Session action")
            return
        self.requests[subject] = ThreadActionExecution(self, action, selected, subject, actor, session_modes)
        app.events.publish(core_events.ThreadActionsChanged())

    def finished(self, execution: ThreadActionExecution) -> None:
        if self.requests.get(execution.subject) is execution:
            del self.requests[execution.subject]
        self.app.events.publish(core_events.ThreadActionsChanged())

    async def close(self) -> None:
        # Domain writes already accepted at their sink must finish, not be
        # reported as absent because a UI task was cancelled during shutdown.
        await asyncio.gather(*(request.task for request in tuple(self.requests.values())), return_exceptions=True)


class ThreadActionExecution:
    """An accepted UI operation owns only its task and captured route resource."""
    def __init__(self, owner, action, selected, subject, actor, session_modes):
        self.owner, self.action, self.selected = owner, action, selected
        self.subject, self.actor, self.session_modes = subject, actor, session_modes
        self.task = asyncio.create_task(self.run(), name="thread-action")

    def apply(self):
        access = self.owner.app.coordination_access
        comms = access.require(self.selected)
        return access.write(self.selected, self.action.request.apply, comms)

    async def run(self):
        app = self.owner.app
        try:
            result = await app.preparation.run_thread(self.apply)
            # Original start result owns whether a connection changed. This is
            # native connection resource refresh, never backend status mutation.
            await self.action.completed(app, self.session_modes, result)
        except Exception as error:
            app.notify(str(error), title=f"Session action: {self.subject}", severity="error")
        finally:
            self.owner.finished(self)
            app.coordination_access.refresh()


@dataclass(frozen=True)
class ThreadAction:
    """A native edit resource borrowing one backend-declared command projection."""
    definition: TargetAction
    request: TargetEdit

    @property
    def pending(self):
        return self.definition.label + '…'

    async def completed(self, app, session_modes, result):
        await app.session_navigation.retire_missing()
        for thread in self.request.declaration.reconnect_targets(result):
            for mode in session_modes:
                source = app.session_navigation.source(mode)
                if source is not None and source.conversation.agent is not None:
                    await source.conversation.agent.session.reconnect()
        app.notify(self.definition.label, title=self.request.target)

    @classmethod
    def collect(cls, ctx, definition):
        from toad.widgets.comms_command_dialog import CommandDialog

        def accepted(arguments):
            if arguments is None:
                return
            try:
                ctx.current()
                request = TargetEdit(declaration=definition.declaration, target=ctx.subject,
                    arguments=arguments, confirmed=bool(definition.edited(arguments).confirmation()), channel=ctx.channel)
                ctx.app.thread_actions.invoke(cls(definition, request), ctx.subject, ctx.actor,
                    (ctx.mode,) if ctx.mode is not None else ())
            except (OSError, ValueError) as error:
                ctx.app.notify(str(error), title=definition.label, severity='error')

        if definition.editable_fields or definition.confirmation:
            ctx.app.push_screen(CommandDialog(definition, ctx.subject), accepted)
        else:
            accepted({})
