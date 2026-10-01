"""Installed ACP callback dispatch and real PTYs with a detached native session."""
import asyncio
from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import sys

from agent_comms.child_process import ProcessIdentity

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import conversation_paint
from runtime_fixture import ToadApp
from saved_state_user_journey_pilot import click_tab
from toad.widgets.terminal_tool import TerminalTool


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def pty_masters():
    """Observe this real application's PTY resources, not its private fields."""
    descriptors = set()
    for descriptor in Path("/proc/self/fd").iterdir():
        try:
            target = descriptor.readlink()
        except FileNotFoundError:
            continue  # A real descriptor can retire during observation.
        if str(target) == "/dev/pts/ptmx":
            descriptors.add(int(descriptor.name))
    return descriptors


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    mode = app.selected_session.id
    process, runner = agent.process.process, agent.process.runner
    owner = comms.registry.require("beta").process_identity
    request_id = 0
    terminals = agent.controller.terminals
    initial_pty_masters = pty_masters()
    evidence = Path(os.environ["L0A_EVIDENCE"])

    async def request(method, **params):
        nonlocal request_id
        request_id += 1
        return await agent.server.call({
            "jsonrpc": "2.0", "id": request_id, "method": method,
            "params": {"sessionId": agent.session_id, **params},
        })

    async def rpc(method, **params):
        response = await request(method, **params)
        assert "error" not in response, response
        return response["result"]

    async def command_identity(terminal_id, marker):
        execution = terminals.require(terminal_id)
        await until(pilot, lambda: any(
            line.content.plain.startswith(marker)
            for line in execution.state.buffer.lines
        ))
        output = await rpc("terminal/output", terminalId=terminal_id)
        line = next(line for line in output["output"].splitlines()
                    if line.startswith(marker))
        return ProcessIdentity.capture(int(line.partition("=")[2]))

    first = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep 1; printf 'ACTIVE_THEN_DETACHED\\n'"]))["terminalId"]
    execution = terminals.require(first)
    original_state = execution.state
    await app.session_navigation.new(app.session_navigation.default_source)
    assert agent.controller.surface.target is None
    second = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep .1; printf 'CREATED_WHILE_DETACHED\\n'"]))["terminalId"]
    assert (await rpc("terminal/wait_for_exit", terminalId=first))["exitCode"] == 0
    assert (await rpc("terminal/wait_for_exit", terminalId=second))["exitCode"] == 0
    assert "ACTIVE_THEN_DETACHED" in (await rpc("terminal/output", terminalId=first))["output"]
    assert "CREATED_WHILE_DETACHED" in (await rpc("terminal/output", terminalId=second))["output"]
    assert execution.outcome.finished and execution.outcome.successful
    assert agent.process.process is process and process.returncode is None
    assert agent.process.runner is runner and not runner.done()
    assert comms.registry.require("beta").process_identity == owner

    await click_tab(app, pilot, mode)
    await until(pilot, lambda: len(app.screen.query(TerminalTool)) == 2)
    assert agent.controller.surface.target is app.selected_session.conversation
    assert app.screen.query_one(f"#{first}", TerminalTool).state is original_state
    await until(pilot, lambda: "CREATED_WHILE_DETACHED" in conversation_paint(app.screen))
    app.save_screenshot("terminal-reattached.svg", path=str(evidence))
    assert pty_masters() == initial_pty_masters

    # A cancelled wait is an observer cancellation, not a second process owner.
    doomed = (await rpc("terminal/create", command="sh", args=[
        "-c", "printf 'TERMINAL_CHILD_PID=%s\\n' \"$$\"; exec sleep 30"
    ]))["terminalId"]
    running = terminals.require(doomed)
    child = await command_identity(doomed, "TERMINAL_CHILD_PID=")
    assert child.alive() and not running.outcome.finished
    waiter = asyncio.create_task(rpc("terminal/wait_for_exit", terminalId=doomed))
    try:
        await pilot.pause()
        assert not waiter.done()
        waiter.cancel()
        cancellation, = await asyncio.gather(waiter, return_exceptions=True)
        assert isinstance(cancellation, asyncio.CancelledError)
        assert child.alive() and not running.outcome.finished
    finally:
        if not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    await rpc("terminal/kill", terminalId=doomed)
    killed = await rpc("terminal/wait_for_exit", terminalId=doomed)
    assert killed["signal"] == signal.Signals(signal.SIGKILL).name
    assert (await rpc("terminal/output", terminalId=doomed))["exitStatus"] == killed
    assert running.outcome.finished and not running.outcome.successful
    assert not child.alive()

    # A byte bound may cut through a UTF-8 scalar, including its entire tail.
    bounded = (await rpc("terminal/create", command=sys.executable, args=[
        "-c", "import sys; sys.stdout.buffer.write('😀'.encode('utf-8'))"
    ], outputByteLimit=2))["terminalId"]
    assert (await rpc("terminal/wait_for_exit", terminalId=bounded))["exitCode"] == 0
    bounded_output = await rpc("terminal/output", terminalId=bounded)
    assert bounded_output["truncated"] is True
    assert bounded_output["output"] == ""
    assert len(bounded_output["output"].encode("utf-8")) <= 2
    assert "😀" in "\n".join(line.content.plain for line in
                              terminals.require(bounded).state.buffer.lines)

    # A missing cwd is a real spawn failure; an unknown command merely exits.
    before_failed_create = frozenset(terminals.executions)
    before_failed_pty = pty_masters()
    absent = Path(app.project_dir) / "terminal-startup-directory-that-does-not-exist"
    assert not absent.exists()
    failure = await request("terminal/create", command="sh", args=["-c", "printf unused"],
                            cwd=str(absent))
    assert "error" in failure, failure
    assert frozenset(terminals.executions) == before_failed_create
    assert pty_masters() == before_failed_pty

    await rpc("terminal/release", terminalId=second)
    assert second not in terminals.executions
    assert "error" in await request("terminal/output", terminalId=second)

    released = (await rpc("terminal/create", command="sh", args=[
        "-c", "printf 'RELEASE_CHILD_PID=%s\\n' \"$$\"; exec sleep 30"
    ]))["terminalId"]
    released_child = await command_identity(released, "RELEASE_CHILD_PID=")
    assert released_child.alive()
    await rpc("terminal/release", terminalId=released)
    assert released not in terminals.executions and not released_child.alive()
    assert "error" in await request("terminal/output", terminalId=released)

    await terminals.close()
    assert execution.outcome.finished and execution.outcome.successful
    assert not terminals.executions and pty_masters() == initial_pty_masters
    assert not requests, "Terminal-only acceptance made a model request"
    assert comms.registry.require("beta").process_identity == owner and owner.alive()
    (evidence / "terminal-lifecycle-acceptance.json").write_text(json.dumps({
        "normal_exit": {"exitCode": 0}, "signal_exit": killed,
        "cancelled_wait_preserves_original_process": True,
        "bounded_utf8": bounded_output,
        "failed_startup": failure,
        "released_child": {"pid": released_child.pid, "alive": released_child.alive()},
        "controller_addresses_after_close": len(terminals.executions),
        "pty_masters_before": sorted(initial_pty_masters),
        "pty_masters_after": sorted(pty_masters()),
        "provider_requests": len(requests),
        "native_owner_preserved": True,
    }, indent=2) + "\n")
    print("NATIVE_ACP_TERMINALS_RETAINED_AND_PAINTED", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(
        app_type=InstalledApp, acceptance=acceptance, headless=False,
        provider_request_budget=0,
        fixture_stage=Path(os.environ["TOAD_TERMINAL_FIXTURE_ROOT"]),
    ))
