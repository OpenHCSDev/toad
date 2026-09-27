"""Provider-free, disposable Toad incarnation registry/controller pilot.

Run with PYTHONPATH=src python tests/cutover_retirement_pilot.py.  The test
callbacks are NOT a production MaintenanceBarrier token or EX authority.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import tempfile
from pathlib import Path

import psutil

from toad.acp.agent import Agent
from toad.acp.cutover_retirement import (
    LIVE_TOAD_REGISTRY,
    Registry,
    RetirementUnresolved,
    RootFenced,
    State,
)
from toad.acp.group_retirement import (
    AcceptedGroup,
    GroupRetirement,
    capture_accepted_group,
    signal_accepted_group,
    verify_accepted_group,
)


class ProcessAgent:
    def __init__(self, process: asyncio.subprocess.Process, accepted: AcceptedGroup):
        self.process = process
        self.accepted = accepted
        self.stop_started = asyncio.Event()
        self.stop_release = asyncio.Event()

    async def stop(self) -> GroupRetirement:
        self.stop_started.set()
        await self.stop_release.wait()
        signal_accepted_group(self.accepted, signal.SIGTERM)
        await self.process.wait()
        deadline = asyncio.get_running_loop().time() + 5
        while True:
            try:
                return verify_accepted_group(self.accepted)
            except Exception:
                if asyncio.get_running_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.02)

    def verify_retirement(self) -> GroupRetirement:
        return verify_accepted_group(self.accepted)


async def process_group_pilot(root: Path) -> None:
    # Real same-group grandchild and a deliberately escaped new-session child.
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import subprocess,sys,time; "
        "same=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdout=subprocess.DEVNULL); "
        "escaped=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdout=subprocess.DEVNULL,start_new_session=True); "
        "print(same.pid,escaped.pid,flush=True); time.sleep(60)",
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert process.stdout is not None
    same_pid, escaped_pid = map(
        int, (await asyncio.wait_for(process.stdout.readline(), timeout=5)).split()
    )
    accepted = capture_accepted_group(process.pid)
    assert os.getpgid(same_pid) == accepted.pgid
    assert os.getpgid(escaped_pid) != accepted.pgid
    escaped_identity = psutil.Process(escaped_pid).create_time()
    agent = ProcessAgent(process, accepted)
    registry = Registry()
    entry = registry.register_pre_spawn(agent, root, implicit=True)
    registry.mark_accepted(entry, accepted)
    assert entry.state is State.ACCEPTED
    try:
        fence = registry.fence_old_root(root)
        try:
            registry.require_open(root)
        except RootFenced:
            pass
        else:
            raise AssertionError("fenced old-root send was admitted")
        try:
            registry.register_pre_spawn(object(), root, implicit=False)
        except RootFenced:
            pass
        else:
            raise AssertionError("explicit old-root Toad start escaped local fence")

        # No external pause/exclusion assertions means DENY, even for a
        # seemingly empty or fully stopped registry.
        try:
            await registry.retire_enrolled(fence)
        except RetirementUnresolved:
            pass
        else:
            raise AssertionError("receipt minted without external PAUSE")
        assert process.returncode is None

        paused = True

        def assert_pause(check_root: Path) -> None:
            if not paused or check_root != root:
                raise RetirementUnresolved("disposable pause no longer current")

        escaped_active = True

        def assert_exclusions(
            check_root: Path, groups: tuple[AcceptedGroup, ...]
        ) -> None:
            assert check_root == root and groups == (accepted,)
            if (
                escaped_active
                and psutil.Process(escaped_pid).create_time() == escaped_identity
            ):
                raise RetirementUnresolved("escaped old-capable child still live")

        retire = asyncio.create_task(
            registry.retire_enrolled(
                fence,
                assert_pause_current=assert_pause,
                assert_exclusions_clear=assert_exclusions,
            )
        )
        await asyncio.wait_for(agent.stop_started.wait(), timeout=5)
        assert not retire.done()
        retire.cancel()
        try:
            await retire
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancelled retirement task reported success")
        assert entry.state is State.ACCEPTED and process.returncode is None
        retire = asyncio.create_task(
            registry.retire_enrolled(
                fence,
                assert_pause_current=assert_pause,
                assert_exclusions_clear=assert_exclusions,
            )
        )
        await asyncio.sleep(0)  # let the second disposable stop enter
        assert not retire.done()
        # An attempt to publish after an EX/PAUSE lapse must fail closed even
        # if the child subsequently exits.
        paused = False
        agent.stop_release.set()
        try:
            await asyncio.wait_for(retire, timeout=8)
        except RetirementUnresolved:
            pass
        else:
            raise AssertionError("PAUSE lapse minted a retirement receipt")
        assert entry.state is State.ACCEPTED  # not cleared on uncertainty

        paused = True
        try:
            await registry.retire_enrolled(
                fence,
                assert_pause_current=assert_pause,
                assert_exclusions_clear=assert_exclusions,
            )
        except RetirementUnresolved:
            pass
        else:
            raise AssertionError("known escaped child was certified")
        assert entry.state is State.RETIRED  # only enrolled PGID was retired
        # The independently observed escaped child is still live.  A separate
        # operator exclusion is required; this test explicitly retires it.
        assert psutil.Process(escaped_pid).create_time() == escaped_identity
        os.killpg(escaped_pid, signal.SIGKILL)
        escaped_active = False
        receipt = await registry.retire_enrolled(
            fence,
            assert_pause_current=assert_pause,
            assert_exclusions_clear=assert_exclusions,
        )
        assert receipt.publishable is False
        assert receipt.controller_epoch == registry._epoch
        assert receipt.toad_pid == os.getpid()
        assert receipt.accepted == (agent.verify_retirement(),)
        registry.assert_receipt_current(receipt, fence, assert_pause)
        paused = False
        try:
            registry.assert_receipt_current(receipt, fence, assert_pause)
        except RetirementUnresolved:
            pass
        else:
            raise AssertionError("stale PAUSE reused retirement receipt")
        paused = True
        registry.release_fence(fence)
        try:
            registry.assert_receipt_current(receipt, fence, assert_pause)
        except RetirementUnresolved:
            pass
        else:
            raise AssertionError("released fence reused retirement receipt")
    finally:
        agent.stop_release.set()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.returncode is None:
            await process.wait()
        try:
            if psutil.Process(escaped_pid).create_time() == escaped_identity:
                os.killpg(escaped_pid, signal.SIGKILL)
        except (ProcessLookupError, psutil.NoSuchProcess):
            pass


async def real_agent_stop_hook_pilot(root: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time;time.sleep(60)",
        start_new_session=True,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    agent = Agent(root, {"name": "fixture", "run_command": {"*": "true"}}, None)
    agent.post_message = lambda _message: None
    entry = LIVE_TOAD_REGISTRY.register_pre_spawn(agent, root, implicit=True)
    agent._retirement_entry = entry
    agent._process = process
    agent._process_group_id = process.pid
    agent._accepted_group = capture_accepted_group(process.pid)
    LIVE_TOAD_REGISTRY.mark_accepted(entry, agent._accepted_group)
    try:
        fence = LIVE_TOAD_REGISTRY.fence_old_root(root)
        receipt = await LIVE_TOAD_REGISTRY.retire_enrolled(
            fence,
            assert_pause_current=lambda _root: None,
            assert_exclusions_clear=lambda _root, _groups: None,
        )
        assert receipt.accepted == (agent.verify_retirement(),)
        assert entry.state is State.RETIRED
        LIVE_TOAD_REGISTRY.release_fence(fence)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.returncode is None:
            await process.wait()


async def pending_and_detached_pilot(root: Path) -> None:
    registry = Registry()

    class DormantAgent:
        async def stop(self):
            return None

        def verify_retirement(self):
            raise AssertionError("no child")

    agent = DormantAgent()
    entry = registry.register_pre_spawn(agent, root, implicit=True)
    del agent  # registry retains it after a tab can be detached
    fence = registry.fence_old_root(root)
    def pause(check_root: Path) -> None:
        assert check_root == root

    def exclusions(check_root: Path, groups: tuple[AcceptedGroup, ...]) -> None:
        assert check_root == root and groups == ()
    try:
        await registry.retire_enrolled(
            fence, assert_pause_current=pause, assert_exclusions_clear=exclusions
        )
    except RetirementUnresolved:
        pass
    else:
        raise AssertionError("pending start was certified as no child")
    try:
        registry.release_fence(fence)
    except RetirementUnresolved:
        pass
    else:
        raise AssertionError("pending child lost its fence")
    registry.mark_no_child(entry)  # only after actual admission settles
    receipt = await registry.retire_enrolled(
        fence, assert_pause_current=pause, assert_exclusions_clear=exclusions
    )
    assert receipt.accepted == () and not receipt.publishable
    registry.release_fence(fence)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="toad-retirement-", dir="/dev/shm") as tmp:
        root = Path(tmp).resolve()
        await pending_and_detached_pilot(root)
        await process_group_pilot(root)
        await real_agent_stop_hook_pilot(root)
    print("Toad live-incarnation cutover inventory pilot PASS (NON-PUBLISHABLE)")


if __name__ == "__main__":
    asyncio.run(main())
