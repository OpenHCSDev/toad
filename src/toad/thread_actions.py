"""Thread menu declarations own presentation, input collection and execution."""

from __future__ import annotations
from toad.core import events as core_events

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.cli_commands import TargetAction, TargetEdit, TargetBatchResult, TargetFailed
from agent_comms.cli_result import CliResult
from agent_comms.native_pi import NativePiUnavailable
from agent_comms.route_selection import RouteChanged, RouteSelection

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.target_commands import TargetContext


class ThreadActions:
    """One actual task per subject owns pending status and guarded completion."""

    def __init__(self, app: ToadApp) -> None:
        self.app = app
        self.requests: dict[str | Path, ThreadActionExecution] = {}

    @property
    def pending(self) -> dict[str | Path, str]:
        return {name: execution.action.pending for name, execution in self.requests.items()}

    def invoke(self, action: ThreadAction, subject: str, *, source_root: Path) -> None:
        app = self.app
        try:
            selected = RouteSelection.capture(source_root)
        except (OSError, ValueError, RuntimeError) as error:
            app.notify(str(error), title="Session action", severity="error")
            return
        if any(target in self.requests for target in action.resources):
            app.notify(f"An action for {subject} is already in progress", title="Session action")
            return
        execution = ThreadActionExecution(self, action, selected, subject)
        for target in action.resources:
            self.requests[target] = execution
        app.events.publish(core_events.ThreadRowStateChanged())

    def finished(self, execution: ThreadActionExecution) -> None:
        for target in execution.action.resources:
            if self.requests.get(target) is execution:
                del self.requests[target]
        self.app.events.publish(core_events.ThreadRowStateChanged())

    async def close(self) -> None:
        # Domain writes already accepted at their sink must finish, not be
        # reported as absent because a UI task was cancelled during shutdown.
        # A failed action was already raised to the app by its worker.
        await asyncio.gather(*(request.task.wait() for request in set(self.requests.values())),
                             return_exceptions=True)


class ThreadActionExecution:
    """An accepted UI operation owns only its task and captured route resource."""
    def __init__(self, owner, action, selected, subject):
        self.owner, self.action, self.selected = owner, action, selected
        self.subject = subject
        self.task = owner.app.run_worker(self.run(), name="thread-action")

    def apply(self):
        access = self.owner.app.coordination_access
        comms = access.require(self.selected).service
        return access.write(self.selected, self.action.request.apply, comms)

    async def run(self):
        app = self.owner.app
        try:
            result = await app.preparation.run_thread(self.apply)
            # Original start result owns whether a connection changed. This is
            # native connection resource refresh, never backend status mutation.
            await self.action.completed(app, self.selected, result)
        except (OSError, ValueError, RuntimeError) as error:
            app.notify(str(error), title=f"Session action: {self.subject}", severity="error")
        finally:
            # The action's store writes reach views through Core's observation.
            self.owner.finished(self)


@dataclass(frozen=True)
class ThreadAction:
    """A native edit resource borrowing one backend-declared command projection."""
    definition: TargetAction
    request: TargetEdit
    context: TargetContext

    @property
    def resources(self):
        return self.definition.targets or (self.context.project,)

    @property
    def pending(self):
        return self.definition.label + '…'

    async def completed(self, app, selected, result: CliResult):
        await app.session_navigation.retire_missing()
        await app.session_navigation.reconnect(selected, result.reconnect_targets())
        for target in result.open_targets():
            await app.thread_navigation.open(owner_mode=self.context.mode,
                project_path=self.context.project, target=target)
        title = self.context.title
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

        ctx = replace(ctx, mode=ctx.mode or ctx.app.selected_mode)

        async def accepted(arguments):
            if arguments is None:
                return
            try:
                def prepare():
                    ctx.current()
                    return TargetEdit(declaration=definition.declaration, target=definition.targets if ctx.targets else ctx.subject,
                        arguments=arguments, confirmed=bool(definition.edited(arguments).confirmation), channel=ctx.channel, project=str(ctx.project))
                request = await ctx.app.preparation.run_thread(prepare)
                ctx.app.thread_actions.invoke(cls(definition, request, ctx), ctx.title,
                                             source_root=ctx.comms.root)
            except (OSError, ValueError) as error:
                ctx.app.notify(str(error), title=definition.label, severity='error')

        async def prepare():
            if definition.editable_fields or definition.confirmation:
                screen = ctx.app.screen
                try:
                    fields = await ctx.app.preparation.run_thread(
                        lambda: asyncio.run(definition.prepare_fields()))
                    ctx.current()
                except (NativePiUnavailable, RouteChanged) as error:
                    ctx.app.notify(str(error), title=definition.label, severity='error')
                    return
                if ctx.app.screen is screen:
                    ctx.app.push_screen(CommandDialog(definition, ctx.title, fields), accepted)
            else:
                await accepted({})
        ctx.app.run_worker(prepare, name='command-fields')
