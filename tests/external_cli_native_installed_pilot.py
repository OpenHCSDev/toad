"""CLI registration/inbox/reply through the installed native ACP and real Toad.

The participant uses the actual CLI. Only the localhost provider is controlled;
the application, bus, navigation, receipts and native owner remain production.
Run under the existing isolated st/ProcessOwner capture, never the user's X11.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic

from agent_comms.acp import CommsClient
from agent_comms.errors import RelationViolationError
from agent_comms.field_codec import FieldCodec
from agent_comms.thread_execution import ExternalThreadExecution, NativeThreadExecution
from agent_comms.thread_identity import ThreadRole
from agent_comms.threads import Thread
from l0a_native_installed_pilot import main as native_fixture, until
from native_session_retention_pilot import InstalledApp
from saved_state_user_journey_pilot import reveal_thread_row, submit_editor, click_tab, screen_paint
from toad.screens.comms import CommsScreen
from toad.widgets.comms_chat import CommsChatView
from toad.widgets.comms_sidebar import CommsRow
from toad.widgets.message_notifications import MessageNotifications


NAME = "external-cli-fixture"
CHANNEL = "#openhcs"
SEED = "CLI_SAVED_CHANNEL_ORIGINAL"
CHANNEL_INPUT = "CLI_CHANNEL_PHYSICAL_ENTER"
DM_INPUT = "CLI_DM_PHYSICAL_ENTER"
REPLY = "CLI_ORIGINAL_AGENT_REPLY"


def participant(root: Path, project: Path):
    """An external agent process shells out to the public CLI; no native RPC."""
    command = [sys.executable, "-I", "-m", "agent_comms.cli", "--root", str(root)]

    def run(arguments):
        completed = subprocess.run([*command, *arguments], check=True,
                                   capture_output=True, text=True)
        print(completed.stdout.strip(), flush=True)

    run(["register", "--name", NAME, "--worktree", str(project),
         "--tags", "openhcs", "--pid", str(os.getpid())])
    for line in sys.stdin:
        run(json.loads(line))


@dataclass
class CliParticipant:
    process: asyncio.subprocess.Process

    async def receive(self):
        # CLI emits one pretty JSON document. Decode once after its closing line.
        lines = []
        while line := await self.process.stdout.readline():
            lines.append(line.decode())
            if line.rstrip() == b"}":
                return json.loads("".join(lines))
        raise RuntimeError("Original CLI participant exited before its receipt")

    async def invoke(self, *arguments):
        self.process.stdin.write((json.dumps(arguments) + "\n").encode())
        await self.process.stdin.drain()
        return await self.receive()

    async def retire(self):
        if self.process.returncode is None:
            self.process.stdin.close()
            await asyncio.wait_for(self.process.wait(), 5)


async def journey():
    evidence = Path(os.environ["L0A_EVIDENCE"])
    receipt = {"phases": [], "provider_requests": 0, "public_mutations": 0}
    cli = None
    started = monotonic()

    async def prepare(comms, project, requests, entered, release, hold_next):
        nonlocal cli
        release.set()
        hold_next.clear()
        other = project.parent / "external-project"
        other.mkdir()
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).resolve()), "--participant",
            str(comms.root), str(other), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=(evidence / "participant-stderr.txt").open("w"),
        )
        cli = CliParticipant(process)
        assert await cli.receive() == {"registered": NAME}
        registered = comms.registry.require(NAME)
        assert registered.execution is ExternalThreadExecution
        assert registered.role is ThreadRole.AGENT and registered.process_alive
        assert registered.worktree != str(project)
        native = Thread("wire-proof", frozenset(), str(project), created_at=1.0)
        assert native.execution is NativeThreadExecution
        assert "execution" not in native.to_wire()
        assert FieldCodec.decode(Thread, registered.to_wire()) == registered
        await cli.invoke("send", "--from", NAME, "--to", CHANNEL, "--body", SEED)

    async def acceptance(app, pilot, agent, comms, entered, release, hold_next, requests):
        assert type(app._driver).__name__ == "LinuxDriver" and not app._headless
        original_native = comms.registry.require("beta").process_identity
        original_mode = app.selected_mode

        async def phase(label):
            await pilot.pause()
            from PIL import ImageGrab
            ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(evidence / f"{label}.png")
            (evidence / f"{label}-paint.txt").write_text(screen_paint(app))
            receipt["phases"].append({"phase": label,
                "seconds": monotonic() - started, "session": app.selected_session.id,
                "driver": type(app._driver).__name__,
                "external": comms.registry.require(NAME).to_wire(),
                "presentation": FieldCodec.encode(comms.views.thread_presentation(NAME))})
            (evidence / "journey.json").write_text(json.dumps(receipt, indent=2))

        # Actual channel-bar row, then its originally mounted participant row.
        row = await reveal_thread_row(app, pilot, NAME, CHANNEL)
        group_row = next(row for row in app.screen.query(CommsRow)
                         if row.target_name == CHANNEL)
        group_row.scroll_visible(animate=False, immediate=True)
        await pilot.pause()
        assert await pilot.click(group_row)
        await until(pilot, lambda: isinstance(app.selected_session, CommsScreen))
        channel_screen = app.selected_session
        await channel_screen.wait_content_ready()
        channel = channel_screen.query_one(CommsChatView)
        await until(pilot, lambda: SEED in screen_paint(app))
        await submit_editor(pilot, channel.prompt.prompt_text_area, CHANNEL_INPUT)
        await until(pilot, lambda: CHANNEL_INPUT in screen_paint(app))
        await until(pilot, lambda: any("Waiting for agent" in str(item.title)
                    for item in channel.query(MessageNotifications)))
        await phase("channel-pending")

        pending = await cli.invoke("inbox", "--thread", NAME)
        assert sum(message["body"] == CHANNEL_INPUT for message in pending["messages"]) == 1
        acknowledgement = await cli.invoke("ack", "--thread", NAME)
        assert acknowledgement["acknowledged"] == 1
        await until(pilot, lambda: any("Checked by CLI" in str(item.title)
                    for item in channel.query(MessageNotifications)))
        await phase("channel-checked")

        row = await reveal_thread_row(app, pilot, NAME, CHANNEL)
        assert await pilot.click(row)
        await until(pilot, lambda: app.selected_session is not channel_screen)
        dm_screen = app.selected_session
        await dm_screen.wait_content_ready()
        dm = dm_screen.query_one(CommsChatView)
        assert dm.target == NAME and dm.kind == "dm" and dm.agent is None
        assert comms.registry.require(NAME).session_file is None
        assert comms.registry.require(NAME).model is None
        assert comms.registry.require("beta").process_identity == original_native
        await submit_editor(pilot, dm.prompt.prompt_text_area, DM_INPUT)
        await until(pilot, lambda: DM_INPUT in screen_paint(app))
        await phase("dm-pending")
        pending = await cli.invoke("inbox", "--thread", NAME)
        assert sum(message["body"] == DM_INPUT for message in pending["messages"]) == 1
        assert (await cli.invoke("ack", "--thread", NAME))["acknowledged"] == 1
        await until(pilot, lambda: any("Checked by CLI" in str(item.title)
                    for item in dm.query(MessageNotifications)))
        user = comms.messaging.user_identity(str(dm.project_path)).name
        await cli.invoke("send", "--from", NAME, "--to", user, "--body", REPLY)
        await until(pilot, lambda: REPLY in screen_paint(app))
        messages = tuple(comms.bus.log.full_history())
        reply = next(message for message in messages if message.body == REPLY)
        assert reply.sender == NAME
        assert len([message for message in messages if message.body == DM_INPUT]) == 1
        await phase("dm-reply")

        await cli.retire()
        assert not comms.registry.require(NAME).process_alive
        await until(pilot, lambda: "CLI offline" in screen_paint(app))
        await phase("external-offline")
        # Return/open still uses the original bus tab; native capability refuses
        # attachment before cwd validation, without any session or owner spawn.
        await click_tab(app, pilot, channel_screen.id)
        row = await reveal_thread_row(app, pilot, NAME, CHANNEL)
        assert await pilot.click(row)
        await until(pilot, lambda: app.selected_session is dm_screen)
        client = CommsClient(comms, runtime_enabled=True)
        try:
            try:
                await client.load_session(cwd=str(app.project_dir), session_id=NAME)
            except Exception as error:
                receipt["direct_acp_refusal"] = str(error)
            else:
                raise AssertionError("External CLI unexpectedly accepted native ACP load")
        finally:
            await client.shutdown()
        try:
            await asyncio.to_thread(comms.owners.start, NAME)
        except RelationViolationError:
            pass
        else:
            raise AssertionError("External CLI unexpectedly started a native Pi")
        assert comms.registry.require(NAME).session_file is None
        assert comms.registry.require("beta").process_identity == original_native
        assert not requests, "External CLI UI interaction called a native provider"
        assert sum(thread.session_file is not None for thread in comms.registry.all_threads().values()) == 1
        receipt["completed"] = True
        receipt["native_owner_unchanged"] = True
        await phase("return-no-native-spawn")

    try:
        await native_fixture(app_type=InstalledApp, prepare_state=prepare,
            acceptance=acceptance, headless=False, provider_request_budget=0,
            fixture_stage=os.environ["EXTERNAL_CLI_FIXTURE"])
    finally:
        if cli is not None:
            await cli.retire()
        receipt["duration_seconds"] = monotonic() - started
        (evidence / "journey.json").write_text(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participant", nargs=2, type=Path)
    arguments = parser.parse_args()
    if arguments.participant:
        participant(*arguments.participant)
    else:
        asyncio.run(journey())
