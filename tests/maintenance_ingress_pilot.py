"""Disposable provider-free Toad/Comms maintenance admission pilot.

Run against the paired candidate core source, not the installed old dependency.
"""

import asyncio
import os
import shlex
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent_comms.maintenance_barrier import MaintenanceBarrier
from toad.acp.agent import Agent
from toad.acp.maintenance_ingress import admitted_spawn, barrier_for, preflight
from toad.agent import AgentFail


async def main() -> None:
    with TemporaryDirectory(prefix="toad-maintenance-fake-") as directory:
        root = Path(directory)
        wire = root / "wire"
        wire.mkdir()
        project = root / "project"
        project.mkdir()
        events = []
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(wire)}):
            agent = Agent(project, {"name": "fake", "run_command": {"*": "true"}}, None)
            agent.post_message = events.append
            assert barrier_for().read() is None  # default OFF on never-enabled wire
            assert barrier_for(str(wire)).read() is None
            assert barrier_for(str(root / "another-wire")).registry_path != barrier_for().registry_path

            spawned = asyncio.Event()
            allow_spawn = asyncio.Event()

            async def fake_spawn(_command, **_kwargs):
                spawned.set()
                await allow_spawn.wait()
                return SimpleNamespace(pid=123, returncode=0)

            with patch("asyncio.create_subprocess_shell", fake_spawn):
                first = asyncio.create_task(admitted_spawn("fake", stdin=None))
                await asyncio.wait_for(spawned.wait(), timeout=5)
                pause = asyncio.create_task(asyncio.to_thread(barrier_for().begin, "test-operator"))
                await asyncio.sleep(0.02)
                assert not pause.done(), "pause acknowledged while ACP spawn was unsettled"
                agent._process = SimpleNamespace(stdin=SimpleNamespace(write=lambda _: None))
                pending_prompt = SimpleNamespace(body={"method": "session/prompt"}, body_json=b"{}")
                try:
                    agent.send(pending_prompt)
                except ValueError as error:
                    assert "spawn admission" in str(error)
                else:
                    raise AssertionError("prompt blocked the event loop while spawn held wire lock")
                allow_spawn.set()
                assert (await asyncio.wait_for(first, timeout=5)).pid == 123
                receipt = await asyncio.wait_for(pause, timeout=5)
                assert receipt.phase == "draining"
                try:
                    await admitted_spawn("must-not-spawn")
                except Exception:
                    pass
                else:
                    raise AssertionError("ACP spawn admitted after durable pause")

            sent = []
            agent._process = SimpleNamespace(stdin=SimpleNamespace(write=sent.append))
            prompt = SimpleNamespace(body={"jsonrpc": "2.0", "method": "session/prompt"},
                                     body_json=b'{"method":"session/prompt"}')
            try:
                agent.send(prompt)
            except Exception:
                pass
            else:
                raise AssertionError("prompt admitted after durable pause")
            assert not sent, "paused prompt reached ACP stdin"
            agent.stop = AsyncMock()
            try:
                await agent.reconnect()
            except ValueError:
                pass
            else:
                raise AssertionError("reconnect admitted after durable pause")
            agent.stop.assert_not_awaited()
            await agent.start()
            assert agent._agent_task is None
            assert any(isinstance(event, AgentFail) for event in events)

    # Cancellation during an unsettled fake spawn retains admission until the
    # spawned process is known and retired; an uncertain spawn cannot be lost.
    with TemporaryDirectory(prefix="toad-maintenance-cancel-") as directory:
        root = Path(directory)
        entered = asyncio.Event()
        released = asyncio.Event()
        retired = asyncio.Event()
        retire_started = asyncio.Event()
        allow_retire = asyncio.Event()

        class FakeChild:
            returncode = None

            def terminate(self):
                retire_started.set()

            async def wait(self):
                await allow_retire.wait()
                self.returncode = -15
                retired.set()
                return self.returncode

        async def delayed_spawn(_command, **_kwargs):
            entered.set()
            await released.wait()
            return FakeChild()

        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(root)}), patch(
            "asyncio.create_subprocess_shell", delayed_spawn
        ):
            attempt = asyncio.create_task(admitted_spawn("fake"))
            await asyncio.wait_for(entered.wait(), timeout=5)
            attempt.cancel()
            pause = asyncio.create_task(asyncio.to_thread(barrier_for().begin, "test-operator"))
            await asyncio.sleep(0.02)
            attempt.cancel()  # A second cancel must not abandon a future child.
            await asyncio.sleep(0.02)
            assert not attempt.done() and not pause.done()
            released.set()
            await asyncio.wait_for(retire_started.wait(), timeout=5)
            assert not pause.done(), "pause acknowledged before cancelled child retired"
            allow_retire.set()
            try:
                await asyncio.wait_for(attempt, timeout=5)
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("cancelled spawn was treated as accepted")
            assert retired.is_set()
            assert (await asyncio.wait_for(pause, timeout=5)).phase == "draining"

    # A mounted second wire can never bypass the default ingress gate, and its
    # own pause also denies its prompts without changing the default root.
    with TemporaryDirectory(prefix="toad-maintenance-mount-") as directory:
        root = Path(directory)
        default = root / "default"
        mounted = root / "mounted"
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(default)}):
            preflight(str(mounted))
            barrier_for(str(mounted)).begin("test-operator")
            try:
                preflight(str(mounted))
            except Exception:
                pass
            else:
                raise AssertionError("mounted paused wire accepted")
            preflight()  # Unrelated default remains open.

    # Relative wire root is resolved against the exact child cwd. A changed
    # parent environment cannot redirect the check away from the copied env.
    with TemporaryDirectory(prefix="toad-maintenance-child-root-") as directory:
        root = Path(directory)
        parent = root / "parent"
        child = root / "child"
        parent.mkdir()
        child.mkdir()
        MaintenanceBarrier(child / "wire" / "registry.json").begin("test-operator")
        called = []

        async def must_not_spawn(*_args, **_kwargs):
            called.append(True)
            raise AssertionError("paused child root reached subprocess")

        previous = Path.cwd()
        try:
            os.chdir(parent)
            with patch.dict(os.environ, {"AGENT_COMMS_ROOT": "wire"}), patch(
                "asyncio.create_subprocess_shell", must_not_spawn
            ):
                try:
                    await admitted_spawn("fake", env=os.environ.copy(), cwd=str(child))
                except Exception:
                    pass
                else:
                    raise AssertionError("relative paused child wire was admitted")
        finally:
            os.chdir(previous)
        assert not called
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(root / "new")}), patch(
            "asyncio.create_subprocess_shell", must_not_spawn
        ):
            try:
                await admitted_spawn("fake", env={"AGENT_COMMS_ROOT": str(child / "wire")}, cwd=str(child))
            except Exception:
                pass
            else:
                raise AssertionError("copied paused child env was ignored")
        assert not called

    # A child's HOME, not Toad's HOME, controls default ~/ wire resolution.
    with TemporaryDirectory(prefix="toad-maintenance-home-") as directory:
        root = Path(directory)
        child_home = root / "child-home"
        MaintenanceBarrier(child_home / ".agent-comms" / "registry.json").begin("test-operator")
        calls = []

        async def record_spawn(*_args, **_kwargs):
            calls.append(True)
            return SimpleNamespace(pid=123, returncode=0)

        with patch.dict(os.environ, {"HOME": str(root / "parent-home")}), patch(
            "asyncio.create_subprocess_shell", record_spawn
        ):
            try:
                await admitted_spawn("fake", env={"HOME": str(child_home)}, cwd=str(root))
            except Exception:
                pass
            else:
                raise AssertionError("child HOME paused gate bypassed")
        assert not calls

    # The child receives the same canonical target that Toad admitted, even
    # when an alias changes while its process is being created.
    with TemporaryDirectory(prefix="toad-maintenance-alias-") as directory:
        root = Path(directory)
        opened = root / "open"
        paused = root / "paused"
        alias = root / "wire-link"
        opened.mkdir()
        alias.symlink_to(opened, target_is_directory=True)
        MaintenanceBarrier(paused / "registry.json").begin("test-operator")
        observed = []

        async def retarget(_command, **kwargs):
            alias.unlink()
            alias.symlink_to(paused, target_is_directory=True)
            observed.append(Path(kwargs["env"]["AGENT_COMMS_ROOT"]).resolve())
            return SimpleNamespace(pid=123, returncode=0)

        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(alias)}), patch(
            "asyncio.create_subprocess_shell", retarget
        ):
            await admitted_spawn("fake", env=os.environ.copy(), cwd=str(root))
        assert observed == [opened], "ACP child followed a retargeted alias"

        attached = root / "attached"
        attached.mkdir()
        alias.unlink()
        alias.symlink_to(attached, target_is_directory=True)
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(opened)}):
            attached_agent = Agent(root, {"name": "fake", "run_command": {"*": "true"}}, None)
            attached_agent._maintenance_env = os.environ.copy()
            attached_agent._maintenance_cwd = str(root)
            attached_agent._publish_coordination_metadata(
                {"_meta": {"agentComms": {"thread": "fixture", "wireRoot": str(alias)}}}
            )
            assert attached_agent._coordination_root == str(attached)
        alias.unlink()
        alias.symlink_to(paused, target_is_directory=True)
        assert attached_agent._coordination_root == str(attached)

    # First-use ordinary path remains open through the actual Toad Agent path;
    # the disposable shell emits a marker, not a provider request.
    with TemporaryDirectory(prefix="toad-maintenance-open-") as directory:
        root = Path(directory)
        marker = root / "fake-acp-started"
        command = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
            f"from pathlib import Path; Path({str(marker)!r}).write_text('started')"
        )
        with patch.dict(os.environ, {"AGENT_COMMS_ROOT": str(root)}):
            agent = Agent(root, {"name": "fake", "run_command": {"*": command}}, None)
            agent.run = AsyncMock()
            await agent.start()
            assert agent._agent_task is not None
            await asyncio.wait_for(agent._agent_task, timeout=5)
            assert marker.read_text() == "started"
            barrier_for().begin("test-operator")
            marker.unlink()
            denied = Agent(root, {"name": "fake", "run_command": {"*": command}}, None)
            denied.post_message = lambda _: None
            await denied.start()
            assert denied._agent_task is None
            assert not marker.exists(), "paused Toad spawned ACP shell"

    print("Toad maintenance ingress: default-off, spawn/pause, paused prompt/reconnect/start, real fake Toad ACP path: PASS")


if __name__ == "__main__":
    asyncio.run(main())
