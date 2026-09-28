"""Matched logical-session scaling with a real ACP/owner/Pi loopback path.

One native owner and one ACP attachment remain fixed across4/16/32/64 tabs.
This measures presentation scaling without changing the backend source cohort.
No Agent, transport, queue, editor or renderer method is mocked.
"""

import asyncio
import gc
from importlib.resources import files
import json
import os
from pathlib import Path
import statistics
import time

import psutil

from runtime_fixture import ToadApp
from l0a_native_installed_pilot import main as native_fixture, until
from toad.screens.main import MainScreen
from toad.widgets.side_bar import SideBar


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


def resource_snapshot(owner, acp_process):
    """Sample this UI's descendants and its explicitly registered native owner."""
    ui = psutil.Process()
    native = psutil.Process(owner.pid)
    processes = {process.pid: process for process in (
        ui, *ui.children(recursive=True), native, *native.children(recursive=True))}
    rss = {}
    for pid, process in processes.items():
        try:
            rss[pid] = process.memory_info().rss
        except psutil.NoSuchProcess:
            continue  # An independent renderer child may finish during sampling.
    return {"scope_rss_bytes": sum(rss.values()), "scope_processes": len(rss),
            "native_owner_rss_bytes": native.memory_info().rss,
            "acp_rss_bytes": psutil.Process(acp_process.pid).memory_info().rss}


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    owner_mode = app.current_mode
    original = app.screen.conversation
    editor = original.prompt.prompt_text_area
    editor.insert("untouched native draft")
    editor.history.checkpoint()
    editor.insert(" with undo")
    document, history = editor.document, editor.history
    session_id = agent.session_id
    acp_process, acp_task = agent.process.process, agent.process.runner
    owner = comms.registry.require("beta").process_identity
    modes = [owner_mode]
    records = []
    active_prompt = None
    try:
        for count in (4, 16, 32, 64):
            while len(modes) < count:
                index = len(modes)
                details = await app.new_session_screen(lambda: MainScreen(
                    original.project_path, agent_session_id=f"cohort-{index}"))
                modes.append(details.mode_name)
                await pilot.pause(.02)
            # Each cohort uses the same three strict visit phases. Do not hide
            # a bad phase with the predecessor's optional diagnostic filtering.
            durations = []
            for order in (tuple(reversed(modes)), tuple(modes), tuple(reversed(modes))):
                for mode in order:
                    if mode == app.current_mode:
                        continue
                    before = time.monotonic()
                    await app.switch_mode(mode)
                    await pilot.pause(.02)
                    assert app.current_mode == mode and app.screen.id == mode
                    durations.append((time.monotonic() - before) * 1000)
            await app.switch_mode(modes[-1])
            entered.clear()
            release.clear()
            hold_next.set()
            before_requests = len(requests)
            active_prompt = asyncio.create_task(agent.send_prompt(f"HELD_AT_{count}"))
            await until(pilot, entered.is_set)
            assert app.current_mode != owner_mode
            assert agent._connected_ok
            assert agent.process.process is acp_process and acp_process.returncode is None
            assert agent.process.runner is acp_task and not acp_task.done()
            assert comms.registry.require("beta").process_identity == owner
            assert comms.registry.require("beta").executing
            await asyncio.wait_for(agent.send_prompt(f"QUEUED_AT_{count}", defer_display=True), 10)
            await until(pilot, lambda: bool(agent.queue_attachment.projection.items))
            assert editor.document is document and editor.history is history
            assert editor.text == "untouched native draft with undo"
            rich_views = {id(view) for stack in app._screen_stacks.values()
                          for screen in stack for view in screen.query("Conversation")}
            assert len(rich_views) == 1, "Inactive rich presentation escaped global admission"
            record = {
                "global_rich_views": len(rich_views),
                "tabs": count, "rss_bytes": psutil.Process().memory_info().rss,
                "tasks": len(asyncio.all_tasks()), "tracked_objects": len(gc.get_objects()),
                "constructed_panels": sum(len(app.get_screen_stack(mode)[0].query_one(
                    "#thread-sidebar", SideBar).panels) for mode in modes),
                "switch_median_ms": statistics.median(durations),
                "switch_max_ms": max(durations),
                "switches_over_100ms": sum(value > 100 for value in durations),
                "switch_count": len(durations), "fixed_native_owners": 1,
                "fixed_acp_attachments": 1,
                "measurement": "headless switch completion plus20ms pilot settle; not native terminal latency",
                **resource_snapshot(owner, acp_process),
            }
            release.set()
            await asyncio.wait_for(active_prompt, 25)
            active_prompt = None
            await until(pilot, lambda: not comms.registry.require("beta").executing)
            await until(pilot, lambda: not agent.queue_attachment.projection.items)
            assert len(requests) == before_requests + 2, "Queued prompt was lost or replayed"
            await app.switch_mode(owner_mode)
            await pilot.pause()
            original = app.screen.conversation
            editor = original.prompt.prompt_text_area
            assert original.agent is agent
            assert editor.document is document and editor.history is history
            assert editor.text == "untouched native draft with undo"
            expected = f"NATIVE_RESPONSE_{len(requests)}"
            try:
                await until(pilot, lambda: expected in "\n".join(
                    strip.text for strip in app.screen._compositor.render_strips()))
            except TimeoutError:
                print("RETURN_PAINT_FAILURE", json.dumps({
                    "expected": expected,
                    "turn": repr(original.turns.owner),
                    "categories": sorted(case.__name__ for case in original.visible_categories),
                    "regions": {"conversation": repr(original.region), "window": repr(original.window.region), "contents": repr(original.contents.region)},
                    "children": [(type(child).__name__, child.display, repr(child.region), str(child.styles.display), list(child.classes)) for child in original.contents.children],
                    "paint": "\n".join(strip.text for strip in app.screen._compositor.render_strips()),
                }), flush=True)
                raise
            record["native_calls"] = len(requests) - before_requests
            record["native_answer_painted"] = True
            records.append(record)
            print("NATIVE_RETAINED", json.dumps(record), flush=True)
        editor.undo()
        assert editor.text == "untouched native draft"
        editor.redo()
        assert editor.text == "untouched native draft with undo"
        assert agent.session_id == session_id
        Path(os.environ["NATIVE_RETENTION_RECEIPT"]).write_text(json.dumps(records, indent=2))
    finally:
        release.set()
        if active_prompt is not None and not active_prompt.done():
            active_prompt.cancel()
            await asyncio.gather(active_prompt, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance))
