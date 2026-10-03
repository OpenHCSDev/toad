"""Installed native input -> real keyboard history/draft -> retained owner."""
from toad.core import input_events
import asyncio
from l0a_native_installed_pilot import main, until, response_painted
from native_session_retention_pilot import InstalledApp
from toad import messages
from toad.session_presentation import SessionViewState

async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
    view = app.selected_session.conversation
    release.set()
    hold_next.clear()
    await until(pilot, lambda: view.agent_ready)
    await view.submit_input(input_events.UserInputSubmitted("HISTORY_NATIVE_INPUT"))
    await until(pilot, lambda: response_painted(app, view, "NATIVE_RESPONSE_1"))
    await until(pilot, lambda: view.input_histories.prompt.size == 1)
    editor = view.prompt.prompt_text_area
    editor.focus()
    editor.text = "UNSENT_DRAFT"
    await pilot.press("ctrl+home", "up")
    await until(pilot, lambda: editor.text == "HISTORY_NATIVE_INPUT")
    assert view.input_histories.prompt.index == -1
    await until(pilot, lambda: "HISTORY_NATIVE_INPUT" in "\n".join(strip.text for strip in app.screen._compositor.render_strips()))
    await pilot.press("down")
    await until(pilot, lambda: editor.text == "UNSENT_DRAFT")
    assert view.input_histories.prompt.index == 0
    await until(pilot, lambda: "UNSENT_DRAFT" in "\n".join(strip.text for strip in app.screen._compositor.render_strips()))
    state = SessionViewState.capture(view)
    owner = view.input_histories
    document, undo = editor.document, editor.history
    state.restore(view)
    assert view.input_histories is owner
    assert editor.document is document and editor.history is undo
    assert editor.text == "UNSENT_DRAFT"
    assert len(requests) == 1
    from pathlib import Path
    Path("evidence/input-history/native-history.svg").write_text(app.export_screenshot())
    print("INSTALLED_NATIVE_PHYSICAL_HISTORY_DRAFT_OWNER_DOCUMENT_UNDO_PRESERVED", flush=True)

if __name__ == "__main__":
    asyncio.run(main(app_type=InstalledApp, acceptance=acceptance))
