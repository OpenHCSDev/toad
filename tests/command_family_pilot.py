"""Mounted command discovery/submission using real isolated core stores."""

from __future__ import annotations

import asyncio
import os
import json
import sys
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_comms.comms import wire
from agent_comms.threads import Thread
from agent_comms.thread_status import StoppedThreadStatus
from textual.geometry import Offset
from toad.app import ToadApp
from toad.screens.main import MainScreen
from toad.slash_command import (
    AgentAdvertisedCommand,
    LocalCommand,
    NoArgumentsCommand,
    SlashCommand,
)
from toad.command_catalog import CommandCatalog
from toad.target_commands import TargetLocal, target_commands
from toad.thread_actions import ArchiveAction, ForkAction, ThreadAction
from toad.widgets.comms_fork_dialog import ForkDialog
from textual.widgets import Static
from toad.widgets.comms_menu import ContextMenuItem
from toad.widgets.comms_sidebar import CommsSidebar
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.slash_complete import SlashComplete


class CommandPilotApp(ToadApp):
    """Exercise installed commands without unrelated internet telemetry tasks."""

    CSS_PATH = files("toad").joinpath("toad.tcss")

    def capture_event(self, *args, **kwargs):
        pass

    def run_version_check(self, *args, **kwargs):
        pass


