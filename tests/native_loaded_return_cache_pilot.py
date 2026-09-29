"""Two loaded actual Pi/ACP histories return without replay or source-state loss."""
import asyncio
import cProfile
import pstats
import traceback
import json
import os
from pathlib import Path
from time import perf_counter
from weakref import ref

from agent_comms.threads import Thread
from agent_comms.goal_actions import SetGoalAction
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from toad.widgets.session_tabs import SessionLabel
from viewport_recent_tabs_pilot import settled
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse
from toad.widgets.conversation import Conversation
from toad.widgets.conversation import TurnActivity
from toad.widgets.prompt import Prompt
from toad.widgets.throbber import Throbber
from toad.widgets.transcript_history import TranscriptFragmentView
from textual.widget import Widget
from textual.content import Content
from toad.acp.messages import UpdateStatusLine


class PaintedReturnApp(InstalledApp):
    """Capture every actual compositor frame during native tab selection."""

    observed_frames = None
    expected_source_id = None
    first_paint_at = None
    selection_requested_at = None
    last_click_metrics = None

    def select_session(self, mode, *, history_index=None):
        if mode == self.expected_source_id and self.selection_requested_at is None:
            self.selection_requested_at = perf_counter()
        return super().select_session(mode, history_index=history_index)

    def _display(self, screen, renderable):
        super()._display(screen, renderable)
        # Textual calls _display inside batch_update but discards that frame.
        # Only a completed display is an observable first paint.
        if (self.observed_frames is not None and renderable is not None
                and not self._batch_count and screen is self.screen):
            if self.selected_mode == self.expected_source_id and self.first_paint_at is None:
                self.first_paint_at = perf_counter()
            view = self.selected_session.query_one_optional(Conversation)
            agent = view.agent if view is not None else None
            self.observed_frames.append((
                self.selected_mode, conversation_paint(screen),
                "\n".join(strip.text for strip in screen._compositor.render_strips()),
                agent is None or view.status == agent.context_measurement.status(),
                agent is None or view.turns.owner.busy == agent.current_turn.busy,
            ))


async def click_session(app, pilot, source):
    tab = next(label for label in app.screen.query(SessionLabel) if label.id == source.id)
    tab.scroll_visible(animate=False, immediate=True)
    await pilot.pause()
    app.observed_frames = []
    app.expected_source_id = source.id
    app.first_paint_at = None
    app.selection_requested_at = None
    phases = {}
    wrapped = []
    previous = app.workspace_sessions.selected
    native = app.workspace_chrome.native
    conversation = native.widget
    viewport = conversation.window.document_viewport if conversation is not None else None
    targets = [
        (previous, "retire_presentation", "retire_presentation"),
        (app.workspace_chrome, "select", "chrome_select"),
        (source, "prepare_presentation", "prepare_presentation"),
        (native, "retire", "native_retire"),
        (native, "activate", "native_activate"),
        (viewport, "park_source", "viewport_park_source"),
        (viewport, "suspend_source", "viewport_suspend_source"),
        (conversation, "release_native_session", "conversation_release"),
        (conversation, "bind_native_session", "conversation_bind"),
        (conversation, "present_retained_native_session", "conversation_present_retained"),
        (app.workspace_screen, "prepare_navigation", "prepare_navigation"),
        (app.workspace_screen, "layout_navigation", "layout_navigation"),
    ]
    for owner, method, label in targets:
        if owner is None:
            continue
        original = getattr(owner, method)

        async def timed(*args, _original=original, _label=label, **kwargs):
            started = perf_counter()
            try:
                return await _original(*args, **kwargs)
            finally:
                phases[_label] = phases.get(_label, 0.0) + (perf_counter() - started) * 1000

        setattr(owner, method, timed)
        wrapped.append((owner, method, original))
    click_started = perf_counter()
    try:
        assert await pilot.click(tab), f"Session tab {source.id} was not clickable"
    finally:
        for owner, method, original in reversed(wrapped):
            setattr(owner, method, original)
    click_completed = perf_counter()
    assert app.first_paint_at is not None, f"Session tab {source.id} never painted"
    assert app.selection_requested_at is not None, f"Session tab {source.id} was not selected"
    app.last_click_metrics = (
        (app.first_paint_at - click_started) * 1000,
        (click_completed - click_started) * 1000,
        (app.first_paint_at - app.selection_requested_at) * 1000,
    )
    app.last_phase_times = phases
    frames, app.observed_frames = app.observed_frames, None
    app.expected_source_id = None
    return frames


