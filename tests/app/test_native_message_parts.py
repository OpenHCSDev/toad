"""One saved native assistant message keeps its Markdown parts together under a single timestamp."""

from agent_comms.acp_extension import TranscriptSnapshotUpdate
from agent_comms.threads import Thread

from support.agents import deliver, detached
from support.coordination import carrying
from support.journals import assistant_entry, write_journal


async def test_saved_message_in_parts_shows_as_one_message(workspace):
    parts = ["## Plan\n\n", "- **Read** first\n", "- Keep working\n\n", "```python\n", "value = 123\n", "```\n"]
    entry = assistant_entry("", id="native-message")
    entry["message"]["content"] = [{"type": "text", "text": part} for part in parts]
    session = write_journal(workspace.project / "native.jsonl", entry)
    workspace.comms.registry.declare(Thread("worker", frozenset(), str(workspace.project), session_file=str(session)))
    read = workspace.comms.transcripts.capture_page_read("worker")
    saved = read.read()
    async with workspace.app(size=(110, 38)) as ui:
        agent = detached(workspace.project, "fixture")
        ui.attach_agent(agent)
        await deliver(agent, carrying(TranscriptSnapshotUpdate(saved, read.identity)))
        await ui.until(lambda: ui.shows("value = 123") and not ui.shows("## Plan"), why="the styled message")
        lines = [line.strip(" │▌").strip() for line in ui.visible_lines()]
        assert sum(" Agent " in line and "──" in line for line in lines) == 1, "one native row gained extra dividers"
        assert "Plan" in lines
        assert "• Read first" in lines and "• Keep working" in lines
        assert not any("```" in line or "**" in line for line in lines)
