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
from functools import partial
import json
import os
from pathlib import Path
import statistics
import sys
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
    observed_writer_frames = None

    def select_session(self, mode, *, history_index=None):
        if mode == self.observed_destination and self.observed_started is None:
            self.observed_started = time.monotonic()
        return super().select_session(mode, history_index=history_index)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        if (self.observed_started is not None and renderable is not None
                and not self._batch_count and screen is self.screen
                and self.selected_mode == self.observed_destination):
            paint = "\n".join(strip.text for strip in screen._compositor.render_strips())
            if all(marker in paint for marker in self.observed_expected):
                self.observed_frames.append((time.monotonic() - self.observed_started) * 1000)
                from functools import partial
                from toad.frame_presentation import FrameFlush
                FrameFlush.for_driver(self._driver).submit(partial(
                    self.record_written_destination, self.observed_started,
                    self.observed_destination))

    def record_written_destination(self, started, destination):
        if self.observed_started is started and self.selected_mode == destination:
            self.observed_writer_frames.append((time.monotonic() - started) * 1000)


async def physical_painted_switch(app, pilot, mode, expected):
    tab = next(label for label in app.screen.query(SessionLabel) if label.id == mode)
    tab.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    app.observed_destination = mode
    app.observed_started = None
    app.observed_frames = []
    app.observed_writer_frames = []
    app.observed_expected = expected
    assert await pilot.click(tab), f"Tab {mode} was not physically clickable"
    await until(pilot, lambda: bool(app.observed_frames) and bool(app.observed_writer_frames))
    frames = tuple(app.observed_frames)
    writes = tuple(app.observed_writer_frames)
    app.observed_destination = None
    app.observed_started = None
    return {"first_paint_ms": frames[0], "last_observed_paint_ms": frames[-1],
            "painted_frames": len(frames), "first_written_ms": writes[0],
            "last_observed_written_ms": writes[-1], "writer_receipts": len(writes),
            "driver": type(app._driver).__name__}


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


