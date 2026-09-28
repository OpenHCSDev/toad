"""Subprocess and task lifetime, independent of ACP session semantics."""
from __future__ import annotations
import asyncio
import json
import os
from abc import abstractmethod
from contextlib import suppress
from pathlib import Path
from agent_comms.declared_family import DeclaredFamily
from toad import jsonrpc
from toad.agent import AgentFail
from toad.acp.wire_message import IncomingWireMessage


class ProcessControl(DeclaredFamily, affix="ProcessControl"):
    @property
    @abstractmethod
    def spawn_options(self) -> dict: ...

    def started(self, process) -> None:
        pass

    @abstractmethod
    async def finish(self, process) -> None: ...

    @abstractmethod
    async def stop(self, process) -> None: ...

    @staticmethod
    async def wait(process, seconds):
        if process is not None and process.returncode is None:
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=seconds)


class PosixProcessControl(ProcessControl):
    spawn_options = {"start_new_session": True}

    def __init__(self):
        self.group_id = None

    def started(self, process):
        self.group_id = process.pid

    def alive(self):
        if self.group_id is None:
            return False
        try:
            os.killpg(self.group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def signal(self, signal):
        if self.group_id is not None:
            with suppress(OSError):
                os.killpg(self.group_id, signal)

    async def finish(self, process):
        if self.alive():
            self.signal(15)
            await asyncio.sleep(0.1)
            if self.alive():
                self.signal(9)
        self.group_id = None

    async def stop(self, process):
        self.signal(15)
        await self.wait(process, 3)
        if self.alive():
            self.signal(9)
            deadline = asyncio.get_running_loop().time() + 1
            while self.alive() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.05)
        await self.wait(process, 1)
        self.group_id = None


class WindowsProcessControl(ProcessControl):
    spawn_options = {"start_new_session": False}

    async def finish(self, process):
        pass

    async def stop(self, process):
        if process is None or process.returncode is not None:
            return
        with suppress(OSError):
            process.terminate()
        await self.wait(process, 3)
        if process.returncode is None:
            with suppress(OSError):
                process.kill()
            await self.wait(process, 1)


class AgentProcess:
    def __init__(self, agent):
        self.agent = agent
        self.control = WindowsProcessControl() if os.name == "nt" else PosixProcessControl()
        self.process = None
        self.runner = None
        self.session_task = None
        self.responses = set()
        self.stopping = False

    def start(self):
        self.stopping = False
        self.runner = asyncio.create_task(self.run())

    async def stop(self):
        self.stopping = True
        process = self.process
        if process is not None and process.returncode is None and process.stdin is not None:
            process.stdin.close()
            with suppress(BrokenPipeError, ConnectionResetError):
                await process.stdin.wait_closed()
            await self.control.wait(process, 1)
        await self.control.stop(process)
        current = asyncio.current_task()
        pending = [task for task in (self.session_task, self.runner, *self.responses)
                   if task is not None and task is not current]
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.responses.clear()
        self.process = self.session_task = self.runner = None

    async def run(self) -> None:
        """Task to communicate with the agent subprocess."""
        agent = self.agent
        PIPE = asyncio.subprocess.PIPE
        env = (agent._maintenance_env or os.environ).copy()
        env["TOAD_CWD"] = str(Path("./").absolute())
        if (command := agent.command) is None:
            agent.post_message(
                AgentFail("Failed to start agent; no run command for this OS")
            )
            return
        try:
            from .maintenance_ingress import admitted_spawn

            process = self.process = await admitted_spawn(
                command,
                root=agent.coordination.wire_root if agent.coordination else None,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                env=env,
                cwd=agent._maintenance_cwd or str(agent.project_root_path.resolve()),
                limit=10 * 1024 * 1024,
                **self.control.spawn_options,
            )
            self.control.started(process)
        except Exception as error:
            agent._connected_ok = False
            agent.session_ready_event.set()
            agent.post_message(AgentFail("Failed to start agent", details=str(error)))
            return
        self.session_task = asyncio.create_task(agent.run())
        assert process.stdout is not None
        assert process.stdin is not None
        tasks = self.responses

        async def call_jsonrpc(request: jsonrpc.JSONObject | jsonrpc.JSONList) -> None:
            try:
                if (result := await agent.server.call(request)) is not None:
                    result_json = json.dumps(result).encode("utf-8")
                    if process.stdin is not None:
                        process.stdin.write(b"%s\n" % result_json)
            finally:
                if (task := asyncio.current_task()) is not None:
                    tasks.discard(task)

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
            await incoming.receive(agent, call_jsonrpc, tasks)
        unexpected = not self.stopping
        self.stopping = True
        agent.controller.connection_closed()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if process.returncode and unexpected:
            assert process.stderr is not None
            fail_details = (await process.stderr.read()).decode("utf-8", "replace")
            agent.post_message(
                AgentFail(
                    f"Agent returned a failure code: [b]{process.returncode}",
                    details=fail_details,
                )
            )
        if unexpected:
            await self.control.finish(process)
        self.process = None
