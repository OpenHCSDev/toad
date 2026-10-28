"""ACP connection, admitted subprocess and attached-session lifetime."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from contextvars import ContextVar
from functools import partial
from pathlib import Path
from typing import Optional

from acp import Client, ClientSideConnection, schema
from acp.connection import StreamDirection, StreamEvent
from acp.exceptions import RequestError
from agent_comms.child_process import (
    AttachedChild,
    StreamingChildStdio,
    join_retirement,
)
from agent_comms.launch_root import LaunchRoot
from agent_comms.route_selection import RouteSelection
from pydantic import JsonValue

from toad.acp.agent_session import AgentSession
from toad.acp.shell_command import ShellCommand
from toad.core.events import LogAgentFail
from toad.resource_release import AsyncResourceRelease


class AgentProcess(Client):
    def __init__(self, agent) -> None:
        self.agent = agent
        self.env: dict[str, str] | None = None
        self.cwd: str | None = None
        self.route_selection: RouteSelection | None = None
        self.process: AttachedChild | None = None
        self.connection: ClientSideConnection | None = None
        self.runner: asyncio.Task[None] | None = None
        self.retirement: asyncio.Task[None] | None = None
        self.sessions: set[AgentSession] = set()
        self.initialization: schema.InitializeResponse | None = None
        self.command: str | None = None
        self.attachment_lock = asyncio.Lock()
        self._incoming: ContextVar[dict] = ContextVar('acp_incoming')

    @property
    def rpc(self) -> ClientSideConnection:
        if self.connection is None:
            raise ConnectionError('ACP process is not connected')
        return self.connection

    def accepts_attachment(self, agent, env: dict[str, str], cwd: str, selection: RouteSelection):
        response = self.initialization
        capabilities = response.agent_capabilities if response is not None else None
        lifecycle = capabilities.session_capabilities if capabilities is not None else None
        return (self.runner is not None and not self.runner.done()
                and self.retirement is None and self.process is not None
                and self.process.returncode is None
                and lifecycle is not None and lifecycle.close is not None
                and self.command == agent.command and self.env == env
                and self.cwd == cwd and self.route_selection == selection
                and agent.session_id is not None
                and all(member.agent.session_id != agent.session_id for member in self.sessions))

    async def start(self, agent, processes: tuple[AgentProcess, ...]=()):
        agent.session.reopen()
        agent.session.starting()
        await asyncio.to_thread(
            agent.presentation.log_path.parent.mkdir, parents=True, exist_ok=True)
        env = os.environ.copy()
        cwd = str(agent.project_root_path.resolve())
        selection = RouteSelection.capture(agent.controller.transcripts.access.launch_root.path)
        if not agent.session.accepts_updates:
            return self
        for connection in dict.fromkeys((self, *processes)):
            if connection.accepts_attachment(agent, env, cwd, selection):
                agent.process = connection
                connection.sessions.add(agent.session)
                agent.controller.replace_terminal_session()
                agent.session.start()
                return connection
        connection = AgentProcess(agent) if self.sessions else self
        connection.agent = agent
        connection.env, connection.cwd, connection.route_selection = env, cwd, selection
        connection.command = agent.command
        connection.initialization = None
        connection.retirement = None
        agent.process = connection
        connection.sessions.add(agent.session)
        agent.controller.replace_terminal_session()
        connection.runner = asyncio.create_task(connection.run())
        return connection

    async def prompt(self, agent, content, metadata: dict[str, JsonValue], require: Callable[[], None]):
        """The agent-comms-acp child writes the prompt under Core's maintenance gate."""
        access = agent.controller.transcripts.access
        await access.preparation.run_thread(partial(access.require, self.route_selection))
        require()
        return await self.rpc.prompt(agent.session_id, content, **metadata)

    def observe_stream(self, event: StreamEvent) -> None:
        """Keep the original frame with its SDK handler."""
        if event.direction is StreamDirection.INCOMING:
            # SDK creates the handler task immediately after this observer; its
            # context captures this frame, independently of later notifications.
            self._incoming.set(event.message)
            sender = 'agent'
        else:
            sender = 'client'
        line = f'[{sender}] {json.dumps(event.message)}'
        for session in tuple(self.sessions):
            session.agent.log(line)

    def recipient(self, session_id: str):
        members = tuple(member.agent for member in self.sessions if member.accepts_updates)
        for agent in members:
            if agent.session.accepts_session(session_id):
                return agent
        if len(members) == 1 and not members[0].controller.session.bound:
            return members[0]
        raise RequestError.invalid_params({'details': 'ACP session is retired or unknown'})

    async def request_permission(
        self,
        session_id: str,
        tool_call: schema.ToolCallUpdate,
        options: list[schema.PermissionOption],
        **kwargs: JsonValue,
    ):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.permissions.request_permission(session_id, options, tool_call, kwargs))

    async def session_update(
        self,
        session_id: str,
        update: schema.UserMessageChunk
        | schema.AgentMessageChunk
        | schema.AgentThoughtChunk
        | schema.ToolCallStart
        | schema.ToolCallProgress
        | schema.AgentPlanUpdate
        | schema.AgentPlanContentUpdate
        | schema.AgentPlanRemovedUpdate
        | schema.AvailableCommandsUpdate
        | schema.CurrentModeUpdate
        | schema.ConfigOptionUpdate
        | schema.SessionInfoUpdate
        | schema.UsageUpdate,
        **kwargs: JsonValue,
    ) -> None:
        agent = self.recipient(session_id)
        notification = schema.SessionNotification.model_construct(
            session_id=session_id, update=update, field_meta=kwargs or None)
        raw = self._incoming.get()['params']['update']
        await agent.session.start_operation(agent.updates.receive(notification, raw))

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line=None,
        limit: Optional[int] = None,
        **kwargs: JsonValue,
    ):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(asyncio.to_thread(
            agent.files.read_text_file, session_id, path, line, limit))

    async def write_text_file(self, session_id: str, path: str, content: str, **kwargs: JsonValue):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(asyncio.to_thread(
            agent.files.write_text_file, session_id, path, content))

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args=None,
        env=None,
        cwd=None,
        output_byte_limit=None,
        **kwargs: JsonValue,
    ):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(agent.controller.terminal_create(
            session_id, command, kwargs, args, cwd, env, output_byte_limit))

    async def terminal_output(self, session_id: str, terminal_id: str, **kwargs: JsonValue):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.controller.terminal_output(session_id, terminal_id, kwargs))

    async def release_terminal(self, session_id: str, terminal_id: str, **kwargs: JsonValue):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.controller.terminal_release(session_id, terminal_id, kwargs))

    async def wait_for_terminal_exit(self, session_id: str, terminal_id: str, **kwargs: JsonValue):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.controller.terminal_wait_for_exit(session_id, terminal_id, kwargs))

    async def kill_terminal(self, session_id: str, terminal_id: str, **kwargs: JsonValue):
        agent = self.recipient(session_id)
        return agent.controller.terminal_kill(session_id, terminal_id, kwargs)

    async def create_elicitation(self, message: str, mode: schema.ElicitationMode, **kwargs: JsonValue):
        raise RequestError.method_not_found('elicitation/create')

    async def complete_elicitation(self, elicitation_id: str, **kwargs: JsonValue):
        raise RequestError.method_not_found('elicitation/complete')

    async def ext_method(self, method: str, params: dict[str, JsonValue]):
        raise RequestError.method_not_found(f'_{method}')

    async def ext_notification(self, method: str, params: dict[str, JsonValue]) -> None:
        self.agent.log(f'[ACP unsupported notification] _{method}: {params}')

    def on_connect(self, conn: ClientSideConnection) -> None:
        pass

    async def retire(self) -> None:
        for session in tuple(self.sessions):
            session.close()
            for task in tuple(session.responses):
                task.cancel()
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
        await join_retirement(self.retirement)

    async def _retire(self) -> None:
        try:
            async with AsyncResourceRelease() as release:
                if self.process is not None:
                    release.push_async_callback(self.process.stop)
                for session in tuple(self.sessions):
                    release.push_async_callback(session.retire)
                if self.connection is not None:
                    try:
                        await self.connection.close()
                    except (BrokenPipeError, ConnectionResetError) as error:
                        # The SDK joins its sender here; an already closed peer can
                        # leave that sender failed. All sessions are retiring.
                        self.agent.log(f'[ACP transport closed during retirement] {error}')
                    finally:
                        self.connection = None
        finally:
            self.process = None
            self.sessions.clear()

    async def detach(self, session: AgentSession):
        async with self.attachment_lock:
            if session not in self.sessions:
                return
            try:
                if (self.retirement is None and len(self.sessions) > 1
                        and session.disposition.held_by_agent):
                    task = asyncio.create_task(self.rpc.close_session(session.agent.session_id))
                    session.responses.add(task)
                    task.add_done_callback(session.responses.discard)
                    await task
            except BaseException:
                if self.runner is not None:
                    self.runner.cancel()
                raise
            finally:
                self.sessions.discard(session)
            if not self.sessions and self.retirement is None and self.runner is not None:
                self.runner.cancel()

    async def stop(self, agent) -> None:
        agent.session.close()
        await agent.session.retire()
        if not self.sessions:
            if self.runner is not None and self.runner is not asyncio.current_task():
                self.runner.cancel()
                await asyncio.gather(self.runner, return_exceptions=True)
            await self.retire()
            self.runner = None

    async def run(self) -> None:
        try:
            await self.communicate()
        finally:
            await self.retire()

    async def communicate(self) -> None:
        agent = self.agent
        env = (self.env or os.environ).copy()
        env['TOAD_CWD'] = str(Path('./').absolute())
        if (command := self.command) is None:
            agent.session.startup_failed('No run command for this OS')
            return
        assert self.route_selection is not None
        try:
            accepts_root = agent.definition.accepts_comms_root
            launch = LaunchRoot.from_path(self.route_selection.root)
            process = self.process = await AttachedChild.start(
                (*ShellCommand.current().argv(command, accepts_comms_root=accepts_root),
                 *(launch.arguments() if accepts_root else ())),
                env=LaunchRoot.environment(env), cwd=self.cwd,
                stdio=StreamingChildStdio(limit=10 * 1024 * 1024),
            )
        except (FileNotFoundError, PermissionError) as error:
            agent.session.startup_failed(str(error))
            return
        assert process.stdout is not None
        assert process.stdin is not None
        self.connection = ClientSideConnection(
            self, process.stdin, process.stdout, observers=[self.observe_stream])
        agent.session.start()
        outcome = await process.wait()
        fail_details = await process.stderr_tail()
        for session in tuple(self.sessions):
            if not session.accepts_updates:
                continue
            if not outcome.successful:
                session.agent.log(f'[error] {fail_details}')
                session.record_failure(LogAgentFail(
                    f'Agent {outcome.summary}',
                    details=fail_details, log_path=session.agent.presentation.log_path))
            elif not session.settled.is_set():
                session.startup_failed('ACP process closed before session initialization completed.')
