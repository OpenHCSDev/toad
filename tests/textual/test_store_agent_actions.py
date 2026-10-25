"""Textual-facing: the Store screen's agent dialog runs a catalog agent's actions through the command
editor and a real terminal dialog (failure, edit, cancel, typed input, bootstrap first, a newly declared action)."""

import json
import os
from unittest.mock import patch

from textual import widgets

from support.catalog import IDENTITY, private_catalog_entry
from support.catalog_steps import choose_action, open_agent, run_action
from toad.agent_schema import ChatAgentKind
from toad.app import ToadApp
from toad.session_scope import NoAgent
from toad.catalog_actions import CatalogCommandAction
from toad.screens.command_edit_modal import CommandEditModal
from toad.screens.store import AgentItem, StoreScreen
from support.ui import TextualUi
from toad.platform import host


class AuditAction(CatalogCommandAction):
    """An action declared here: the dialog must use it for the catalog's ``audit`` command with no other edit."""

    def finished(self, modal, return_code):
        modal.query_one("#run-action", widgets.Button).label = f"AUDIT_{return_code}"


def scrollback(pane) -> str:
    return "\n".join(line.content.plain for line in pane.execution.state.scrollback_buffer.lines)


async def test_agent_actions_run_edit_fail_cancel_and_take_input(workspace):
    settings = workspace.roots.attempt / "config" / "toad"
    settings.mkdir(parents=True)
    (settings / "toad.json").write_text(json.dumps({
        "anon_id": "00000000-0000-0000-0000-000000000001", "statistics": {"allow_collect": False}}))

    with private_catalog_entry():
        app = ToadApp(agent_binding=NoAgent(), mode="store", project_dir=str(workspace.project))  # starts on the Store: no session to wait for
        async with app.run_test(size=(140, 48)) as pilot:
            ui = TextualUi(app, pilot)
            await ui.until(lambda: isinstance(app.screen, StoreScreen), why="the Store")
            store = app.screen
            await ui.until(lambda: any(item.agent.identity == IDENTITY for item in store.query(AgentItem)),
                           why="the private catalog entry")
            agent = store.agents[IDENTITY]
            item = next(item for item in store.query(AgentItem) if item.agent is agent)
            expected_chat = {entry.identity for entry in store.agents.values()
                             if entry.kind.section() is ChatAgentKind}
            shown_chat = {entry.agent.identity for entry in store.query(AgentItem)
                          if entry.agent.kind.section() is ChatAgentKind}
            assert shown_chat == expected_chat
            chat_headings = [heading for heading in store.query(".heading")
                             if ChatAgentKind.heading in str(heading.render())]
            assert len(chat_headings) == bool(expected_chat)

            await open_agent(ui, item)
            modal = app.screen

            install = agent.commands_for(host)["install"]
            # Cancelling the editor runs nothing.
            await choose_action(ui, modal, "install")
            await ui.until(lambda: isinstance(app.screen, CommandEditModal), why="the command editor")
            assert await pilot.click(app.screen.query_one("#cancel", widgets.Button))
            await ui.until(lambda: app.screen is modal, why="the agent dialog again")
            await run_action(ui, "install", expected=7)
            assert not modal.launcher_checkbox.value, "A failed install added the agent to the launcher"
            await run_action(ui, "install", edited="printf CMD_INSTALL_EDITED")
            await ui.until(lambda: modal.launcher_checkbox.value, why="a successful install to add the launcher entry")
            assert install.command == "printf CMD_INSTALL_ORIGINAL; exit 7", "Editing changed the catalog's command"
            await run_action(ui, "install-acp")
            await run_action(ui, "owner-custom-script")
            await run_action(ui, "audit")
            assert isinstance(modal.action_select.value, AuditAction)
            await ui.until_shows("AUDIT_0")
            await run_action(ui, "login", edited="exit 5", expected=5)
            await run_action(ui, "login")

            # The bootstrap installer runs before the action's own command, in the same terminal.
            tools = workspace.roots.attempt / "bootstrap-tools"
            tools.mkdir()
            (tools / "curl").write_text("#!/bin/sh\nprintf 'printf CMD_BOOTSTRAP_FIRST\\n'\n")
            (tools / "curl").chmod(0o700)
            (tools / "sh").symlink_to("/bin/sh")
            with patch.dict(os.environ, PATH=str(tools)):
                text = scrollback(await run_action(ui, "bootstrap"))
            assert "CMD_BOOTSTRAP_FIRST" in text and "CMD_BOOTSTRAP_MAIN" in text
            assert text.index("CMD_BOOTSTRAP_FIRST") < text.rindex("CMD_BOOTSTRAP_MAIN")
            assert "CMD_INPUT:native-input" in scrollback(await run_action(ui, "input", typed="native-input"))
            await run_action(ui, "hold", cancel=True)
            await ui.press("escape")
            await ui.until(lambda: app.screen is store, why="the Store again")
            assert store.agents[IDENTITY] is agent and app._exception is None
