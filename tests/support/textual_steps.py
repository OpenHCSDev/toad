"""Steps through Textual widgets that several Textual-facing tests share.

Each takes the ``TextualUi``. App-layer tests do not use these.
"""

from __future__ import annotations

from pathlib import Path


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
        return (sidebar.navigation.ready.is_set() and sidebar.display and sidebar.shows_model
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
    """Run the chat view's history read now and wait for it."""
    worker = await view._refresh()
    if worker is not None:
        await worker.wait()


def coordination_update(root, name):
    """The coordination fact for a thread as its registry row describes it now."""
    from agent_comms.acp_extension import CoordinationChangedUpdate
    from agent_comms.comms import wire

    thread = wire(Path(root)).registry.require(name)
    return CoordinationChangedUpdate(thread.incarnation, str(root), thread.pid, thread.worktree or "",
                                     thread.model, thread.thinking_level, thread.title or thread.name, None)


def request_target_command(app, command, subject) -> None:
    """Invoke a target command (as the sidebar menu would) on `subject`."""
    from agent_comms.cli_commands import CliCommand, TargetEdit
    from toad.thread_actions import ThreadAction

    comms = app.coordination_access.service
    definition = next(item for item in CliCommand.target_catalog(comms, subject, project=str(app.project_dir))
                      if item.declaration is command)
    app.thread_actions.invoke(ThreadAction(definition, TargetEdit(target=subject, declaration=command, arguments={})),
                              subject, source_root=comms.root)
