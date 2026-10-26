"""Textual-facing: the session details panel and the history widgets report saved-history coverage from the retained source.

Not carried over from the old script: the wait for a nested rendering pager inside a long live message
(agent text is line-drawn now, so a live message has no pager of its own).
"""

from agent_comms.repo import Checkout
from functools import partial

from agent_comms.session_file import RegistrySessionLocation
from agent_comms.threads import Thread
from support import journals
from toad.screens.main import MainScreen
from toad.tab_identity.kinds import MailboxTab
from toad.widgets.agent_response import AgentResponse
from toad.widgets.session_details import SessionDetails
from toad.widgets.transcript_history import TranscriptHistory


async def saved_history(workspace, ui):
    journal = journals.write_journal(workspace.project / "native.jsonl", *(
        journals.assistant_entry(f"## Saved native row {number}\n\n"
                                 "Canonical retained source owns coverage independently of painted resources.",
                                 id=f"a{number}", parent=f"a{number - 1}" if number else None)
        for number in range(8)))
    owner = workspace.comms.registry.declare(Thread(
        "saved", frozenset(), Checkout(workspace.project),
        session_file=RegistrySessionLocation.from_path(journal, workspace.comms.root),
    ))
    root = str(workspace.comms.root)
    await ui.app.session_navigation.new(
        MailboxTab(owner.incarnation, root),
        partial(MainScreen.from_thread, workspace.project, root, owner.incarnation),
        original=(root, owner.incarnation),
    )
    conversation = ui.conversation
    await ui.until(lambda: conversation.transcript.reports_coverage,
                   why="the retained owner's saved history")
    page = workspace.comms.transcripts.capture_page_read(owner.name).read()
    return page, conversation.contents.query_children(TranscriptHistory).first(), conversation.query_one(SessionDetails)


async def test_saved_history_is_unavailable_while_its_source_is_parked_and_returns_when_revalidated(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        page, history, details = await saved_history(workspace, ui)
        conversation = ui.conversation
        await ui.until(lambda: "Saved history available" in str(details.title), why="saved history reported available")
        children, pages = tuple(history.walk_children()), tuple(history.pages)

        await history.retire_source(parked=True)
        await conversation.transcript.binding.reveal_retained(conversation.transcript, history)
        await ui.until(lambda: "Saved history not loaded" in str(details.title), why="saved history reported not loaded")
        assert not history.state.reports_coverage

        conversation.transcript.received(page)
        await ui.until(lambda: history.state.reports_coverage, why="coverage reported again")
        await ui.until(lambda: "Saved history available" in str(details.title), why="saved history reported available again")
        assert "Saved history available" in details.overview_text
        assert history is conversation.transcript.binding.history
        assert tuple(history.pages) == pages
        assert tuple(history.walk_children()) == children


async def test_a_live_message_does_not_count_as_saved_history_coverage(workspace):
    async with workspace.app(size=(110, 35)) as ui:
        page, history, details = await saved_history(workspace, ui)
        conversation = ui.conversation
        pages = tuple(history.pages)
        await conversation.contents.mount(AgentResponse("## Paged live message\n\n" + "\n\n".join(
            f"Live paragraph {i} is long enough to need more than one page." for i in range(32))))
        await ui.step()
        await history.retire_source(parked=True)
        await conversation.transcript.binding.reveal_retained(conversation.transcript, history)
        await ui.until(lambda: "Saved history not loaded" in str(details.title), why="saved history reported not loaded")
        assert not conversation.transcript.reports_coverage
        conversation.transcript.received(page)
        await ui.until(lambda: "Saved history available" in str(details.title), why="saved history reported available")
        assert tuple(history.pages) == pages