async def warm_admission_acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    """Actual loaded journals exercise shared native/source/paint admission.

    The existing fixture authors one localhost turn for each of two owners.
    This mode adds no input, queue or mixed/blank-tab scaling journey.
    """
    import hashlib
    from viewport_recent_tabs_pilot import ReaderCheckpoint, settled

    beta = app.selected_session
    original_files = {name: Path(comms.registry.require(name).session_file)
                      for name in ("alpha", "beta")}
    original_hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                       for name, path in original_files.items()}
    await until(pilot, lambda: "NATIVE_RESPONSE_2" in conversation_paint(app.screen))
    alpha_mode = await ThreadTarget("alpha").open(beta.navigation_context)
    await until(pilot, lambda: "NATIVE_RESPONSE_1" in conversation_paint(app.screen))
    sources = (beta, app.workspace_sessions.require(alpha_mode))
    checkpoints = {}
    witness = None
    ordered = admitted = roots = ()
    costs = {}
    widget = owner = painted_owner = None
    rows = []
    native = app.workspace_chrome.native
    try:
        for source in sources:
            await app.select_session(source.id)
            view = source.conversation
            await settled(pilot, view)
            assert view.window.histories and view.transcript.displayed_cursor is not None
            assert view.agent.session_id in original_files
            editor = view.prompt.prompt_text_area
            editor.insert(f"{view.agent.session_id} draft")
            editor.history.checkpoint()
            editor.insert(" with undo")
            assert view.window.max_scroll_y > 0
            view.window.release_anchor()
            view.window.scroll_to(y=min(5, view.window.max_scroll_y / 2),
                                  animate=False, immediate=True)
            await settled(pilot, view)
            assert not view.window.follows_tail
            checkpoints[source.id] = await ReaderCheckpoint.capture(source, app, pilot)

        # Each return consumes the witness from before departure. A genuine
        # native eviction restores editor/reader custody; a retained tree must
        # also retain the exact page/fragment/render identities and raw reads.
        for source in (*reversed(sources), *sources):
            retained = source.presentation.widget is not None
            witness = checkpoints[source.id]
            reads = await witness.page_reads()
            await app.select_session(source.id)
            view = source.conversation
            await settled(pilot, view)
            editor = view.prompt.prompt_text_area
            assert editor.document is witness.document and editor.history is witness.history
            assert editor.text == witness.text
            assert view.window.scroll_y == witness.reader_y
            assert view.window.follows_tail is witness.follows_tail
            if retained:
                await witness.verify(app, pilot)
                assert await witness.page_reads() == reads
            # Freeze this original resource before comparing admission with
            # native lifetime effects; no renderer/worker method is replaced.
            viewport = view.window.document_viewport
            await viewport.suspend_source()
            try:
                required = source.presentation
                presentations = {session.id: owner for session, owner in native._presentations()}
                ordered = dict.fromkeys((required, *(presentations[identity]
                    for identity in app.tab_order.recent if identity in presentations)))
                costs = {}
                for owner in ordered:
                    widget = owner.widget
                    manager = widget.window.document_viewport
                    roots = tuple(manager.body_roots())
                    assert set(roots) == set(manager.owners)
                    assert owner.retained_widget_count == 1 + widget.descendant_count
                    assert owner.retained_source_bytes == sum(body.retained_source_bytes for body in roots)
                    assert owner.retained_paint_bytes == sum(body.retained_paint_bytes for body in roots)
                    costs[owner] = (owner.retained_widget_count, owner.retained_source_bytes,
                                    owner.retained_paint_bytes)
                assert any(paint > 0 for widgets, source_bytes, paint in costs.values()), (
                    "Loaded fixture must exercise actual retained paint", costs,
                )
                painted_owner = next((owner for owner, (widgets, size, paint) in costs.items()
                                      if paint > 0 and widgets <= viewport.budget.widget_limit(app.size.height)), None)
                assert painted_owner is not None, "Paint accounting needs a native tree that fits the widget budget"
                # Exercise the existing policy on actual mounted resources at
                # their source-only byte boundary. No application budget is
                # modified: paint must exclude a tree whose widgets fit.
                assert not viewport.budget.admit(
                    (painted_owner,), (), app.size.height, painted_owner.retained_source_bytes,
                )
                admitted = viewport.budget.admit(ordered, (required,), app.size.height,
                                                  app.preparation.max_bytes)
                await native._trim_retained(view)
                assert required.widget is view
                assert {owner for _, owner in native._presentations()} == admitted
                rows.append({"selected": source.id, "warm_return": retained,
                             "resources": [{"widgets": widgets, "source_bytes": size,
                                            "paint_bytes": paint, "admitted": owner in admitted}
                                           for owner, (widgets, size, paint) in costs.items()]})
            finally:
                viewport.resume_source()
            await pilot.press("ctrl+z")
            assert editor.text == witness.text.removesuffix(" with undo")
            editor.redo()
            assert editor.text == witness.text
    finally:
        checkpoints.clear()
        witness = None
        ordered = admitted = roots = ()
        costs.clear()
        widget = owner = painted_owner = None
    del checkpoints, witness, ordered, admitted, costs, roots, widget, owner, painted_owner
    assert len(requests) == 2, "Read-only mounted admission replayed native input"
    assert {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in original_files.items()} == original_hashes
    Path(os.environ["NATIVE_RETENTION_RECEIPT"]).write_text(json.dumps({
        "scope": "two genuinely loaded native journals; authored localhost input only",
        "rows": rows, "native_inputs": len(requests), "history_scaling_4_16_32_64": "UNRUN",
    }, indent=2) + "\n")


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    from viewport_recent_tabs_pilot import ReaderCheckpoint

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
            # Capture the two actual unchanged native sources before this
            # cohort; blank logical tabs are not loaded-history witnesses.
            checkpoints = {}
            try:
                for mode in (owner_mode, alpha_mode):
                    if app.selected_mode != mode:
                        await physical_painted_switch(app, pilot, mode, markers[mode])
                    checkpoints[mode] = await ReaderCheckpoint.capture(
                        app.selected_session, app, pilot,
                    )
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
                        if mode in checkpoints:
                            reads_before = await checkpoints[mode].page_reads()
                        timing = await physical_painted_switch(app, pilot, mode, markers[mode])
                        painted.append({"mode": mode, "source": "loaded-native" if mode in loaded_modes else "blank",
                                        **timing})
                        if mode in checkpoints:
                            await checkpoints[mode].verify(app, pilot)
                            read_delta = await checkpoints[mode].page_reads() - reads_before
                            assert read_delta == 0, ("Warm return repeated raw page acquisition", mode, read_delta)
                            painted[-1]["raw_page_read_delta"] = read_delta
                            painted[-1]["warm_page_fragments_and_rendered_rows_retained"] = True
                        assert app.selected_mode == mode and app.selected_session.id == mode
                        assert app.screen is workspace, "Tab change replaced native WorkspaceScreen"
                        durations.append(timing["first_paint_ms"])
                if profiler is not None:
                    profiler.disable()
                    with Path(profile_path).open("w") as stream:
                        stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
                        stats.print_stats(55)
                        stats.print_callers("viewer_snapshot")
                # Retain scalar evidence before retiring the identity witnesses.
                loaded_reader_positions = {mode: witness.reader_y
                                           for mode, witness in checkpoints.items()}
            finally:
                # The warm proof ends here, before new input and resource counts.
                # Empty the graph owners even when an identity assertion fails.
                checkpoints.clear()
            del checkpoints
            await app.select_session(modes[-1])
            entered.clear()
            release.clear()
            hold_next.set()
            before_requests = len(requests)
            active_prompt = asyncio.create_task(agent.send_prompt(f"HELD_AT_{count}"))
            await until(pilot, entered.is_set)
            assert app.selected_mode != owner_mode
            assert agent.session.connected
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
                "unchanged_loaded_resource_returns": sum(
                    item.get("warm_page_fragments_and_rendered_rows_retained", False)
                    for item in painted
                ),
                "loaded_reader_positions": loaded_reader_positions,
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
    if sys.argv[1:] == ["--warm-admission-only"]:
        asyncio.run(native_fixture(app_type=PaintedSwitchApp,
                                   prepare_state=partial(prepare_loaded_histories, long_history=True),
                                   acceptance=warm_admission_acceptance))
    elif not sys.argv[1:]:
        asyncio.run(native_fixture(app_type=PaintedSwitchApp, prepare_state=prepare_loaded_histories, acceptance=acceptance))
    else:
        raise SystemExit("usage: native_session_retention_pilot.py [--warm-admission-only]")
