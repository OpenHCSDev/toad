from agent_comms.acp_extension import QueuePromptRequest
"""Matched logical-session scaling with a real ACP/owner/Pi loopback path.

One native owner and one ACP attachment remain fixed across4/16/32/64 tabs.
This measures presentation scaling without changing the backend source cohort.
No Agent, transport, queue, editor or renderer method is mocked.
"""

import asyncio
import cProfile
import pstats
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
from toad.widgets.conversation import Conversation
from toad.widgets.side_bar import SideBar
from toad.widgets.session_tabs import SessionLabel
from toad.navigation_target import ThreadTarget


class InstalledApp(ToadApp):
    CSS_PATH = files("toad").joinpath("toad.tcss")


class PaintedSwitchApp(InstalledApp):
    """Observe production selection and actual composited output; never replace it."""
    observed_destination = None
    observed_started = None
    observed_frames = None
    observed_expected = None

    def select_session(self, mode, *, history_index=None):
        if mode == self.observed_destination and self.observed_started is None:
            self.observed_started = time.monotonic()
        return super().select_session(mode, history_index=history_index)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if (self.observed_started is not None and renderable is not None
                and not self._batch_count and screen is self.screen
                and self.selected_mode == self.observed_destination
                and screen.frame_presentation.ready):
            paint = "\n".join(strip.text for strip in screen._compositor.render_strips())
            if all(marker in paint for marker in self.observed_expected):
                self.observed_frames.append((time.monotonic() - self.observed_started) * 1000)


async def physical_painted_switch(app, pilot, mode, expected):
    tab = next(label for label in app.screen.query(SessionLabel) if label.id == mode)
    tab.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    app.observed_destination = mode
    app.observed_started = None
    app.observed_frames = []
    app.observed_expected = expected
    assert await pilot.click(tab), f"Tab {mode} was not physically clickable"
    await until(pilot, lambda: bool(app.observed_frames))
    frames = tuple(app.observed_frames)
    app.observed_destination = None
    app.observed_started = None
    return {"first_paint_ms": frames[0], "last_observed_paint_ms": frames[-1],
            "painted_frames": len(frames)}


