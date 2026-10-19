"""Steps through the Store's agent dialog and its command dialogs (Textual widgets)."""

from __future__ import annotations

from textual import widgets


async def open_agent(ui, item) -> None:
    """Open the agent dialog for a Store grid item."""
    from toad.screens.agent_modal import AgentModal
    from toad.screens.store import StoreScreen

    app, pilot = ui.textual
    item.scroll_visible(immediate=True)
    await ui.step()
    assert await pilot.click(item.query_one("#name", widgets.Label))
    await ui.step()
    if isinstance(app.screen, StoreScreen):
        await ui.press("enter")
    await ui.until(lambda: isinstance(app.screen, AgentModal), why="the agent dialog")


async def choose_action(ui, modal, name: str | None) -> None:
    """Pick action `name` in the agent dialog (None: the launch entry after the actions) and run it."""
    import toad

    _app, pilot = ui.textual
    order = list(modal.agent.commands_for(toad.os))
    index = len(order) if name is None else order.index(name)
    modal.action_select.focus()
    await ui.press("enter", "home", *(["down"] * (index + 1)), "enter")
    if name is not None:
        chosen = modal.action_select.value
        assert chosen.name == name, (name, chosen)
        assert chosen.command is modal.agent.commands_for(toad.os)[name]
    assert await pilot.click(modal.query_one("#run-action", widgets.Button))


async def run_action(ui, name: str, *, edited: str | None = None, cancel: bool = False, expected: int = 0,
                     typed: str | None = None):
    """Run an action from the open agent dialog through the command editor and the terminal dialog.

    Returns the terminal pane once the dialog has closed and its process is gone.
    """
    from toad.screens.action_modal import ActionModal
    from toad.screens.agent_modal import AgentModal
    from toad.screens.command_edit_modal import CommandEditModal

    app, pilot = ui.textual
    modal = app.screen
    assert isinstance(modal, AgentModal)
    await choose_action(ui, modal, name)
    await ui.until(lambda: isinstance(app.screen, CommandEditModal), why="the command editor")
    editor = app.screen
    if edited is not None:
        editor.text_area.focus()
        await ui.press("f7", *list(edited))
        assert editor.text_area.text == edited, editor.text_area.text
    assert await pilot.click(editor.query_one("#ok", widgets.Button))
    if name == "login" and expected == 0:
        await ui.until(lambda: isinstance(app.screen, AgentModal), why="a successful login to close by itself")
        return None
    await ui.until(lambda: isinstance(app.screen, ActionModal), why="the terminal dialog")
    runner = app.screen
    pane = runner.command_pane
    if typed is not None:
        await ui.until_shows("CMD_INPUT_READY")
        assert not pane.execution.operation.outcome().finished
        pane.focus()
        await ui.press(*list(typed), "enter")
    if cancel:
        await ui.until(lambda: ui.visible_text().count("CMD_HELD") >= 2, why="the held command's output")
        assert await pilot.click(runner.query_one("#cancel", widgets.Button))
    else:
        await ui.until(lambda: not runner.ok_button.disabled, seconds=20, why="the command to finish")
        assert runner.command_pane.return_code == expected
        assert await pilot.click(runner.ok_button)
    await ui.until(lambda: app.screen is modal, why="the agent dialog again")
    execution = pane.execution
    process = await execution.operation.process()
    assert execution.operation.outcome().finished, "The command is still running after its dialog closed"
    assert process.child.returncode is not None and process.master.closed
    assert process.child.retired, "The command's process outlived its dialog"
    return pane
