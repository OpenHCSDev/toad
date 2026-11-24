"""A message prompt attaches files from its terminal pickers, sends them with the message,
and gets them back with the draft when a send does not land."""

import hashlib

from agent_comms.messaging.channel_targets import ChannelTarget, CommandTarget

from toad.client.conversation import ChannelConversation
from toad.client.history import ChannelDestination
from toad.client.message_files import PathSearchFilePicker
from toad.conversation_submission import OrdinaryInputSubmission
from toad.preferences import SETTINGS
from toad.screens.file_picker import FileBrowserScreen, PathSearchScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.prompt import FileChip, MessageTextArea, PromptTextArea
from toad.prompt_actions import AttachFileAction


def chips(prompt) -> list[str]:
    return [str(chip.label) for chip in prompt.query(FileChip)]


async def test_a_picked_file_rides_the_message_and_comes_back_with_a_refused_draft(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        view = ui.app.selected_session.query_one(CommsChatView)
        prompt = view.prompt
        content = b"line one\nline two\n"
        picked = prompt.project_path.path / "notes.txt"
        picked.write_bytes(content)

        await prompt.attach_path(picked)
        await ui.until(lambda: chips(prompt) == ["notes.txt · 18 B ✕"], why="the attached file's chip")

        prompt.prompt_text_area.focus()
        await ui.type("with a file")
        await ui.press("enter")

        def sent_messages():
            return [message for message in workspace.comms.views.history_page(CommandTarget.named("#team")).messages
                    if message.body == "with a file"]

        await ui.until(sent_messages, why="the message on the bus")
        (sent,) = sent_messages()
        (stored,) = workspace.comms.messaging.files.of((sent.reference,))
        assert (stored.name, stored.size, stored.sha256) == (
            "notes.txt", len(content), hashlib.sha256(content).hexdigest())
        assert chips(prompt) == [] and prompt.attached_files == ()

        await prompt.attach_path(picked)
        files = prompt.take_files()
        stale = ChannelDestination(workspace.roots.wire, ChannelConversation(ChannelTarget("#elsewhere")), view)
        await view.submissions.start_bus(OrdinaryInputSubmission("REFUSED_DRAFT", files), stale).prepare()
        await ui.until(lambda: prompt.text == "REFUSED_DRAFT", why="the refused text back in the composer")
        assert prompt.attached_files == files
        await ui.until(lambda: chips(prompt) == ["notes.txt · 18 B ✕"], why="the refused file's chip")

        prompt.query_one(FileChip).press()
        await ui.until(lambda: chips(prompt) == [], why="the chip took its file off")
        assert prompt.attached_files == ()


async def test_the_attach_key_opens_the_named_picker_and_escape_attaches_nothing(workspace):
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    async with workspace.app() as ui:
        app, _pilot = ui.textual
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        prompt = app.selected_session.query_one(CommsChatView).prompt
        (prompt.project_path.path / "picked-by-search.txt").write_bytes(b"found")

        prompt.prompt_text_area.focus()
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(app.screen, FileBrowserScreen), why="the file browser")
        await ui.press("escape")
        await ui.until(lambda: not isinstance(app.screen, FileBrowserScreen), why="escape closed it")
        assert prompt.attached_files == ()

        app.saved_settings.set(SETTINGS.ui.input.file_picker, PathSearchFilePicker)
        prompt.prompt_text_area.focus()
        await ui.press("ctrl+t")
        await ui.until(lambda: isinstance(app.screen, PathSearchScreen), why="the path search")
        await ui.until(lambda: "picked-by-search.txt" in app.screen.spellings, why="the project listing")
        await ui.type("picked-by")
        await ui.press("enter")
        await ui.until(lambda: chips(prompt) == ["picked-by-search.txt · 5 B ✕"], why="the searched file's chip")


def test_only_a_message_editor_answers_the_attach_key():
    assert AttachFileAction in MessageTextArea.declared_actions()
    assert AttachFileAction not in PromptTextArea.declared_actions()


async def test_a_sent_file_draws_as_a_chip_under_its_message_in_the_terminal(workspace):
    """The history row a reader sees: the message's text, then a chip per file it carries."""
    workspace.thread("peer", "team")
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        view = ui.app.selected_session.query_one(CommsChatView)
        prompt = view.prompt
        picked = prompt.project_path.path / "shot.png"
        picked.write_bytes(b"\x89PNG" + bytes(2044))
        await prompt.attach_path(picked)
        prompt.prompt_text_area.focus()
        await ui.type("a screenshot")
        await ui.press("enter")
        await ui.until(lambda: ui.shows("a screenshot") and ui.shows("[shot.png · 2.0 KB]"),
                       why="the sent message and its file's chip under it")


async def test_an_image_pasted_into_a_message_rides_it_as_a_file_not_as_a_path(workspace):
    """Tristan pasted a screenshot into #claude and every teammate got one line,
    `@~/.local/share/toad/clipboard-images/clipboard-794d….png`: a path on his laptop,
    which no other machine can open. A message composer attaches the image instead."""
    workspace.thread("peer", "team")
    workspace.comms.messaging.send("peer", "#team", "CURRENT_HISTORY")
    png = b"\x89PNG\r\n\x1a\n" + b"pixels" * 40
    async with workspace.app() as ui:
        await ui.open_channel("#team", actor=workspace.viewer)
        await ui.until_shows("CURRENT_HISTORY")
        prompt = ui.app.selected_session.query_one(CommsChatView).prompt

        await prompt.prompt_text_area.attach_png(png)

        name = f"clipboard-{hashlib.sha256(png).hexdigest()[:12]}.png"
        await ui.until(lambda: chips(prompt) == [f"{name} · {len(png)} B ✕"], why="the pasted image's chip")
        assert prompt.text == ""
        (attached,) = prompt.attached_files
        assert (attached.name, attached.mime_type, attached.sha256) == (
            name, "image/png", hashlib.sha256(png).hexdigest())
