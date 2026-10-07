"""Thread menu declarations own presentation, input collection and execution."""

from __future__ import annotations
from toad.core import events as core_events

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.cli_commands import TargetAction, TargetEdit, TargetBatchResult, TargetFailed
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

    def invoke(self, action: ThreadAction, subject: str, *, source_root: Path) -> None:
        app = self.app
        try:
            selected = RouteSelection.capture(source_root)
        except (OSError, ValueError, RuntimeError) as error:
            app.notify(str(error), title="Session action", severity="error")
            return
        if any(target in self.requests for target in action.definition.targets):
            app.notify(f"An action for @{subject} is already in progress", title="Session action")
            return
        execution = ThreadActionExecution(self, action, selected, subject)
        for target in action.definition.targets:
            self.requests[target] = execution
        app.events.publish(core_events.ThreadActionsChanged())

    def finished(self, execution: ThreadActionExecution) -> None:
        for target in execution.action.definition.targets:
            if self.requests.get(target) is execution:
                del self.requests[target]
        self.app.events.publish(core_events.ThreadActionsChanged())

    async def close(self) -> None:
        # Domain writes already accepted at their sink must finish, not be
        # reported as absent because a UI task was cancelled during shutdown.
        await asyncio.gather(*(request.task for request in set(self.requests.values())), return_exceptions=True)


class ThreadActionExecution:
    """An accepted UI operation owns only its task and captured route resource."""
    def __init__(self, owner, action, selected, subject):
        self.owner, self.action, self.selected = owner, action, selected
        self.subject = subject
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
            await self.action.completed(app, self.selected, result)
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

    async def completed(self, app, selected, result):
        await app.session_navigation.retire_missing()
        await app.session_navigation.reconnect(
            selected, self.request.declaration.reconnect_targets(result))
        title = ", ".join(self.definition.targets)
        if isinstance(result, TargetBatchResult) and not result.successful:
            failures = [f"{item.target}: {item.error}" for item in result.outcomes
                        if isinstance(item, TargetFailed)]
            completed = sum(item.successful for item in result.outcomes)
            app.notify(f"{completed}/{len(result.outcomes)} completed\n" + "\n".join(failures),
                       title=title, severity="error")
        else:
            app.notify(self.definition.label, title=title)

    @classmethod
    def collect(cls, ctx, definition):
        from toad.widgets.comms_command_dialog import CommandDialog

        def accepted(arguments):
            if arguments is None:
                return
            try:
                ctx.current()
                request = TargetEdit(declaration=definition.declaration, target=definition.targets if ctx.targets else ctx.subject,
                    arguments=arguments, confirmed=bool(definition.edited(arguments).confirmation), channel=ctx.channel)
                ctx.app.thread_actions.invoke(cls(definition, request), ctx.subject,
                                             source_root=ctx.comms.root)
            except (OSError, ValueError) as error:
                ctx.app.notify(str(error), title=definition.label, severity='error')

        if definition.editable_fields or definition.confirmation:
            ctx.app.push_screen(CommandDialog(definition, ctx.title), accepted)
        else:
            accepted({})
