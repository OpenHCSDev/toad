"""Subprocess and task lifetime, independent of ACP session semantics."""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from agent_comms.acp_ingress import AcpIngress
from agent_comms.child_process import StreamingChildStdio, join_retirement
from toad.acp.shell_command import ShellCommand
from toad import jsonrpc
from toad.core.events import LogAgentFail
from toad.acp.wire_message import IncomingWireMessage


class AgentProcess:
    def __init__(self, agent):
        self.agent = agent
        self.env = None
        self.cwd = None
        self.route_selection = None
        self.process = None
        self.runner = None
        self.retirement = None
        self.custody = ExitStack()
        self.sessions = set()
        self.initialization = None
        self.command = None
        self.attachment_lock = asyncio.Lock()

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
                acquisition.enter_context(selection.route.admit_client())
                await AcpIngress(selection, Path(cwd), self.attached_root(agent)).preflight()
            except (OSError, ValueError, RuntimeError) as error:
                agent.session.failed()
                agent.events.publish(LogAgentFail("Failed to start agent", details=str(error),
                                                 log_path=agent.presentation.log_path))
                return self
            if not agent.session.accepts_updates:
                return self
            for connection in dict.fromkeys((self, *processes)):
                if connection.accepts_attachment(agent, env, cwd, selection):
                    # Bind the acquired connection before eager session tasks run.
                    agent.process = connection
                    connection.sessions.add(agent.session)
                    agent.controller.replace_terminal_session()
                    agent.session.start()
                    return connection
            # A previously shared connection cannot be repurposed for another
            # launch. Keep its original sessions and acquire a new process.
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
            connection.custody.enter_context(acquisition.pop_all())
            return connection

    def send(self, request, agent):
        if self.process is None:
            agent.log("[error] Agent process isnt running")
            return

        body = request.body
        agent.log(f"[client] {body}")
        if (stdin := self.process.stdin) is not None:
            stdin.write(b"%s\n" % request.body_json)

    @staticmethod
    def attached_root(agent):
        return agent.coordination.wire_root if agent.coordination else None

    def ingress(self, agent):
        return AcpIngress(self.route_selection, Path(self.cwd), self.attached_root(agent))

    @asynccontextmanager
    async def admitted_prompt(self, agent):
        """Core ingress admission held through the prompt's stdin write.

        Admission is acquired off this loop; the write stays on it. Without a
        process there is nothing to admit, and send() reports that.
        """
        if self.process is None:
            yield
            return
        async with self.ingress(agent).prompt():
            yield

    async def retire(self):
        for session in tuple(self.sessions):
            session.close()
            # EOF must release a pending close response too. Those replies are
            # owned by the session, just like all its other outstanding work.
            for task in tuple(session.responses):
                task.cancel()
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
        await join_retirement(self.retirement)

    async def _retire(self):
        try:
            await asyncio.gather(*(session.retire() for session in tuple(self.sessions)),
                                 return_exceptions=True)
        finally:
            if self.process is not None:
                await self.process.stop()
            self.process = None
            self.sessions.clear()
            self.custody.close()

    async def detach(self, session):
        from . import api
        async with self.attachment_lock:
            if session not in self.sessions:
                return
            try:
                if self.retirement is None and len(self.sessions) > 1:
                    # Only advertised scoped-close transports acquire multiple
                    # members. Revoke locally first, then join remote retirement.
                    with session.agent.request():
                        response = api.session_close(session.agent.session_id)
                    task = asyncio.create_task(response.wait())
                    session.responses.add(task)
                    task.add_done_callback(session.responses.discard)
                    await task
            except BaseException:
                # Unknown remote closure cannot leave a shared connection with
                # an unowned attachment. Retire it; never replay the close.
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
        """Task to communicate with the agent subprocess."""
        agent = self.agent
        env = (self.env or os.environ).copy()
        env["TOAD_CWD"] = str(Path("./").absolute())
        if (command := self.command) is None:
            agent.session.failed()
            agent.events.publish(
                LogAgentFail("Failed to start agent; no run command for this OS", log_path=agent.presentation.log_path)
            )
            return
        try:
            process = self.process = await self.ingress(agent).spawn(
                ShellCommand.current().argv(command), env=env,
                stdio=StreamingChildStdio(limit=10 * 1024 * 1024),
            )
        except (OSError, ValueError, RuntimeError) as error:
            agent.session.failed()
            agent.events.publish(LogAgentFail("Failed to start agent", details=str(error), log_path=self.agent.presentation.log_path))
            return
        agent.session.start()
        assert process.stdout is not None
        assert process.stdin is not None

        async def call_jsonrpc(request, recipient):
            if recipient is None:
                result = ({"jsonrpc": "2.0", "id": request["id"], "error": {
                    "code": -32602, "message": "ACP session is retired or unknown"}}
                    if "id" in request else None)
            else:
                result = await recipient.server.call(request)
            if result is not None:
                result_json = json.dumps(result).encode("utf-8")
                assert process.stdin is not None
                process.stdin.write(b"%s\n" % result_json)

        while line := (await process.stdout.readline()):
            if not line.strip():
                continue
            try:
                line_str = line.decode("utf-8")
            except UnicodeDecodeError as error:
                agent.log(f"[error] Unable to decode utf-8 from agent: {error}")
                continue
            for session in tuple(self.sessions):
                session.agent.log(f"[agent] {line_str}")
            try:
                agent_data: jsonrpc.JSONType = json.loads(line_str)
            except json.JSONDecodeError as error:
                agent.log(f"[error] failed to decode JSON from agent: {error}")
                continue
            try:
                incoming = IncomingWireMessage.decode(agent_data)
            except ValueError as error:
                agent.log(f"[error] {error}")
                continue
            await incoming.receive(self.recipient(agent_data), call_jsonrpc)
        for session in tuple(self.sessions):
            if not session.accepts_updates:
                continue
            if process.returncode:
                session.failed()
                assert process.stderr is not None
                fail_details = (await process.stderr.read()).decode("utf-8", "replace")
                session.agent.events.publish(LogAgentFail(
                    f"Agent returned a failure code: [b]{process.returncode}",
                    details=fail_details, log_path=session.agent.presentation.log_path))
            elif not session.settled.is_set():
                session.startup_failed("ACP process closed before session initialization completed.")

    def recipient(self, request):
        if not isinstance(request, dict):
            return None
        params = request.get("params")
        session_id = params.get("sessionId") if isinstance(params, dict) else None
        members = tuple(member.agent for member in self.sessions if member.accepts_updates)
        if session_id is not None:
            matched = next((agent for agent in members if agent.session.accepts_session(session_id)), None)
            if matched is not None:
                return matched
            return (members[0] if len(members) == 1
                    and not members[0].controller.session.bound else None)
        # Unbound new sessions are never multiplexed; their original callback
        # contract remains available on their dedicated process.
        return members[0] if len(members) == 1 else None
