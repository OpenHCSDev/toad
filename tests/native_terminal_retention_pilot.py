"""Installed ACP callback dispatch and real PTYs with a detached native session."""
import asyncio
import argparse
from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from unittest.mock import patch

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

    first = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep 1; printf 'ACTIVE_THEN_DETACHED\\n'"]))["terminalId"]
    execution = terminals.require(first)
    original_state = execution.state
    original_custody = await execution.custody()
    await app.session_navigation.new(app.session_navigation.default_source)
    assert agent.controller.surface.target is None
    second = (await rpc("terminal/create", command="sh", args=[
        "-c", "sleep .1; printf 'CREATED_WHILE_DETACHED\\n'"]))["terminalId"]
    assert (await rpc("terminal/wait_for_exit", terminalId=first))["exitCode"] == 0
    assert (await rpc("terminal/wait_for_exit", terminalId=second))["exitCode"] == 0
    assert "ACTIVE_THEN_DETACHED" in (await rpc("terminal/output", terminalId=first))["output"]
    assert "CREATED_WHILE_DETACHED" in (await rpc("terminal/output", terminalId=second))["output"]
    assert execution.outcome.finished and execution.outcome.successful
    assert original_custody.child.process.returncode == 0 and original_custody.master.closed
    assert original_custody.child.retired
    assert agent.process.process is process and process.returncode is None
    assert agent.process.runner is runner and not runner.done()
    assert comms.registry.require("beta").process_identity == owner

    await click_tab(app, pilot, mode)
    await until(pilot, lambda: len(app.screen.query(TerminalTool)) == 2)
    assert agent.controller.surface.target is app.selected_session.conversation
    assert app.screen.query_one(f"#{first}", TerminalTool).state is original_state
    assert await execution.custody() is original_custody
    await until(pilot, lambda: "CREATED_WHILE_DETACHED" in conversation_paint(app.screen))
    app.save_screenshot("terminal-reattached.svg", path=str(evidence))
    assert pty_masters() == initial_pty_masters

    # A cancelled wait is an observer cancellation, not a second process owner.
    doomed = (await rpc("terminal/create", command="sleep", args=["30"]))["terminalId"]
    running = terminals.require(doomed)
    running_custody = await running.custody()
    child = running_custody.child.identity
    assert child.alive() and not running.outcome.finished
    waiter = asyncio.create_task(rpc("terminal/wait_for_exit", terminalId=doomed))
    try:
        await pilot.pause()
        assert not waiter.done()
        waiter.cancel()
        cancellation, = await asyncio.gather(waiter, return_exceptions=True)
        assert isinstance(cancellation, asyncio.CancelledError)
        assert child.alive() and not running.outcome.finished
        assert await running.custody() is running_custody
    finally:
        if not waiter.done():
            waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    await rpc("terminal/kill", terminalId=doomed)
    killed = await rpc("terminal/wait_for_exit", terminalId=doomed)
    assert killed["signal"] == signal.Signals(signal.SIGKILL).name
    assert (await rpc("terminal/output", terminalId=doomed))["exitStatus"] == killed
    assert running.outcome.finished and not running.outcome.successful
    assert not child.alive() and running_custody.master.closed
    assert running_custody.child.process.returncode == -signal.SIGKILL
    assert running_custody.child.retired

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

    released = (await rpc("terminal/create", command="sleep", args=["30"]))["terminalId"]
    released_custody = await terminals.require(released).custody()
    released_child = released_custody.child.identity
    assert released_child.alive()
    await rpc("terminal/release", terminalId=released)
    assert released not in terminals.executions and not released_child.alive()
    assert released_custody.master.closed
    assert released_custody.child.retired
    assert "error" in await request("terminal/output", terminalId=released)

    # Cancellation belongs to the request; original retirement still joins.
    interrupted = (await rpc("terminal/create", command="sleep", args=["30"]))["terminalId"]
    interrupted_execution = terminals.require(interrupted)
    interrupted_custody = await interrupted_execution.custody()
    interrupted_child = interrupted_custody.child.identity
    releasing = asyncio.create_task(rpc("terminal/release", terminalId=interrupted))
    await asyncio.sleep(0)  # Enter the real handler, without a screen barrier.
    assert terminals.require(interrupted) is interrupted_execution
    assert releasing.cancel(), "Release settled before the cancellation observation"
    await asyncio.sleep(0)  # Deliver the first cancellation at its original await.
    assert releasing.cancel(), "Repeated cancellation was not exercised"
    release_cancellation, = await asyncio.gather(releasing, return_exceptions=True)
    assert isinstance(release_cancellation, asyncio.CancelledError)
    assert releasing.cancelling() == 2
    assert interrupted not in terminals.executions
    assert interrupted_execution.outcome.finished
    assert interrupted_custody.master.closed and not interrupted_child.alive()
    assert interrupted_custody.child.retired
    assert "error" in await request("terminal/output", terminalId=interrupted)

    # Original creation publishes its execution before yielding to PTY spawn.
    # Cancel at that real await, preserving whichever acquisition actually won.
    before_startup = frozenset(terminals.executions)
    before_startup_pty = pty_masters()
    starting = asyncio.create_task(rpc("terminal/create", command="sleep", args=["30"]))
    await asyncio.sleep(0)
    startup_ids = frozenset(terminals.executions) - before_startup
    assert len(startup_ids) == 1 and not starting.done(), "Startup phase was not observed"
    startup_id, = startup_ids
    startup_execution = terminals.require(startup_id)
    acquisition = asyncio.create_task(startup_execution.custody())
    assert starting.cancel()
    startup_cancellation, = await asyncio.gather(starting, return_exceptions=True)
    assert isinstance(startup_cancellation, asyncio.CancelledError)
    try:
        acquired = await acquisition
    except asyncio.CancelledError:
        startup_observation = {"acquisition": "refused_before_custody"}
    else:
        assert acquired.master.closed and acquired.child.process.returncode is not None
        assert acquired.child.retired
        startup_observation = {
            "acquisition": "original_custody_joined", "pid": acquired.child.identity.pid,
            "return_code": acquired.child.process.returncode, "pty_closed": acquired.master.closed,
        }
    assert startup_id not in terminals.executions and startup_execution.outcome.finished
    assert frozenset(terminals.executions) == before_startup
    assert pty_masters() == before_startup_pty

    # Leader completion cannot retire a group whose descendant still owns IO.
    descendant_id = (await rpc("terminal/create", command="sh", args=[
        "-c", "(trap '' HUP TERM; sleep 30) & exit 0"
    ]))["terminalId"]
    descendant_execution = terminals.require(descendant_id)
    descendant_custody = await descendant_execution.custody()
    group_owner = descendant_custody.child
    await until(pilot, lambda: group_owner.process.returncode == 0)
    survivors = group_owner.platform.group_members(group_owner.identity)
    assert survivors, "The exited-leader/living-descendant phase was not exercised"
    assert not group_owner.retired and not descendant_custody.master.closed
    assert not descendant_execution.outcome.finished
    await rpc("terminal/release", terminalId=descendant_id)
    assert descendant_id not in terminals.executions
    assert group_owner.retired and descendant_custody.master.closed
    assert not group_owner.platform.group_members(group_owner.identity)
    assert all(not survivor.alive() for survivor in survivors)
    assert "error" in await request("terminal/output", terminalId=descendant_id)

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
        "released_child": {"pid": released_child.pid, "alive": released_child.alive(),
                           "pty_closed": released_custody.master.closed},
        "cancelled_release": {"cancellations": releasing.cancelling(),
                              "pid": interrupted_child.pid, "alive": interrupted_child.alive(),
                              "pty_closed": interrupted_custody.master.closed,
                              "address_present": interrupted in terminals.executions},
        "cancelled_startup": startup_observation,
        "exited_leader_descendant": {
            "leader_pid": group_owner.identity.pid,
            "leader_return_code": group_owner.process.returncode,
            "observed_survivors": [survivor.pid for survivor in survivors],
            "group_retired": group_owner.retired,
            "pty_closed": descendant_custody.master.closed,
            "address_present": descendant_id in terminals.executions,
        },
        "controller_addresses_after_close": len(terminals.executions),
        "pty_masters_before": sorted(initial_pty_masters),
        "pty_masters_after": sorted(pty_masters()),
        "provider_requests": len(requests),
        "native_owner_preserved": True,
    }, indent=2) + "\n")
    print("NATIVE_ACP_TERMINALS_RETAINED_AND_PAINTED", flush=True)


