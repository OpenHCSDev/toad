"""Installed native source return preserves a non-tail reader with bounded data.

One real Pi/ACP source is visited through four logical tabs. No transport,
restoration, source loader or body renderer is replaced by a test double.
"""
import asyncio
import difflib
import gc
import json
import os
from pathlib import Path

from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp, conversation_paint
from toad.screens.main import MainScreen
from textual.widget import Widget
from toad.widgets.transcript_history import TranscriptFragmentView
from agent_comms.transcript_events import TextTranscript


READER_TEXT = "READER_POSITION_3"


async def settled(pilot, view):
    window = view.window
    await until(pilot, lambda: (
        not window.document_viewport._running
        and window.document_viewport.visible_bodies_ready
        and all(not history._loading
                for history in window.histories)
    ))


async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    frame, source = app.screen, app.selected_session
    original_agent = agent
    process, runner = agent.process.process, agent.process.runner
    release.set()
    for index in range(4):
        prompt = f"READER_POSITION_{index}\n\n" + "\n\n".join(
            f"Source {index} paragraph {row}: retained canonical reader text."
            for row in range(12)
        )
        await asyncio.wait_for(agent.send_prompt(prompt), 25)
        await until(pilot, lambda: not comms.registry.require("beta").executing)
    await until(pilot, lambda: "NATIVE_RESPONSE_4" in conversation_paint(frame))
    # Reopen through the ordinary source owner before choosing a saved reader
    # record. Direct Agent input doesn't synthesize the UI's live UserInput;
    # the actual native journal snapshot publishes that canonical content.
    modes = []
    for index in range(3):
        details = await app.new_session_screen(lambda: MainScreen(
            original_agent.project_root_path, agent_session_id=f"recent-return-{index}"))
        modes.append(details.mode_name)
        await pilot.pause(.02)
    await app.select_session(source.id)
    await until(pilot, lambda: "NATIVE_RESPONSE_4" in conversation_paint(frame))
    conversation = source.conversation
    await settled(pilot, conversation)
    window = conversation.window
    # Visible text can precede the pager's next measured layout. Establish a
    # real scroll range before selecting a non-tail record; zero is not a saved
    # reader position for this acceptance path.
    await until(pilot, lambda: window.max_scroll_y > 0)
    candidates = [node for node in conversation.query(TranscriptFragmentView)
                  if any(READER_TEXT in event.text
                         for event in node.fragment.events if isinstance(event, TextTranscript))]
    assert candidates, "Native source did not publish the selected reader record"
    window.release_anchor()
    window.scroll_to_widget(candidates[0], animate=False, immediate=True, top=True)
    await until(pilot, lambda: READER_TEXT in conversation_paint(frame))
    print("RECENT_POSITION", window.scroll_y, window.max_scroll_y, window.follows_tail, flush=True)
    await settled(pilot, conversation)
    before_y = window.scroll_y
    assert before_y < window.max_scroll_y and not window.follows_tail
    print("RECENT_INITIAL_GEOMETRY", [(type(node).__name__, node.region, node.virtual_size,
          node.show_vertical_scrollbar) for node in (window, *window.ancestors) if isinstance(node, Widget)], flush=True)
    source_paint = conversation_paint(frame)
    editor = conversation.prompt.prompt_text_area
    document, history = editor.document, editor.history
    records = []
    for mode in modes:
        await app.select_session(mode)
        await pilot.pause(.02)
        await app.select_session(source.id)
        await until(pilot, lambda: READER_TEXT in conversation_paint(frame))
        restored = source.conversation
        await settled(pilot, restored)
        assert restored is conversation and app.screen is frame
        assert restored.agent is original_agent
        assert agent.process.process is process and agent.process.runner is runner
        assert process.returncode is None and not runner.done()
        assert not restored.window.follows_tail
        if restored.window.scroll_y != before_y:
            print("RECENT_RETURN_GEOMETRY", [(type(node).__name__, node.region, node.virtual_size,
                  node.show_vertical_scrollbar) for node in (restored.window, *restored.window.ancestors) if isinstance(node, Widget)], flush=True)
            current_paint = conversation_paint(frame)
            print("RECENT_PAINT_DIAGNOSTIC", source_paint == current_paint,
                  [index for index, line in enumerate(source_paint.splitlines()) if READER_TEXT in line],
                  [index for index, line in enumerate(current_paint.splitlines()) if READER_TEXT in line], flush=True)
            print("RECENT_READER_DIAGNOSTIC", [(history.fragment_count, history.has_older,
                  history._loading, history._check_pending, history._selected_categories,
                  history.region, frame._compositor.visible_widgets.get(history))
                  for history in restored.window.histories], flush=True)
        assert restored.window.scroll_y == before_y, (restored.window.scroll_y, before_y, restored.window.max_scroll_y, restored.window.scrollable_content_region)
        if conversation_paint(frame) != source_paint:
            print("RECENT_PAINT_DIFF", "\n".join(difflib.unified_diff(
                source_paint.splitlines(), conversation_paint(frame).splitlines(),
                fromfile="departing", tofile="returned")), flush=True)
            print("RECENT_PAINT_GEOMETRY", window.virtual_size, window.region,
                  window.show_vertical_scrollbar, window.scrollable_content_region, flush=True)
        assert conversation_paint(frame) == source_paint
        assert restored.prompt.prompt_text_area is editor
        assert editor.document is document and editor.history is history
        assert len(requests) == 4, "Source return replayed native input"
        rich = {id(view) for owner in app.workspace_sessions.views.values()
                for view in owner.query("Conversation")}
        assert len(rich) == 1
        assert app.preparation.retained_bytes <= app.preparation.max_bytes
        gc.collect()
        records.append({"return_mode": mode, "scroll_y": restored.window.scroll_y,
                        "rich_views": len(rich), "native_calls": len(requests),
                        "prepared_bytes": app.preparation.retained_bytes,
                        "preparation_hits": app.preparation.hits,
                        "preparation_misses": app.preparation.misses})
    Path(os.environ["RECENT_SOURCE_RECEIPT"]).write_text(json.dumps(records, indent=2))
    print("Installed native non-tail return/cropped reader/editor/source lifetime passed", flush=True)


if __name__ == "__main__":
    asyncio.run(native_fixture(app_type=InstalledApp, acceptance=acceptance))
