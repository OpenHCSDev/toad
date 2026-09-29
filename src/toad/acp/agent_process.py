"""Subprocess and task lifetime, independent of ACP session semantics."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc
from toad.agent import LogAgentFail
from toad.acp.wire_message import IncomingWireMessage


class ProcessDisposition(DeclaredFamily, affix="ProcessDisposition"):
    accepts_updates = False

    def close(self, agent):
        return self


class ActiveProcessDisposition(ProcessDisposition):
    accepts_updates = True

    def close(self, agent):
        agent.controller.connection_closed()
        return ClosedProcessDisposition()


class ClosedProcessDisposition(ProcessDisposition):
    pass


class AgentProcess:
    def __init__(self, agent):
        self.agent = agent
        self.env = None
        self.cwd = None
        self.root = None
        self.implicit_root = None
        self.process = None
        self.runner = None
        self.session_task = None
        self.responses = set()
        self.retirement = None
        self.disposition = ActiveProcessDisposition()

    async def start(self):
        self.agent.session.starting()
        # Freeze exactly the environment and working directory passed to the
        # child. A relative wire root is relative to the child cwd, not Toad's.
        # Preflight is early denial; the actual spawn takes the core wire lock.
        from .maintenance_ingress import configured_root, preflight

        self.env = os.environ.copy()
        self.implicit_root = (
            "AGENT_COMMS_ROOT" not in self.env
        )
        self.cwd = str(self.agent.project_root_path.resolve())
        self.root = configured_root(
            self.env, self.cwd
        )
        # The later process runner must not re-resolve an alias after the
        # preflight snapshot while prompt admission still uses this root.
        self.env["AGENT_COMMS_ROOT"] = str(self.root)
        try:
            await asyncio.to_thread(
                preflight,
                (self.agent.coordination.wire_root if self.agent.coordination else None),
                ingress_root=self.root,
                cwd=self.cwd,
            )
        except Exception as error:
            self.agent.session.failed()
            self.agent.post_message(LogAgentFail("Failed to start agent", details=str(error), log_path=self.agent.presentation.log_path))
            return
        self.disposition = ActiveProcessDisposition()
        self.agent.controller.replace_terminal_session()
        self.retirement = None
        self.runner = asyncio.create_task(self.run())

    def send(self, request):
        if self.process is None:
            self.agent.log("[error] Agent process isnt running")
            return

        body = request.body
        self.agent.log(f"[client] {body}")
        if (stdin := self.process.stdin) is not None:
            calls = body if isinstance(body, list) else [body]
            if any(
                isinstance(call, dict) and call.get("method") == "session/prompt"
                for call in calls
            ):
                from .maintenance_ingress import admitted_prompt

                with admitted_prompt(
                    (self.agent.coordination.wire_root if self.agent.coordination else None),
                    ingress_root=self.root,
                    cwd=self.cwd,
                    implicit=self.implicit_root,
                ):
                    stdin.write(b"%s\n" % request.body_json)
            else:
                stdin.write(b"%s\n" % request.body_json)

    @property
    def accepts_updates(self):
        return self.disposition.accepts_updates

    def accepts_session(self, session_id: str | None) -> bool:
        """Only the active process may consume work for its current binding."""
        return self.accepts_updates and self.agent.session_id == session_id

    def start_operation(self, operation):
        task = asyncio.create_task(operation)
        if not self.accepts_updates:
            task.cancel()
        self.responses.add(task)
        task.add_done_callback(self.responses.discard)
        return task

    def close(self):
        self.disposition = self.disposition.close(self.agent)

    async def retire(self):
        self.close()
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
        cancelled = False
        while True:
            try:
                await asyncio.shield(self.retirement)
                break
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def _retire(self):
        pending = tuple(task for task in (self.session_task, *self.responses)
                        if task is not None)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.responses.clear()
        if self.process is not None:
            await self.process.stop()
        self.process = self.session_task = None

    async def stop(self):
        self.close()
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

    def session_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None and self.accepts_updates:
            self.startup_failed(f"{type(error).__name__}: {error}")
            if self.runner is not None:
                self.runner.cancel()

    def session_failed(self, failure):
        self.close()
        self.agent.session.failed()
        self.agent.post_message(LogAgentFail(failure.title, failure.feedback, log_path=self.agent.presentation.log_path))

    def startup_failed(self, details):
        self.close()
        self.agent.session.failed()
        self.agent.post_message(LogAgentFail("ACP session startup failed", details=details, log_path=self.agent.presentation.log_path))

    async def communicate(self) -> None:
        """Task to communicate with the agent subprocess."""
        agent = self.agent
        env = (self.env or os.environ).copy()
        env["TOAD_CWD"] = str(Path("./").absolute())
        if (command := agent.command) is None:
            agent.session.failed()
            agent.post_message(
                LogAgentFail("Failed to start agent; no run command for this OS", log_path=agent.presentation.log_path)
            )
            return
        try:
            from .maintenance_ingress import admitted_spawn

            process = self.process = await admitted_spawn(
                command,
                root=agent.coordination.wire_root if agent.coordination else None,
                env=env,
                cwd=self.cwd or str(agent.project_root_path.resolve()),
                limit=10 * 1024 * 1024,
            )
        except Exception as error:
            agent.session.failed()
            agent.post_message(LogAgentFail("Failed to start agent", details=str(error), log_path=self.agent.presentation.log_path))
            return
        self.session_task = asyncio.create_task(agent.session.run())
        self.session_task.add_done_callback(self.session_finished)
        assert process.stdout is not None
        assert process.stdin is not None

        async def call_jsonrpc(request: jsonrpc.JSONObject | jsonrpc.JSONList) -> None:
            if (result := await agent.server.call(request)) is not None:
                result_json = json.dumps(result).encode("utf-8")
                assert process.stdin is not None
                process.stdin.write(b"%s\n" % result_json)

        while line := (await process.stdout.readline()):
            if not line.strip():
                continue
            try:
                line_str = line.decode("utf-8")
            except Exception as error:
                agent.log(f"[error] Unable to decode utf-8 from agent: {error}")
                continue
            agent.log(f"[agent] {line_str}")
            try:
                agent_data: jsonrpc.JSONType = json.loads(line_str)
            except Exception as error:
                agent.log(f"[error] failed to decode JSON from agent: {error}")
                continue
            try:
                incoming = IncomingWireMessage.decode(agent_data)
            except ValueError as error:
                agent.log(f"[error] {error}")
                continue
            await incoming.receive(agent, call_jsonrpc, self)
        if process.returncode and self.accepts_updates:
            agent.session.failed()
            assert process.stderr is not None
            fail_details = (await process.stderr.read()).decode("utf-8", "replace")
            agent.post_message(LogAgentFail(
                f"Agent returned a failure code: [b]{process.returncode}",
                details=fail_details, log_path=agent.presentation.log_path,
            ))
        elif self.accepts_updates and not agent.session.settled.is_set():
            self.startup_failed("ACP process closed before session initialization completed.")
