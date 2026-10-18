"""ACP connection, admitted subprocess and attached-session lifetime."""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import ExitStack
from contextvars import ContextVar
from pathlib import Path
from acp import Client, ClientSideConnection, schema
from acp.connection import StreamDirection, StreamEvent
from acp.exceptions import RequestError
from agent_comms.acp_ingress import AcpIngress
from agent_comms.child_process import StreamingChildStdio, join_retirement
from toad.acp.shell_command import ShellCommand
from toad.core.events import LogAgentFail


class AgentProcess(Client):
    def __init__(self, agent):
        self.agent = agent
        self.env = None
        self.cwd = None
        self.route_selection = None
        self.process = None
        self.connection: ClientSideConnection | None = None
        self.runner = None
        self.retirement = None
        self.cleanup = ExitStack()
        self.sessions = set()
        self.initialization = None
        self.command = None
        self.attachment_lock = asyncio.Lock()
        self._incoming: ContextVar[dict] = ContextVar('acp_incoming')
        self._prompt_written: ContextVar[asyncio.Future] = ContextVar('acp_prompt_written')

    @property
    def rpc(self) -> ClientSideConnection:
        if self.connection is None:
            raise ConnectionError('ACP process is not connected')
        return self.connection

    def accepts_attachment(self, agent, env, cwd, selection):
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

    async def start(self, agent, processes=()):
        agent.session.reopen()
        agent.session.starting()
        try:
            await asyncio.to_thread(
                agent.presentation.log_path.parent.mkdir, parents=True, exist_ok=True)
        except OSError:
            pass
        from agent_comms.route_selection import RouteSelection
        env = os.environ.copy()
        cwd = str(agent.project_root_path.resolve())
        selection = RouteSelection.for_child(env, cwd)
        with ExitStack() as acquisition:
            try:
                acquisition.enter_context(selection.route.hold_client_route())
                await AcpIngress(selection, Path(cwd), self.attached_root(agent)).preflight()
            except (OSError, ValueError, RuntimeError) as error:
                agent.session.startup_failed(str(error))
                return self
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
            connection.cleanup.enter_context(acquisition.pop_all())
            return connection

    @staticmethod
    def attached_root(agent):
        return agent.coordination.wire_root if agent.coordination else None

    def ingress(self, agent):
        return AcpIngress(self.route_selection, Path(self.cwd), self.attached_root(agent))

    async def prompt(self, agent, content, metadata, require):
        """Core admits the actual SDK write, not the duration of the reply."""
        written = asyncio.get_running_loop().create_future()
        token = self._prompt_written.set(written)
        try:
            async with self.ingress(agent).prompt():
                require()
                pending = asyncio.create_task(self.rpc.prompt(agent.session_id, content, **metadata))
                flushed = asyncio.create_task(asyncio.wait(
                    (written, pending), return_when=asyncio.FIRST_COMPLETED))
                try:
                    await asyncio.shield(flushed)
                except asyncio.CancelledError:
                    # The SDK may already have queued bytes. Keep Core's lock
                    # until that write finishes or fails, even during retirement.
                    await flushed
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                    raise
                if not written.done():
                    return await pending
        finally:
            self._prompt_written.reset(token)
        return await pending

    def observe_stream(self, event: StreamEvent):
        """Keep the original frame with its SDK handler and acknowledge real writes."""
        if event.direction is StreamDirection.INCOMING:
            # SDK creates the handler task immediately after this observer; its
            # context captures this frame, independently of later notifications.
            self._incoming.set(event.message)
            sender = 'agent'
        else:
            sender = 'client'
            try:
                written = self._prompt_written.get()
            except LookupError:
                pass
            else:
                if not written.done():
                    written.set_result(None)
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

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.permissions.request_permission(session_id, options, tool_call, kwargs))

    async def session_update(self, session_id, update, **kwargs):
        agent = self.recipient(session_id)
        notification = schema.SessionNotification.model_construct(
            session_id=session_id, update=update, field_meta=kwargs or None)
        raw = self._incoming.get()['params']['update']
        await agent.session.start_operation(agent.updates.receive(notification, raw))

    async def read_text_file(self, session_id, path, line=None, limit=None, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(asyncio.to_thread(
            agent.files.read_text_file, session_id, path, line, limit))

    async def write_text_file(self, session_id, path, content, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(asyncio.to_thread(
            agent.files.write_text_file, session_id, path, content))

    async def create_terminal(self, session_id, command, args=None, env=None,
                              cwd=None, output_byte_limit=None, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(agent.controller.terminal_create(
            session_id, command, kwargs, args, cwd, env, output_byte_limit))

    async def terminal_output(self, session_id, terminal_id, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.controller.terminal_output(session_id, terminal_id, kwargs))

    async def release_terminal(self, session_id, terminal_id, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.controller.terminal_release(session_id, terminal_id, kwargs))

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kwargs):
        agent = self.recipient(session_id)
        return await agent.session.start_operation(
            agent.controller.terminal_wait_for_exit(session_id, terminal_id, kwargs))

    async def kill_terminal(self, session_id, terminal_id, **kwargs):
        agent = self.recipient(session_id)
        return agent.controller.terminal_kill(session_id, terminal_id, kwargs)

    async def create_elicitation(self, message, mode, **kwargs):
        raise RequestError.method_not_found('elicitation/create')

    async def complete_elicitation(self, elicitation_id, **kwargs):
        raise RequestError.method_not_found('elicitation/complete')

    async def ext_method(self, method, params):
        raise RequestError.method_not_found(f'_{method}')

    async def ext_notification(self, method, params):
        self.agent.log(f'[ACP unsupported notification] _{method}: {params}')

    def on_connect(self, conn):
        pass

    async def retire(self):
        for session in tuple(self.sessions):
            session.close()
            for task in tuple(session.responses):
                task.cancel()
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
        await join_retirement(self.retirement)

    async def _retire(self):
        try:
            if self.connection is not None:
                await self.connection.close()
                self.connection = None
            await asyncio.gather(*(session.retire() for session in tuple(self.sessions)),
                                 return_exceptions=True)
        finally:
            if self.process is not None:
                await self.process.stop()
            self.process = None
            self.sessions.clear()
            self.cleanup.close()

    async def detach(self, session):
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

    async def stop(self, agent):
        agent.session.close()
        await agent.session.retire()
        if not self.sessions:
            if self.runner is not None and self.runner is not asyncio.current_task():
                self.runner.cancel()
                await asyncio.gather(self.runner, return_exceptions=True)
            await self.retire()
            self.runner = None

    async def run(self):
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
        try:
            process = self.process = await self.ingress(agent).spawn(
                ShellCommand.current().argv(command), env=env,
                stdio=StreamingChildStdio(limit=10 * 1024 * 1024),
            )
        except (OSError, ValueError, RuntimeError) as error:
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
