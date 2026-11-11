"""Local failures stay between the saved messages they originally followed."""

import json
from dataclasses import replace

from agent_comms.execution.session_file import RegistrySessionLocation
from support.journals import assistant_entry, write_journal

from toad.core.events import TextAgentFail
from toad.widgets.note import ErrorNote


async def test_error_note_keeps_its_chronological_place_across_saved_appends(workspace):
    thread = workspace.thread("error-source")
    journal = write_journal(
        thread.project_path / "error-source.jsonl",
        assistant_entry("BEFORE_LOCAL_FAILURE", id="before"),
    )
    workspace.comms.registry.declare(replace(
        thread, session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root),
    ))
    async with workspace.app(resume="error-source", size=(110, 38)) as ui:
        view = ui.conversation
        await ui.until_shows("BEFORE_LOCAL_FAILURE")
        await ui.app.coordination_access.stop_observing()
        await TextAgentFail("LOCAL_FAILURE_STAYS", "Unconfirmed").present(view)
        await ui.until_shows("LOCAL_FAILURE_STAYS")
        note = view.query_one(ErrorNote)
        for identity, parent, marker in (
            ("after", "before", "AFTER_LOCAL_FAILURE"),
            ("later", "after", "LATER_SAVED_MESSAGE"),
        ):
            with journal.open("a") as output:
                output.write(json.dumps(assistant_entry(marker, id=identity, parent=parent)) + "\n")
            view.transcript.require_commit()
            await ui.until_shows(marker)
            painted = ui.painted(view.window)
            assert painted.index("BEFORE_LOCAL_FAILURE") < painted.index("LOCAL_FAILURE_STAYS")
            assert painted.index("LOCAL_FAILURE_STAYS") < painted.index(marker)
            assert note.is_attached
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry(
                "\n".join(f"Later row {index}" for index in range(60)) + "\nLONG_REPLY_END",
                id="long", parent="later",
            )) + "\n")
        view.transcript.require_commit()
        await ui.until_shows("LONG_REPLY_END")
        view.window.scroll_to(y=0, animate=False, immediate=True)
        await ui.step()
        assert not view.window.follows_tail
        before = view.window.scroll_y
        with journal.open("a") as output:
            output.write(json.dumps(assistant_entry(
                "AFTER_READER_SCROLLED", id="scrolled", parent="long",
            )) + "\n")
        view.transcript.require_commit()
        await ui.step()
        assert view.window.scroll_y == before
        assert note.is_attached
        assert ui.failure() is None
        first, owner = ui.selected_tab, ui.app.selected_session
        await ui.new_session()
        await owner.presentation.evict(owner)
        await ui.select_tab(first)
        ui.conversation.window.scroll_to(y=0, animate=False, immediate=True)
        await ui.until_shows("BEFORE_LOCAL_FAILURE")
        assert ui.failure() is None