def conversation_paint(screen):
    """Only actually composited strips inside the message reader viewport."""
    region = screen.app.selected_session.conversation.window.scrollable_content_region
    strips = screen._compositor.render_strips()
    return "\n".join(strip.crop(region.x, region.right).text
                     for strip in strips[region.y:region.bottom])


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
            "acp_rss_bytes": psutil.Process(acp_process.identity.pid).memory_info().rss}


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    workspace = app.screen
    owner_mode = app.selected_mode
    owner_view = app.selected_session
    original = app.selected_session.conversation
    editor = original.prompt.prompt_text_area
    original_editor = editor
    editor.insert("untouched native draft")
    editor.history.checkpoint()
    editor.insert(" with undo")
    document, history = editor.document, editor.history
    session_id = agent.session_id
    acp_process, acp_task = agent.process.process, agent.process.runner
    owner = comms.registry.require("beta").process_identity
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    alpha_mode = await ThreadTarget("alpha").open(owner_view.navigation_context)
    await until(pilot, lambda: "NATIVE_RESPONSE_1" in conversation_paint(app.screen))
    modes = [owner_mode, alpha_mode]
    loaded_modes = frozenset(modes)
    records = []
    markers = {owner_mode: ("untouched native draft with undo", "NATIVE_RESPONSE_2"),
               alpha_mode: ("NATIVE_RESPONSE_1",)}
    active_prompt = None
    try:
        for count in tuple(map(int, os.environ.get("WORKSPACE_COHORTS", "4,16,32,64").split(","))):
            while len(modes) < count:
                index = len(modes)
                details = await app.session_navigation.new(lambda: MainScreen(
                    original.project_path, agent_session_id=f"cohort-{index}"))
                modes.append(details.mode_name)
                marker = f"BLANK_TAB_DRAFT_{index}"
                app.selected_session.conversation.prompt.prompt_text_area.insert(marker)
                markers[details.mode_name] = (marker,)
                await pilot.pause(.02)
            # Each cohort uses the same three strict visit phases. Do not hide
            # a bad phase with the predecessor's optional diagnostic filtering.
            durations = []
            painted = []
            profile_path = os.environ.get("WORKSPACE_SWITCH_PROFILE")
            profiler = cProfile.Profile() if count == 4 and profile_path else None
            if profiler is not None:
                profiler.enable()
            for order in (tuple(reversed(modes)), tuple(modes), tuple(reversed(modes))):
                for mode in order:
                    if mode == app.selected_mode:
                        continue
                    timing = await physical_painted_switch(app, pilot, mode, markers[mode])
                    painted.append({"mode": mode, "source": "loaded-native" if mode in loaded_modes else "blank",
                                    **timing})
                    assert app.selected_mode == mode and app.selected_session.id == mode
                    assert app.screen is workspace, "Tab change replaced native WorkspaceScreen"
                    durations.append(timing["first_paint_ms"])
            if profiler is not None:
                profiler.disable()
                with Path(profile_path).open("w") as stream:
                    stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
                    stats.print_stats(55)
                    stats.print_callers("viewer_snapshot")
            await app.select_session(modes[-1])
            entered.clear()
            release.clear()
            hold_next.set()
            before_requests = len(requests)
            active_prompt = asyncio.create_task(agent.send_prompt(f"HELD_AT_{count}"))
            await until(pilot, entered.is_set)
            assert app.selected_mode != owner_mode
            assert agent._connected_ok
            assert agent.process.process is acp_process and acp_process.returncode is None
            assert agent.process.runner is acp_task and not acp_task.done()
            assert comms.registry.require("beta").process_identity == owner
            assert comms.registry.require("beta").executing
            await asyncio.wait_for(agent.send_prompt(f"QUEUED_AT_{count}", request=QueuePromptRequest(f"QUEUED_AT_{count}", True)), 10)
            await until(pilot, lambda: bool(agent.queue_attachment.projection.items))
            state = owner_view.presentation.state
            assert state is not None
            assert state.editor.document is document and state.editor.history is history
            assert state.editor.document.text == "untouched native draft with undo"
            rich_views = {id(view) for screen in app.workspace_sessions.views.values()
                          for view in screen.query("Conversation")}
            assert len(rich_views) == 1, "Inactive rich presentation escaped global admission"
            record = {
                "global_rich_views": len(rich_views),
                "tabs": count, "rss_bytes": psutil.Process().memory_info().rss,
                "tasks": len(asyncio.all_tasks()), "tracked_objects": len(gc.get_objects()),
                "constructed_panels": sum(len(app.workspace_sessions.require(mode).query_one(
                    "#thread-sidebar", SideBar).panels) for mode in modes),
                "switch_median_ms": statistics.median(durations),
                "switch_max_ms": max(durations),
                "switches_over_100ms": sum(value > 100 for value in durations),
                "switch_count": len(durations), "fixed_native_owners": 2,
                "fixed_acp_attachments": 2,
                "measurement": "physical Pilot tab click: production selection to first actual compositor output with destination draft; no fixed settle added, headless not terminal writer latency",
                "painted_switches": painted,
                "blank_median_ms": statistics.median(item["first_paint_ms"] for item in painted if item["source"] == "blank"),
                "loaded_median_ms": statistics.median(item["first_paint_ms"] for item in painted if item["source"] == "loaded-native"),
                **resource_snapshot(owner, acp_process),
            }
            release.set()
            await asyncio.wait_for(active_prompt, 25)
            active_prompt = None
            await until(pilot, lambda: not comms.registry.require("beta").executing)
            await until(pilot, lambda: not agent.queue_attachment.projection.items)
            assert len(requests) == before_requests + 2, "Queued prompt was lost or replayed"
            await app.select_session(owner_mode)
            await pilot.pause()
            original = app.selected_session.conversation
            editor = original.prompt.prompt_text_area
            assert editor is original_editor, "Source return rebuilt the native editor"
            assert original.agent is agent
            assert editor.document is document and editor.history is history
            assert editor.text == "untouched native draft with undo"
            expected = f"NATIVE_RESPONSE_{len(requests)}"
            try:
                await until(pilot, lambda: expected in conversation_paint(app.screen))
            except TimeoutError:
                print("RETURN_PAINT_FAILURE", json.dumps({
                    "expected": expected,
                    "page_events": [repr(event) for event in (await agent.get_transcript_page()).events],
                    "turn": repr(original.turns.owner),
                    "categories": sorted(case.__name__ for case in original.visible_categories),
                    "descendants": [(type(child).__name__, child.display, repr(child.region)) for child in original.contents.walk_children()],
                    "regions": {"conversation": repr(original.region), "window": repr(original.window.region), "contents": repr(original.contents.region)},
                    "children": [(type(child).__name__, child.display, repr(child.region), str(child.styles.display), list(child.classes)) for child in original.contents.children],
                    "paint": conversation_paint(app.screen),
                }), flush=True)
                raise
            markers[owner_mode] = ("untouched native draft with undo", expected)
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
    from thread_navigation_installed_journey import prepare as prepare_loaded_histories
    asyncio.run(native_fixture(app_type=PaintedSwitchApp, prepare_state=prepare_loaded_histories, acceptance=acceptance))
