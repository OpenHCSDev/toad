"""Subprocess and task lifetime, independent of ACP session semantics."""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import ExitStack
from pathlib import Path
from agent_comms.child_process import StreamingChildStdio, join_retirement
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

    async def start(self):
        self.retirement = None
        self.agent.session.reopen()
        try:
            await asyncio.to_thread(
                self.agent.presentation.log_path.parent.mkdir, parents=True, exist_ok=True
            )
        except OSError:
            pass
        self.agent.session.starting()
        # Freeze exactly the environment and working directory passed to the
        # child. A relative wire root is relative to the child cwd, not Toad's.
        # Preflight is early denial; the actual spawn takes the core wire lock.
        from toad.comms_root import RouteSelection
        from .maintenance_ingress import preflight

        self.env = os.environ.copy()
        self.cwd = str(self.agent.project_root_path.resolve())
        self.route_selection = RouteSelection.for_child(self.env, self.cwd)
        with ExitStack() as acquisition:
            try:
                acquisition.enter_context(self.route_selection.route.admit_client())
                await asyncio.to_thread(
                    preflight,
                    (self.agent.coordination.wire_root if self.agent.coordination else None),
                    ingress_root=self.route_selection.root,
                    cwd=self.cwd,
                )
            except Exception as error:
                self.agent.session.failed()
                self.agent.events.publish(LogAgentFail("Failed to start agent", details=str(error), log_path=self.agent.presentation.log_path))
                return
            # Closing the operational owner during preflight revokes this
            # acquisition; it cannot reopen the process after that await.
            if not self.agent.session.accepts_updates:
                return
            self.agent.controller.replace_terminal_session()
            self.runner = asyncio.create_task(self.run())
            # No await can cancel between task creation and resource transfer.
            # Cancelled/failed preflight owns no runner and closes acquisition.
            self.custody.enter_context(acquisition.pop_all())

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
                    ingress_root=self.route_selection.root,
                    cwd=self.cwd,
                    implicit=self.route_selection.implicit,
                ):
                    stdin.write(b"%s\n" % request.body_json)
            else:
                stdin.write(b"%s\n" % request.body_json)

    async def retire(self):
        self.agent.session.close()
        if self.retirement is None:
            self.retirement = asyncio.create_task(self._retire())
        await join_retirement(self.retirement)

    async def _retire(self):
        await self.agent.session.retire()
        if self.process is not None:
            await self.process.stop()
        self.process = None
        self.custody.close()

    async def stop(self):
        self.agent.session.close()
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
        if (command := agent.command) is None:
            agent.session.failed()
            agent.events.publish(
                LogAgentFail("Failed to start agent; no run command for this OS", log_path=agent.presentation.log_path)
            )
            return
        try:
            from .maintenance_ingress import admitted_spawn

            process = self.process = await admitted_spawn(
                command,
                root=agent.coordination.wire_root if agent.coordination else None,
                env=env,
                selection=self.route_selection,
                cwd=self.cwd or str(agent.project_root_path.resolve()),
                stdio=StreamingChildStdio(limit=10 * 1024 * 1024),
            )
        except Exception as error:
            agent.session.failed()
            agent.events.publish(LogAgentFail("Failed to start agent", details=str(error), log_path=self.agent.presentation.log_path))
            return
        agent.session.start()
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
            await incoming.receive(agent, call_jsonrpc)
        if process.returncode and self.agent.session.accepts_updates:
            agent.session.failed()
            assert process.stderr is not None
            fail_details = (await process.stderr.read()).decode("utf-8", "replace")
            agent.events.publish(LogAgentFail(
                f"Agent returned a failure code: [b]{process.returncode}",
                details=fail_details, log_path=agent.presentation.log_path,
            ))
        elif self.agent.session.accepts_updates and not agent.session.settled.is_set():
            self.agent.session.startup_failed("ACP process closed before session initialization completed.")
