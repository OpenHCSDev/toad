"""One saved native assistant message keeps its Markdown parts together under a single timestamp."""

from agent_comms.repo import Checkout
from agent_comms.session_file import RegistrySessionLocation
from agent_comms.threads import Thread
from support.journals import assistant_entry, write_journal


async def test_saved_message_in_parts_shows_as_one_message(workspace):
    parts = ["## Plan\n\n", "- **Read** first\n", "- Keep working\n\n", "```python\n", "value = 123\n", "```\n"]
    entry = assistant_entry("", id="native-message")
    entry["message"]["content"] = [{"type": "text", "text": part} for part in parts]
    session = write_journal(workspace.project / "native.jsonl", entry)
    workspace.comms.registry.declare(Thread("worker", frozenset(), Checkout(workspace.project), session_file=RegistrySessionLocation.from_path(session, workspace.comms.root)))
    async with workspace.app(size=(110, 38)) as ui:
        await ui.app.thread_navigation.open(
            owner_mode=ui.selected_tab, project_path=workspace.project, target="worker")
        await ui.step()
        await ui.until(lambda: ui.shows("value = 123") and not ui.shows("## Plan"), why="the styled message")
        lines = [line.strip(" │▌").strip() for line in ui.visible_lines()]
        assert sum(" Agent " in line and "──" in line for line in lines) == 1, "one native row gained extra dividers"
        assert "Plan" in lines
        assert "• Read first" in lines and "• Keep working" in lines
        assert not any("```" in line or "**" in line for line in lines)