async def acceptance(app, pilot, beta, comms, entered, release, hold_next, requests):
    frame = app.screen
    release.set()
    sources = [app.selected_session]
    agents = [beta]
    records = []
    await sources[0].wait_content_ready()
    await until(pilot, lambda: sources[0].conversation.query_one_optional(Prompt) is not None)
    comms.registry.declare(Thread("gamma", frozenset({"team"}), str(beta.project_root_path),
                                  model="selected-offline/fixture", thinking_level="off"))
    try:
        prompt_count = int(os.environ.get("NATIVE_RETURN_PROMPTS", "2"))
        for name in ("beta", "gamma"):
            if name == "gamma":
                await app.session_navigation.new(lambda: MainScreen(
                    beta.project_root_path, agent=sources[0]._agent, agent_session_id="gamma"))
                source = app.selected_session
                sources.append(source)
                await until(pilot, lambda: source.conversation.agent is not None)
                agents.append(source.conversation.agent)
                await until(pilot, agents[-1].session.settled.is_set)
            agent = agents[-1]
            view = app.selected_session.conversation
            await until(pilot, lambda: view.agent_ready and view.queue_projection.status == "available")
            for index in range(prompt_count):
                prompt = f"CACHE_{name.upper()}_{index}\n\n" + "\n\n".join(
                    f"{name} saved reader paragraph {row}: **canonical loaded source**."
                    for row in range(12))
                before_requests = len(requests)
                editor = view.prompt.prompt_text_area
                editor.scroll_visible(animate=False, immediate=True)
                await pilot.pause()
                assert await pilot.click(editor)
                editor.insert(prompt)
                await pilot.press("enter")
                await until(pilot, lambda: len(requests) == before_requests + 1)
                await until(pilot, lambda: not comms.registry.require(name).executing)
                await until(pilot, lambda: not agent.current_turn.busy)
            comms.goals.update_goal(name, SetGoalAction(text=f"SELECTED_GOAL_{name.upper()}"))
        # Both now have durable, actually produced native journals. Establish
        # comparable reader/editor state only after ordinary saved publication.
        states = {}
        for source_index, (source, agent) in enumerate(zip(sources, agents)):
            print("CACHE_BEFORE_SELECT", source.id,
                  [(type(k().parent).__name__, getattr(k().identity.source,"session_id",None),
                    k().identity.interval.before.offset,k().identity.interval.through.offset,
                    k().identity.directory_revision,k().body_ready,
                    1+sum(1 for _ in k().walk_children()))
                   for k in app.selected_session.conversation.window.document_viewport._warm.values()
                   if k() is not None and isinstance(k(),TranscriptFragmentView)],flush=True)
            frames = await click_session(app, pilot, source)
            view = source.conversation
            await until(pilot, lambda: bool(view.window.histories) and view.transcript.displayed_cursor is not None)
            await view.goal_observation.refresh()
            assert view.goal_display.snapshot is not None
            assert view.goal_display.snapshot.text == f"SELECTED_GOAL_{agent.session_id.upper()}"
            print("SOURCE_READY_PAINT", source.id, agent.ready, view.agent_ready, view.classes,
                  view.window.document_viewport.visible_bodies_ready,
                  [(type(node).__name__, node.region) for node in app.screen._compositor.visible_widgets
                   if node in view.window.document_viewport.owners],
                  "FRAME", "\n".join(strip.text for strip in app.screen._compositor.render_strips()), flush=True)
            print("WINDOW_LAYOUT", [(type(n).__name__, n.display, str(n.styles.height), n.region, n.size, n.virtual_size) for n in view.window.walk_children() if n.parent is view.window or n in view.contents.ancestors_with_self], flush=True)
            print("SOURCE_BODY_CUSTODY", source.id, view.window.scroll_y, view.window.max_scroll_y,
                  view.window.document_viewport.reuse_hits,
                  [(type(node).__name__, type(node.parent).__name__, node.visible, node.display,
                    node._closing, node._pruning, node.is_running,
                    app.screen._compositor._full_map.get(node))
                   for history in view.window.histories for node in history.walk_children()
                   if isinstance(node, TranscriptFragmentView)], flush=True)
            await until(pilot, lambda: f"NATIVE_RESPONSE_{prompt_count * (source_index + 1)}" in conversation_paint(frame))
            await until(pilot, lambda: view.window.max_scroll_y > 0)
            await settled(pilot, view)
            view.window.release_anchor()
            view.window.scroll_to(y=min(5, view.window.max_scroll_y / 2), animate=False, immediate=True)
            await settled(pilot, view)
            assert not view.window.follows_tail and view.window.scroll_y < view.window.max_scroll_y, (
                view.window.scroll_y, view.window.max_scroll_y,
                [(type(node).__name__, node.size, node.virtual_size) for node in view.window.histories],
                conversation_paint(frame),
                repr(app._exception),
                [(type(node).__name__, len(node.children), node.is_mounted, node.display,
                  node.size, node.virtual_size, str(node.styles.height), node.loading)
                 for history_view in view.window.histories for node in history_view.walk_children()],
                [(type(node).__name__, node.size, node.virtual_size, node.display, node.loading)
                 for node in view.window.ancestors_with_self if isinstance(node, Widget)],
                [(node._body_dormant, node._body_measurement, node._body_measurement_stale)
                 for node in view.query(TranscriptFragmentView)],
            )
            editor = view.prompt.prompt_text_area
            editor.insert(f"draft-{source.id}")
            editor.history.checkpoint()
            editor.insert(" with undo")
            states[source.id] = (view.window.scroll_y, conversation_paint(frame), editor.document,
                                 editor.history, agent.process.process, agent.process.runner,
                                 tuple(ref(body) for body in view.query(AgentResponse)
                                       if body in frame._compositor.visible_widgets
                                       and body.region.overlaps(view.window.scrollable_content_region)))
            assert states[source.id][-1], "Saved reader fixture must contain a painted response"
        native_calls = len(requests)
        assert native_calls == 2 * prompt_count
        profile = cProfile.Profile() if os.environ.get("NATIVE_RETURN_PROFILE") == "1" else None
        if profile is not None:
            profile.enable()
        for source, agent in ((sources[0], agents[0]), (sources[1], agents[1]),
                              (sources[0], agents[0]), (sources[1], agents[1]), (sources[0], agents[0])):
            before_hits, before_misses = app.preparation.hits, app.preparation.misses
            viewport = app.workspace_chrome.native.widget.window.document_viewport
            before_reuse, before_evictions = viewport.reuse_hits, viewport.body_evictions
            started = perf_counter()
            print("CACHE_BEFORE_SELECT", source.id,
                  [(type(k().parent).__name__, getattr(k().identity.source,"session_id",None),
                    k().identity.interval.before.offset,k().identity.interval.through.offset,
                    k().identity.directory_revision,k().body_ready,
                    1+sum(1 for _ in k().walk_children()))
                   for k in app.selected_session.conversation.window.document_viewport._warm.values()
                   if k() is not None and isinstance(k(),TranscriptFragmentView)],flush=True)
            frames = await click_session(app, pilot, source)
            view = source.conversation
            await until(pilot, lambda: bool(view.window.histories))
            y, painted, document, history, process, runner, old_bodies = states[source.id]
            print("FIRST_FRAMES", source.id,
                  [(mode, len(reader.strip()), "NATIVE_RESPONSE" in reader,
                    "Earlier history" in reader) for mode, reader, _full, _status, _turn in frames[:8]], flush=True)
            destination_frames = [frame for frame in frames if frame[0] == source.id]
            reader_marker = f"{agent.session_id} saved reader paragraph"
            other_reader = "gamma saved reader paragraph" if agent.session_id == "beta" else "beta saved reader paragraph"
            assert destination_frames and reader_marker in destination_frames[0][1] and other_reader not in destination_frames[0][1], (
                "First painted return frame did not show the destination reader",
                source.id, [(mode, reader[:200]) for mode, reader, _full, _status, _turn in frames[:3]],
            )
            goal_text = f"SELECTED_GOAL_{agent.session_id.upper()}"
            other_goal = f"SELECTED_GOAL_{'GAMMA' if agent.session_id == 'beta' else 'BETA'}"
            assert goal_text in destination_frames[0][2] and other_goal not in destination_frames[0][2], (
                "First painted return frame showed another agent's goal",
                source.id, destination_frames[0][2][-1800:],
            )
            assert destination_frames[0][3] and destination_frames[0][4], (
                "First painted status or turn belonged to another agent", source.id,
            )
            assert "Loading new thread" not in destination_frames[0][2]
            try:
                await until(pilot, lambda: conversation_paint(frame) == painted)
            except TimeoutError:
                print("FAILED_RETURN", source.id, "reader", view.window.scroll_y, y,
                      "reuse", view.window.document_viewport.reuse_hits,
                      "expected", painted, "actual", conversation_paint(frame),
                      "layout", [(type(n).__name__, n.display, n.region, n.size, n.virtual_size)
                                 for n in view.window.walk_children()
                                 if n.parent is view.window or n in view.contents.ancestors_with_self],
                      "cached", [(type(k()).__name__, type(k().parent).__name__, k().identity)
                                 for k in view.window.document_viewport._warm.values() if k() is not None], flush=True)
                raise
            await settled(pilot, view)
            print("RETURN_GEOMETRY", source.id, view.window.scroll_y, view.window.max_scroll_y,
                  [(type(node).__name__, node.size, node.virtual_size, node.display)
                   for history_view in view.window.histories for node in history_view.walk_children()
                   if type(node).__name__ in {"TranscriptPageView", "TranscriptFragmentView", "AgentResponse"}],
                  "REUSE", view.window.document_viewport.reuse_hits,
                  "PAINT", conversation_paint(frame), flush=True)
            assert view.window.scroll_y == y, (view.window.scroll_y, y)
            assert conversation_paint(frame) == painted
            editor = view.prompt.prompt_text_area
            assert editor.document is document and editor.history is history
            assert view.agent is agent and agent.process.process is process and agent.process.runner is runner
            assert len(requests) == native_calls, "Tab return replayed input"
            assert app.preparation.retained_bytes <= app.preparation.max_bytes
            bodies = tuple(body for body in view.query(AgentResponse)
                           if body in frame._compositor.visible_widgets
                           and body.region.overlaps(view.window.scrollable_content_region))
            reused = sum(any(previous() is body for previous in old_bodies) for body in bodies)
            if reused == 0:
                print("CACHE_MISS_ROOTS", [(getattr(n.identity.source,"session_id",None),
                     n.identity.interval.before.offset,n.identity.interval.through.offset,
                     n.identity.directory_revision,n.body_ready,
                     type(n.parent).__name__) for n in view.query(TranscriptFragmentView)],flush=True)
            assert reused > 0, ("Already-loaded native source discarded every response body", source.id)
            records.append({"source":source.id,
                            "return_painted_ms":app.last_click_metrics[0],
                            "click_completed_ms":app.last_click_metrics[1],
                            "selection_to_paint_ms":app.last_click_metrics[2],
                            "phases_ms":app.last_phase_times,
                            "fixture_total_ms":(perf_counter()-started)*1000,
                            "reader_y":y,"cache_hits":app.preparation.hits-before_hits,
                            "cache_misses":app.preparation.misses-before_misses,
                            "mounted_response_bodies":len(bodies),
                            "reused_body_instances":reused,
                            "retained_body_reuse_hits":viewport.reuse_hits-before_reuse,
                            "retained_body_evictions":viewport.body_evictions-before_evictions,
                            "warm_bodies":sum(key() is not None for key in viewport._warm.values()),
                            "prepared_bytes":app.preparation.retained_bytes})
        if profile is not None:
            profile.disable()
            with Path(os.environ["NATIVE_RETURN_RECEIPT"]).with_suffix(".profile.txt").open("w") as stream:
                pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(60)
        for source in sources:
            await app.select_session(source.id)
            editor = source.conversation.prompt.prompt_text_area
            editor.undo()
            assert editor.text == f"draft-{source.id}"
        await app.select_session(sources[0].id)
        entered.clear()
        release.clear()
        hold_next.set()
        held = asyncio.create_task(agents[1].send_prompt("ACTIVE_GAMMA_RETURN"))
        await until(pilot, entered.is_set)
        await until(pilot, lambda: agents[1].current_turn.busy)
        beta_view = sources[0].conversation
        assert not beta_view.turns.owner.busy
        assert not beta_view.query_one(TurnActivity).visible
        assert not beta_view.query_one(Throbber).busy
        assert not beta_view.prompt.agent_busy and not beta_view.prompt.prompt_text_area.agent_busy
        active_started = perf_counter()
        active_frames = await click_session(app, pilot, sources[1])
        active_return_ms = (perf_counter() - active_started) * 1000
        selected_active = [frame for frame in active_frames if frame[0] == sources[1].id]
        print("ACTIVE_RETURN_MS", round(active_return_ms, 1), flush=True)
        print("ACTIVE_FIRST_FRAME", selected_active[0][1][:700] if selected_active else "none",
              selected_active[0][2][-700:] if selected_active else "none", flush=True)
        assert selected_active and selected_active[0][3] and selected_active[0][4]
        assert ("gamma saved reader paragraph" in selected_active[0][1]
                or "ACTIVE_GAMMA_RETURN" in selected_active[0][1])
        assert "beta saved reader paragraph" not in selected_active[0][1]
        assert "SELECTED_GOAL_GAMMA" in selected_active[0][2]
        assert "Thinking" in selected_active[0][2]
        assert sources[1].conversation.turns.owner.busy
        assert sources[1].conversation.prompt.agent_busy
        assert sources[1].conversation.prompt.prompt_text_area.agent_busy
        # A status event queued by the departing source may reach the shared
        # widget after it is rebound. Its content has no destination identity.
        sources[1].conversation.post_message(UpdateStatusLine(Content("STALE_BETA_STATUS")))
        await pilot.pause()
        assert sources[1].conversation.status == agents[1].context_measurement.status()
        assert "STALE_BETA_STATUS" not in "\n".join(
            strip.text for strip in frame._compositor.render_strips())
        release.set()
        await asyncio.wait_for(held, 25)
        await until(pilot, lambda: not agents[1].current_turn.busy)
        await until(pilot, lambda: not sources[1].conversation.turns.owner.busy)
        settled_view = sources[1].conversation
        assert not settled_view.query_one(TurnActivity).visible
        assert not settled_view.query_one(Throbber).busy
        assert not settled_view.prompt.agent_busy and not settled_view.prompt.prompt_text_area.agent_busy
        await click_session(app, pilot, sources[0])
        await click_session(app, pilot, sources[1])
        assert not sources[1].conversation.query_one(TurnActivity).visible
        assert not sources[1].conversation.query_one(Throbber).busy
        assert len(requests) == native_calls + 1
        assert app.screen is frame and app._exception is None
        Path(os.environ["NATIVE_RETURN_RECEIPT"]).write_text(json.dumps(records,indent=2))
        print("TWO_LOADED_NATIVE_ABABA_FULL_PAINT_READER_EDITOR_UNDO_CUSTODY_NO_REPLAY", records, flush=True)
    except BaseException:
        traceback.print_exc()
        raise
    finally:
        release.set()
        for agent in agents[1:]:
            await agent.stop()
        await asyncio.to_thread(comms.owners.stop,"gamma")


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=PaintedReturnApp, acceptance=acceptance,
                               provider_request_budget=2 * int(os.environ.get("NATIVE_RETURN_PROMPTS", "2")) + 2))
