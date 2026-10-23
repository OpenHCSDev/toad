"""A resumed thread's saved project replaces the directory Toad was launched in, in every view that shows it."""

import asyncio
from pathlib import Path

import psutil

from support.native import attached_app, start_private_native_wire, without_provider
from support.textual_steps import reveal_project_tree
from toad.widgets.project_directory_tree import ProjectDirectoryTree
from agent_comms.threads import Thread


async def project_applied(ui, project) -> None:
    """Wait for the whole project change (shell directory, saved session, title), which ends with the title."""
    from toad.format_path import format_path

    app, _pilot = ui.textual
    await ui.until(lambda: format_path(project) in app.screen.title, why="the title to name the new project")


async def test_saved_project_and_later_changes_replace_the_launch_directory(workspace, native_package):
    launched, saved = workspace.project, workspace.roots.attempt / "saved-project"
    saved.mkdir()
    without_provider()
    comms = start_private_native_wire(workspace.roots.wire)
    comms.registry.declare(Thread("saved", frozenset({"acp"}), str(launched)))
    comms.threads.set_project("saved", str(saved))
    async with attached_app(workspace, comms, "saved", size=(100, 35)) as (ui, agent):
        app, _pilot = ui.textual
        await ui.until_agent_ready()
        conversation = ui.conversation
        assert agent.session.connected
        tree = await reveal_project_tree(ui)
        session = app.selected_session
        assert session.project_path == saved
        assert conversation.project_path == saved
        assert Path(tree.path) == saved
        assert saved.name in str(tree.root.label)
        shell = await conversation.shell._operation.process()

        def shell_directory():
            return psutil.Process(shell.child.pid).cwd()

        await ui.until(lambda: shell_directory() == str(saved), seconds=5, why="the shell in the saved project")
        assert conversation.working_directory == str(saved)
        await conversation.shell.change_directory(str(launched))
        await ui.step()
        assert conversation.project_path == saved
        assert Path(conversation.prompt.current_directory.path) == saved

        await asyncio.to_thread(comms.threads.set_project, "saved", str(launched))
        await ui.until(lambda: session.project_path == launched, seconds=10, why="the project change from the wire")
        await ui.until(lambda: conversation.project_path == launched, why="the conversation's project")
        assert Path(session.query_one(ProjectDirectoryTree).path) == launched
        await project_applied(ui, launched)


async def test_a_project_change_reported_by_the_agent_moves_the_session(workspace, native_package):
    from support.coordination import coordination_fact

    moved = workspace.roots.attempt / "moved-project"
    moved.mkdir()
    without_provider()
    comms = start_private_native_wire(workspace.roots.wire)
    comms.registry.declare(Thread("saved", frozenset({"acp"}), str(workspace.project)))
    async with attached_app(workspace, comms, "saved", size=(100, 35)) as (ui, agent):
        app, _pilot = ui.textual
        await ui.until_agent_ready()
        session = app.selected_session
        agent.comms_consumer_class(agent, agent.session_id).dispatch_sync(
            coordination_fact("saved", str(workspace.roots.wire), worktree=str(moved)))
        await ui.until(lambda: session.project_path == moved, why="the session's project to follow the agent's report")
        await ui.until(lambda: ui.conversation.project_path == moved, why="the conversation's project")
        await project_applied(ui, moved)
        assert ui.failure() is None
