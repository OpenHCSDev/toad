"""Two loaded actual Pi/ACP histories return without replay or source-state loss."""
import asyncio
import cProfile
import pstats
import json
import os
from pathlib import Path
from time import perf_counter
from weakref import ref

from agent_comms.threads import Thread
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from viewport_recent_tabs_pilot import settled
from toad.screens.main import MainScreen
from toad.widgets.agent_response import AgentResponse


async def acceptance(app, pilot, beta, comms, entered, release, hold_next, requests):
    frame = app.screen
    release.set()
    sources = [app.selected_session]
    agents = [beta]
    records = []
    comms.threads.register(Thread("gamma", frozenset({"team"}), str(beta.project_root_path),
                                  model="selected-offline/fixture", thinking_level="off"))
    try:
        for name in ("beta", "gamma"):
            if name == "gamma":
                await app.new_session_screen(lambda: MainScreen(
                    beta.project_root_path, agent=sources[0]._agent, agent_session_id="gamma"))
                source = app.selected_session
                sources.append(source)
                await until(pilot, lambda: source.conversation.agent is not None)
                agents.append(source.conversation.agent)
                await until(pilot, agents[-1].session_ready_event.is_set)
            agent = agents[-1]
            for index in range(2):
                prompt = f"CACHE_{name.upper()}_{index}\n\n" + "\n\n".join(
                    f"{name} saved reader paragraph {row}: **canonical loaded source**."
                    for row in range(12))
                await asyncio.wait_for(agent.send_prompt(prompt), 25)
                await until(pilot, lambda: not comms.registry.require(name).executing)
        # Both now have durable, actually produced native journals. Establish
        # comparable reader/editor state only after ordinary saved publication.
        states = {}
        for source, agent in zip(sources, agents):
            await app.select_session(source.id)
            view = source.conversation
            await until(pilot, lambda: bool(view.window.histories) and view.transcript.displayed_cursor is not None)
            await settled(pilot, view)
            view.window.release_anchor()
            view.window.scroll_to(y=min(5, view.window.max_scroll_y / 2), animate=False, immediate=True)
            await settled(pilot, view)
            assert not view.window.follows_tail and view.window.scroll_y < view.window.max_scroll_y, (
                view.window.scroll_y, view.window.max_scroll_y,
                [(type(node).__name__, node.size, node.virtual_size) for node in view.window.histories],
                conversation_paint(frame),
                repr(app._exception),
                [(type(node).__name__, len(node.children), node.is_mounted, node.display)
                 for history_view in view.window.histories for node in history_view.walk_children()],
            )
            editor = view.prompt.prompt_text_area
            editor.insert(f"draft-{source.id}")
            editor.history.checkpoint()
            editor.insert(" with undo")
            states[source.id] = (view.window.scroll_y, conversation_paint(frame), editor.document,
                                 editor.history, agent.process.process, agent.process.runner,
                                 tuple(ref(body) for body in view.query(AgentResponse)))
        native_calls = len(requests)
        assert native_calls == 4
        profile = cProfile.Profile() if os.environ.get("NATIVE_RETURN_PROFILE") == "1" else None
        if profile is not None:
            profile.enable()
        for source, agent in ((sources[0], agents[0]), (sources[1], agents[1]),
                              (sources[0], agents[0]), (sources[1], agents[1]), (sources[0], agents[0])):
            before_hits, before_misses = app.preparation.hits, app.preparation.misses
            started = perf_counter()
            await app.select_session(source.id)
            view = source.conversation
            await until(pilot, lambda: bool(view.window.histories))
            await settled(pilot, view)
            y, painted, document, history, process, runner, old_bodies = states[source.id]
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
            bodies = tuple(view.query(AgentResponse))
            reused = sum(any(previous() is body for previous in old_bodies) for body in bodies)
            assert reused > 0, ("Already-loaded native source discarded every response body", source.id)
            records.append({"source":source.id,"return_painted_ms":(perf_counter()-started)*1000,
                            "reader_y":y,"cache_hits":app.preparation.hits-before_hits,
                            "cache_misses":app.preparation.misses-before_misses,
                            "mounted_response_bodies":len(bodies),
                            "reused_body_instances":reused,
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
        assert app.screen is frame and app._exception is None
        Path(os.environ["NATIVE_RETURN_RECEIPT"]).write_text(json.dumps(records,indent=2))
        print("TWO_LOADED_NATIVE_ABABA_FULL_PAINT_READER_EDITOR_UNDO_CUSTODY_NO_REPLAY", records, flush=True)
    finally:
        for agent in agents[1:]:
            await agent.stop()
        await asyncio.to_thread(comms.owners.stop,"gamma")


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance))