async def until(pilot, predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await pilot.pause(0.02)


async def submit(pilot, conversation, text):
    conversation.prompt.text = text
    conversation.prompt.focus()
    await pilot.press("enter")
    await pilot.pause(0.05)


async def main():
    class InsertionCommand(NoArgumentsCommand):
        help = "A single declaration becomes discoverable and executable"

        async def apply(self, conversation):
            conversation.prompt.text = "declaration ran"
            return True

    for member in SlashCommand.members_with(LocalCommand):
        assert member.help and member().command
        assert member.parse("" if issubclass(member, TargetLocal) else "1")
    for member in ThreadAction.menu():
        assert member.pending and member.menu_label()
        assert member.tool.action_label == member.menu_label()
    advertised = [
        AgentAdvertisedCommand("model", "wrong collision help"),
        AgentAdvertisedCommand("external", "Native agent command"),
    ]
    completions = CommandCatalog(advertised).commands
    assert (
        next(c for c in completions if c.command == "/model").help
        != "wrong collision help"
    )
    assert next(c for c in completions if c.command == "/external").requires_agent
    assert any(c.command == "/insertion" for c in completions)

    artifacts = Path(__file__).resolve().parents[1] / ".artifacts"
    with TemporaryDirectory(prefix="t3-commands-", dir=artifacts) as directory:
        root = Path(directory)
        os.environ.update(
            AGENT_COMMS_ROOT=str(root / "wire"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
        )
        comms = wire(root / "wire")
        for name in ("actor", "pointer", "slash", "other"):
            comms.registry.register(
                Thread(name, frozenset({"team"}), str(root)), StoppedThreadStatus()
            )
        comms.channels.create_tag("team")
        comms.messaging.send("pointer", "actor", "retained pointer history")
        comms.messaging.send("slash", "actor", "retained slash history")
        original_history = comms.views.full_history()
        app = CommandPilotApp(project_dir=str(root))
        async with app.run_test(size=(110, 38)) as pilot:
            mode = (await app.new_session_screen(lambda: MainScreen(root))).mode_name
            conversation = app.screen.conversation
            actor = app.screen.navigation_context.actor
            if actor not in comms.registry.all_threads():
                comms.registry.register(
                    Thread(actor, frozenset({"team"}), str(root)), StoppedThreadStatus()
                )
            conversation.update_slash_commands()
            # A fresh ACP SDK producer exercises the real JSON-RPC notification
            # validator and mounted consumer; no provider is invoked.
            producer = """import json
from acp.schema import AvailableCommandsUpdate
update=AvailableCommandsUpdate.model_validate({'sessionUpdate':'available_commands_update',
 'availableCommands':[{'name':'model','description':'ACP collision'},
                      {'name':'external','description':'Native command'}]})
print(json.dumps({'jsonrpc':'2.0','method':'session/update','params':{
 'sessionId':'commands','update':update.model_dump(by_alias=True,exclude_none=True)}}))
"""
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-c", producer, stdout=asyncio.subprocess.PIPE
            )
            payload = await process.stdout.read()
            assert await process.wait() == 0
            from toad.acp.agent import Agent

            agent = Agent(
                root,
                {
                    "name": "Commands",
                    "identity": "commands",
                    "short_name": "commands",
                    "run_command": {"*": "true"},
                    "protocol": "acp",
                },
                "commands",
            )
            agent._message_target = conversation
            await agent.server.call(json.loads(payload))
            await until(
                pilot,
                lambda: any(
                    c.command == "/external" for c in conversation.prompt.slash_commands
                ),
            )
            assert (
                next(
                    c
                    for c in conversation.prompt.slash_commands
                    if c.command == "/model"
                ).help
                != "ACP collision"
            )
            assert await conversation.slash_command("/external argument") is False
            print(
                "PASS: fresh ACP SDK -> real JSON-RPC validation -> mounted advertised command completion; local collision and forwarding preserved",
                flush=True,
            )
            await submit(pilot, conversation, "/insertion")
            assert conversation.prompt.text == "declaration ran"
            await submit(pilot, conversation, "/copy")
            assert app.clipboard == actor
            before = comms.views.full_history()
            await submit(pilot, conversation, "/toad:clear nonsense")
            assert comms.views.full_history() == before
            print(
                "PASS: mounted agent command insertion, local execution before agent readiness, collision ownership and invalid-argument consumption",
                flush=True,
            )

            dm = await app.open_comms_session(
                owner_mode=mode,
                project_path=root,
                me="actor",
                target="slash",
                kind="dm",
            )
            await pilot.pause()
            await until(
                pilot, lambda: app.screen.query_one_optional(CommsChatView) is not None
            )
            conversation = app.screen.query_one(CommsChatView)
            await until(
                pilot,
                lambda: conversation._wire is not None and conversation.agent_ready,
            )
            conversation.update_slash_commands()
            assert conversation.query_one(SlashComplete)
            sidebar = app.screen.query_one(CommsSidebar)
            sidebar.selected = "other"
            sidebar._show_thread_menu("slash", Offset(3, 3), mode_name=dm)
            await pilot.pause()
            menu = {
                item.action: item.render().plain
                for item in app.screen.query(ContextMenuItem)
            }
            expected = {
                c.command.removeprefix("/"): c.label(
                    conversation.command_target_context()
                )
                for c in target_commands(conversation.command_target_context())
            }
            assert menu == expected, (menu, expected)
            await app.screen.dismiss()
            await submit(pilot, conversation, "/copy")
            assert app.clipboard == "slash", (
                "Sidebar selection must not change the slash target"
            )
            # Both entry points use the existing parameter dialog; cancel never
            # creates an owner or changes the exact target's registry/history.
            registry_before = comms.registry.all_threads()
            await submit(pilot, conversation, f"/{ForkAction.declared_name}")
            await until(pilot, lambda: isinstance(app.screen, ForkDialog))
            assert "@slash" in app.screen.query_one("#title", Static).render().plain
            await pilot.press("escape")
            await until(pilot, lambda: not isinstance(app.screen, ForkDialog))
            sidebar._show_thread_menu("slash", Offset(3, 3), mode_name=dm)
            await pilot.pause()
            fork_item = next(item for item in app.screen.query(ContextMenuItem)
                             if item.action == ForkAction.declared_name)
            await pilot.click(fork_item)
            await until(pilot, lambda: isinstance(app.screen, ForkDialog))
            assert "@slash" in app.screen.query_one("#title", Static).render().plain
            await pilot.press("escape")
            await until(pilot, lambda: not isinstance(app.screen, ForkDialog))
            assert comms.registry.all_threads() == registry_before
            assert comms.views.full_history() == original_history
            await submit(pilot, conversation, f"/{ArchiveAction.declared_name}")
            await until(
                pilot,
                lambda: comms.registry.status("slash").declared_name == "archived",
            )
            await until(pilot, lambda: not app.pending_thread_actions)
            conversation.update_slash_commands()
            assert f"/{ArchiveAction.declared_name}" not in {
                c.command for c in conversation.prompt.slash_commands
            }
            await submit(pilot, conversation, f"/{ArchiveAction.declared_name}")
            assert comms.views.full_history() == original_history, (
                "Unavailable commands must not become messages"
            )
            print(
                "PASS: mounted DM menu/slash label parity, exact open target, archive and stale availability; durable history unchanged",
                flush=True,
            )

            channel = await app.open_comms_session(
                owner_mode=mode,
                project_path=root,
                me="actor",
                target="#team",
                kind="channel",
            )
            await pilot.pause()
            await until(
                pilot, lambda: app.screen.query_one_optional(CommsChatView) is not None
            )
            conversation = app.screen.query_one(CommsChatView)
            await until(
                pilot,
                lambda: conversation._wire is not None and conversation.agent_ready,
            )
            conversation.update_slash_commands()
            assert conversation.query_one(SlashComplete)
            sidebar = app.screen.query_one(CommsSidebar)
            sidebar._show_channel_menu("#team", Offset(3, 3))
            await pilot.pause()
            menu = {
                item.action: item.render().plain
                for item in app.screen.query(ContextMenuItem)
            }
            ctx = conversation.command_target_context()
            expected = {
                c.command.removeprefix("/"): c.label(ctx) for c in target_commands(ctx)
            }
            assert menu == expected, (menu, expected)
            pin = next(
                item
                for item in app.screen.query(ContextMenuItem)
                if item.action == "pin"
            )
            await pilot.click(pin)
            await until(
                pilot, lambda: comms.channels.catalog.read().resolve("#team").pinned
            )
            await submit(pilot, conversation, "/pin")
            await until(
                pilot, lambda: not comms.channels.catalog.read().resolve("#team").pinned
            )
            await submit(pilot, conversation, "/pin @other")
            await until(
                pilot,
                lambda: (
                    "other" in comms.channels.catalog.read().pinned_threads("#team")
                ),
            )
            await submit(pilot, conversation, "/pin @other")
            await until(
                pilot,
                lambda: (
                    "other" not in comms.channels.catalog.read().pinned_threads("#team")
                ),
            )
            await submit(pilot, conversation, "/any_mode")
            await until(
                pilot, lambda: comms.channels.catalog.read().resolve("#team").any_mode
            )
            await submit(pilot, conversation, "/copy")
            assert app.clipboard == "#team"
            assert comms.views.full_history() == original_history
            assert app._exception is None
            print(
                "PASS: mounted channel pointer/slash pin, any-mode and copy share declaration behavior; no prompt published",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
