"""Steps through Textual widgets that several Textual-facing tests share.

Each takes the ``TextualUi``. App-layer tests do not use these.
"""

from __future__ import annotations

import asyncio


async def reveal_project_tree(ui):
    """Open the thread's Project panel (its tree loads only when shown) and return the tree."""
    from toad.widgets.project_directory_tree import ProjectDirectoryTree
    from toad.widgets.side_bar import SideBar, SideBarCollapsible

    sidebar = ui.app.screen.query_one("#thread-sidebar", SideBar)
    sidebar.reveal()
    await sidebar.wait_content_ready()
    next(panel for panel in sidebar.query(SideBarCollapsible) if panel.title == "Project").collapsed = False

    def loaded():
        tree = sidebar.query_one_optional(ProjectDirectoryTree)
        return tree is not None and tree.path_filter is not None

    await ui.until(loaded, seconds=5, why="the project tree")
    await ui.step()
    return sidebar.query_one(ProjectDirectoryTree)


async def channel_roster(ui, *targets: str):
    """Wait until the channels sidebar lists `targets`, and return the sidebar."""
    from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar

    def listed():
        sidebar = ui.app.screen.query_one(CommsSidebar)
        return (sidebar.navigation.ready.is_set() and sidebar.display and sidebar.model_state.shows_model()
                and set(targets) <= {group.row.target_name for group in sidebar.query(ChannelGroup)})

    await ui.until(listed, seconds=8, why=f"channels {targets} in the sidebar")
    return ui.app.screen.query_one(CommsSidebar)


async def reveal_session_details(ui, target=None):
    """Expand the session details panel, optionally scrolling `target` into view."""
    from toad.widgets.session_details import SessionDetails

    details = ui.app.screen.query_one(SessionDetails)
    if details.collapsed:
        assert await ui.pilot.click(details.query_one("CollapsibleTitle"))
        await ui.step()
    if target is not None:
        target.scroll_visible(animate=False, immediate=True)
        await ui.step()
    return details


async def command_dialog(ui, *, seconds: float = 20):
    """Wait for the command dialog to be mounted, focused on its name field and clickable."""
    from textual.widgets import Input
    from toad.widgets.comms_command_dialog import CommandDialog

    def usable():
        dialog = ui.app.screen
        if not (isinstance(dialog, CommandDialog) and dialog.is_mounted and dialog.is_attached):
            return False
        entry = dialog.query_one_optional("#command-field-name", Input)
        return (entry is not None and entry.is_mounted and entry.is_attached
                and dialog.focused is entry and ui.app.focused is entry
                and entry.region.width > 0 and entry.region.height > 0
                and entry.region.offset in dialog.size.region
                and dialog.get_widget_at(*entry.region.offset)[0] is entry)

    await ui.until(usable, seconds=seconds, why="the command dialog")
    return ui.app.screen


async def refresh_chat(view) -> None:
    """Run the chat view's history read now and wait for it; a view that is not shown reads nothing."""
    history = view.message_history
    while (worker := await view._refresh()) is None:
        if not history.can_draw_on_screen or history.state.accepts_source_work:
            return
        # Another read is in flight: read once it ends.
        await asyncio.sleep(0.01)
    await worker.wait()
    # The participants and status lines are read after the history's own read.
    for labels in tuple(view.workers):
        if labels.node is view and labels.group == view.LABELS_GROUP:
            await labels.wait()


def text_rows_of(chat, message) -> range | None:
    """The rows of the chat window's scrolled content that draw a message's own text, if it is laid out.

    None while a change to the history is still being laid out: its pages already hold the new rows, and
    the window is not on them until that layout ends.
    """
    window = chat.window
    if window.reader_position is not None or window.screen._stepped_layout is not None:
        return None
    for page in chat.message_history.pages:
        for fragment, first, lines in page._layout:
            if fragment.message.view_key == message.view_key:
                rows = fragment.text_rows(lines)
                return next((range(int(offset) + first + rows.start, int(offset) + first + rows.stop)
                             for _, offset in chat.window.placements((page,))), None)
    return None


def request_target_command(app, command, subject) -> None:
    """Invoke a target command (as the sidebar menu would) on `subject`."""
    from agent_comms.cli_commands import CliCommand, TargetEdit
    from agent_comms.channel_targets import CommandTarget
    from toad.thread_actions import ThreadAction

    comms = app.coordination_access.service
    target = CommandTarget.named(subject)
    definition = next(item for item in CliCommand.target_catalog(comms, CliCommand.selected_targets(target), project=str(app.project_dir))
                      if item.declaration is command)
    app.thread_actions.invoke(ThreadAction(definition, TargetEdit(target=command.selected_targets(target), declaration=command, arguments={})),
                              subject, source_root=comms.root)


def tool_status(fields: dict):
    """The ToolCallStatus for an ACP tool call written with the protocol's field names."""
    from acp.schema import ToolCall
    from toad.acp.status import ToolCallStatus

    return ToolCallStatus.from_acp(ToolCall.model_validate(fields))


async def wait_for_tool_diff(ui, tool):
    """Wait for the shared tool rows to be prepared and drawn."""
    from toad.widgets.tool_content import ToolContent

    content = tool.query_one(ToolContent)
    await ui.until(lambda: content._styled is not None, seconds=10, why="the styled tool rows")
    await ui.step()
    return content


def viewport_text(widget) -> str:
    """The text drawn in the part of `widget` that is on screen."""
    region, clip = widget.screen.screen._compositor.visible_widgets[widget]
    region = region.intersection(clip).intersection(widget.screen.region)
    return "\n".join(strip.crop(region.x, region.right).text
                     for strip in widget.screen.screen._compositor.render_strips()[region.y:region.bottom])


def painted_text(widget, text) -> bool:
    """Whether `widget` is on screen and draws `text`."""
    return widget in widget.screen._compositor.visible_widgets and text in viewport_text(widget)


async def saved_history(view, page, loader, *, committed=True):
    """A saved transcript history prepared and paged the way the application builds one."""
    from toad.transcript_preparation import SavedHistory, TranscriptPageRenderTask
    from toad.transcript_state import LiveTranscript, ProvisionalTranscript
    from toad.widgets.transcript_history import TranscriptHistory
    from toad.work_preparation import RenderPreparation

    prepared = await view.app.preparation.submit(RenderPreparation(TranscriptPageRenderTask(page)))
    return TranscriptHistory(prepared, SavedHistory(loader, page.after, view.app.preparation),
                             view=view, notification_view=view.contents,
                             source_state=LiveTranscript() if committed else ProvisionalTranscript())