async def damage_journey():
    """Registered ACP, real streaming PTY and native App; no model provider."""
    from agent_comms.comms import Comms
    from toad.acp.agent import Agent
    from toad.agent_schema import AgentDefinition

    evidence = Path(os.environ["L0A_EVIDENCE"]).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    projections = []
    present = TerminalTool.present_execution

    def observe(terminal, scrollback, alternate):
        projections.append({
            "scrollback": None if scrollback is None else sorted(scrollback),
            "alternate": None if alternate is None else sorted(alternate),
            "screen": terminal.state.alternate_screen,
            "cursor": terminal.state.show_cursor,
            "finished": terminal.execution.outcome.finished,
        })
        present(terminal, scrollback, alternate)
        (evidence / "projections.json").write_text(json.dumps(projections, indent=2) + "\n")

    # The child blocks on actual PTY input between independently painted chunks.
    program = """
import sys, termios
settings = termios.tcgetattr(0)
settings[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, settings)
for output in ('INITIAL_BODY\\r\\nUNCHANGED_BODY',
               '\\x1b[1;1HREPLACED_BODY\\x1b[K',
               '\\x1b[?25l',
               '\\x1b[?1049h\\x1b[2J\\x1b[HALT_ACTIVE',
               '\\x1b[?1049l',
               '\\r\\nDETACHED_BODY',
               '\\r\\nFINAL_BODY',
               '\\x1b[2JAFTER_CLEAR',
               '\\x1b[1;6H\\x1b[J',
               '\\r\\n\\r\\n'):
    sys.stdout.write(output)
    sys.stdout.flush()
    sys.stdin.readline()
sys.exit(7)
"""
    initial_descriptors = pty_masters()
    with tempfile.TemporaryDirectory(prefix="terminal-damage-", dir=".artifacts") as directory:
        root = Path(directory).resolve()
        command_file = root / "terminal_output.py"
        command_file.write_text(program)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"),
                          XDG_STATE_HOME=str(root / "state"),
                          XDG_DATA_HOME=str(root / "data"),
                          AGENT_COMMS_ROOT=str(root / "wire"))
        Comms(root / "wire").messaging.initialize_private_initial_protocol()
        app = InstalledApp(project_dir=str(root))
        async with app.run_test(size=(100, 35)) as pilot:
            await app.selected_session.wait_content_ready()
            mode = app.selected_session.id
            agent = Agent(root, AgentDefinition.decode({
                "name": "Fixture", "identity": "fixture", "short_name": "fixture",
                "run_command": {"*": "true"}, "protocol": "acp",
            }), "fixture")
            app.selected_session.conversation.agent = agent
            request_id = 0

            async def rpc(method, **params):
                nonlocal request_id
                request_id += 1
                response = await agent.server.call({
                    "jsonrpc": "2.0", "id": request_id, "method": method,
                    "params": {"sessionId": agent.session_id, **params},
                })
                assert "error" not in response, response
                return response["result"]

            try:
                with patch.object(TerminalTool, "present_execution", observe):
                    terminal_id = (await rpc("terminal/create", command=sys.executable,
                                             args=["-u", str(command_file)]))["terminalId"]
                    execution = agent.controller.terminals.require(terminal_id)
                    original_state = execution.state
                    custody = await execution.custody()
                    child = custody.child.identity
                    await until(pilot, lambda: "UNCHANGED_BODY" in conversation_paint(app.screen))
                    assert projections[0]["scrollback"] is projections[0]["alternate"] is None
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: "REPLACED_BODY" in conversation_paint(app.screen))
                    assert "UNCHANGED_BODY" in conversation_paint(app.screen)
                    assert any(p["scrollback"] and p["alternate"] == [] for p in projections)
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: not original_state.show_cursor)
                    await pilot.pause()
                    assert any(p["cursor"] is False and p["scrollback"] for p in projections)
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: "ALT_ACTIVE" in conversation_paint(app.screen))
                    assert any(p["screen"] and p["scrollback"] is p["alternate"] is None
                               for p in projections)
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: not original_state.alternate_screen)
                    await pilot.pause()
                    assert "REPLACED_BODY" in conversation_paint(app.screen)
                    app.save_screenshot("stream.svg", path=str(evidence))

                    await app.session_navigation.new(app.session_navigation.default_source)
                    assert agent.controller.surface.target is None
                    projected_before = len(projections)
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: "DETACHED_BODY" in "\n".join(
                        line.content.plain for line in original_state.buffer.lines))
                    assert len(projections) == projected_before
                    assert child.alive() and await execution.custody() is custody
                    await click_tab(app, pilot, mode)
                    await until(pilot, lambda: "DETACHED_BODY" in conversation_paint(app.screen))
                    terminal = app.screen.query_one(f"#{terminal_id}", TerminalTool)
                    assert terminal.state is original_state
                    assert len(projections) > projected_before
                    assert projections[-1]["scrollback"] is projections[-1]["alternate"] is None
                    assert await execution.custody() is custody
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: "FINAL_BODY" in conversation_paint(app.screen))
                    app.save_screenshot("resumed-stream.svg", path=str(evidence))
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: "AFTER_CLEAR" in conversation_paint(app.screen))
                    assert "FINAL_BODY" not in conversation_paint(app.screen)
                    assert projections[-1]["scrollback"] is None
                    # ANSI positioning is screen-relative. Keep the cleared
                    # screen intact until the child finishes its next write.
                    await execution.write_stdin("\n")
                    await until(pilot, lambda: original_state.scrollback_buffer.lines[0].content.plain == "AFTER")
                    await pilot.pause()
                    frame = conversation_paint(app.screen)
                    assert "AFTER" in frame and "AFTER_CLEAR" not in frame
                    assert projections[-1]["scrollback"] is None
                    await execution.write_stdin("\n")
                    # The terminal may leave the cursor on a virtual final
                    # row. Qualify an actual stored blank, not newline count.
                    await until(pilot, lambda: (
                        original_state.scrollback_buffer.line_count > 1
                        and not original_state.scrollback_buffer.lines[-1].content.plain
                    ))
                    await execution.write_stdin("\n")
                    assert (await rpc("terminal/wait_for_exit", terminalId=terminal_id))["exitCode"] == 7
                    await until(pilot, lambda: terminal.is_finalized)
                    assert projections[-1]["finished"]
                    assert projections[-1]["scrollback"] is projections[-1]["alternate"] is None
                    assert terminal.has_class("-error") and "[7]" in str(terminal.border_title)
                    assert custody.master.closed and custody.child.retired and not child.alive()
                    # Final-output trimming removes rows only after the PTY
                    # writer retires; no later ANSI command recreates them.
                    original_state.remove_trailing_blank_lines_from_scrollback()
                    scrollback = original_state.scrollback_buffer.consume_updates()
                    assert scrollback is None and original_state.scrollback_buffer.line_count == 1
                    terminal.project_state(scrollback, original_state.alternate_buffer.consume_updates())
                    await pilot.pause()
                    assert original_state.scrollback_buffer.lines[0].content.plain == "AFTER"
                    assert "AFTER" in conversation_paint(app.screen)
                    app.save_screenshot("reattached-completed.svg", path=str(evidence))
                    await rpc("terminal/release", terminalId=terminal_id)
                    assert not agent.controller.terminals.executions
                    assert pty_masters() == initial_descriptors
                    assert app._exception is None
            except BaseException:
                app.save_screenshot("failed.svg", path=str(evidence))
                if agent.controller.terminals.executions:
                    execution = next(iter(agent.controller.terminals.executions.values()))
                    (evidence / "failed-state.json").write_text(json.dumps({
                        "buffer": [line.content.plain for line in execution.state.buffer.lines],
                        "terminal_presentations": projections,
                        "outcome": type(execution.outcome).__name__,
                        "paint": conversation_paint(app.screen),
                    }, indent=2) + "\n")
                raise
            finally:
                await agent.stop()
        await asyncio.get_running_loop().shutdown_default_executor()
    (evidence / "projections.json").write_text(json.dumps(projections, indent=2) + "\n")
    print(json.dumps({"result": "pass", "projections": len(projections),
                      "provider_calls": 0, "remaining_pty_masters": sorted(pty_masters()),
                      "initial_pty_masters": sorted(initial_descriptors)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--damage-only", action="store_true")
    args = parser.parse_args()
    asyncio.run(damage_journey() if args.damage_only else native_fixture(
        app_type=InstalledApp, acceptance=acceptance, headless=False,
        provider_request_budget=0,
        fixture_stage=Path(os.environ["TOAD_TERMINAL_FIXTURE_ROOT"]),
    ))
