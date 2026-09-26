"""Mounted Conversation + actual Agent new/load/update paths, provider-free."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime_fixture import ToadApp

from toad.acp import messages
from toad.acp.agent import Agent
from toad.private_native_cursor import LABELS, TOOLTIP
from toad.screens.main import MainScreen
from toad.widgets.native_history import NativeHistory

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/private_native_cursor_v1.json").read_text()
)
AGENT_DATA = {
    "name": "Fixture",
    "identity": "fixture",
    "short_name": "fixture",
    "run_command": {"*": "true"},
    "protocol": "acp",
}


def update(cursor):
    return {
        "sessionUpdate": "session_info_update",
        "_meta": {"agentComms": {"privateNativeCursor": cursor}},
    }


async def main():
    with TemporaryDirectory(prefix="toad-native-cursor-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_STATE_HOME=str(root / "state"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(115, 38)) as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            view = app.screen.conversation
            agent = Agent(root, AGENT_DATA, "beta")
            agent._message_target = view
            view.agent = agent
            await pilot.pause()
            row = view.query_one(NativeHistory)
            assert not row.display
            seen = []
            original_post = agent.post_message

            def record(message):
                seen.append(type(message).__name__)
                return original_post(message)

            agent.post_message = record

            async def load(cursor, *, before=(), new=False):
                class Response:
                    async def wait(self):
                        for value in before:
                            agent.rpc_session_update("beta", update(value))
                        return {
                            "sessionId": "beta",
                            "_meta": {"agentComms": {"privateNativeCursor": cursor}},
                        }

                api_name = "session_new" if new else "session_load"
                with patch(f"toad.acp.agent.api.{api_name}", return_value=Response()):
                    await (agent.acp_new_session() if new else agent.acp_load_session())
                await pilot.pause()

            def side_effect_state():
                return (
                    tuple(view.queued_prompts),
                    view.delivering_prompt,
                    view.sending_queued_prompt,
                    view.prompt.text,
                    deepcopy(view.input_delivery),
                    view._transcript_generation,
                    view._managed_turn_id,
                    tuple(view.contents.children),
                    view.busy_count,
                )

            async def callback(cursor, session="beta"):
                before = side_effect_state()
                seen.clear()
                agent.rpc_session_update(session, update(cursor))
                await pilot.pause()
                assert side_effect_state() == before
                assert set(seen) <= {"PrivateNativeCursorUpdate"}, seen

            async def painted(status, artifact=None):
                await pilot.pause()
                assert view.native_history_status == status
                assert row.status == status and row.display
                assert LABELS[status] == str(row.render())
                assert row.tooltip == TOOLTIP
                assert row in app.screen._compositor.visible_widgets
                assert row.region.height > 0 and row.region.width > 0
                svg = app.export_screenshot()
                for secret in (
                    "recipient-opaque",
                    "native-session-opaque",
                    "claim-opaque",
                    "b" * 32,
                    "wireRootId",
                    "ownerPid",
                    "ownerEpoch",
                    "input_id",
                ):
                    assert secret not in svg and secret not in str(row.tooltip)
                if artifact and (output := os.environ.get("CURSOR_EVIDENCE_DIR")):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    (Path(output) / f"{artifact}.svg").write_text(svg)

            # Genuine trusted new startup, through the actual Agent method.
            await load(FIXTURE["trustedLoad"]["cursor"], new=True)
            await painted("proven", "proven")
            view.queued_prompts = ["remote pending", "remote pending"]
            view.prompt.text = "editable draft"
            await pilot.pause()
            for event in FIXTURE["updates"]:
                await callback(event["cursor"])
                await painted("unavailable")
            assert agent._private_cursor.current.scope.owner_epoch == 2
            # Automatic proxy ready has no trusted cursor channel; config-only
            # reconnect cannot bind or restore old proof.
            agent.rpc_session_update(
                "beta", {"sessionUpdate": "config_option_update", "configOptions": []}
            )
            await pilot.pause()
            await painted("unavailable", "quarantined")
            await load(FIXTURE["nextTrustedLoad"]["cursor"])
            await painted("none", "none")
            for event in FIXTURE["afterNextLoad"]:
                await callback(event["cursor"])
            await painted("unavailable")

            # Retired request/Agent events cannot repaint the successor view.
            stale_agent = agent
            stale_receipt = messages.PrivateNativeCursorUpdate(
                "proven", stale_agent, "beta", 9999
            )
            agent = Agent(root, AGENT_DATA, "beta")
            agent._message_target = view
            view.agent = agent
            await pilot.pause()
            assert not row.display
            original_post = agent.post_message
            agent.post_message = record
            race = FIXTURE["prebindRace"]
            await load(
                race["delayedTrustedLoad"], before=[race["callbackBeforeTrustedResult"]]
            )
            await painted("unavailable", "prebind-race")
            assert agent._private_cursor.floor.owner_epoch == 4
            await load(race["subsequentTrustedLoad"])
            await painted("none")
            view.post_message(stale_receipt)
            stale_agent.rpc_session_update(
                "beta", update(FIXTURE["trustedLoad"]["cursor"])
            )
            await pilot.pause()
            await painted("none")

            # Lower epoch after trusted newer none, foreign scope/session,
            # equal conflict, and reordered revisions all preserve status.
            await callback(FIXTURE["trustedLoad"]["cursor"])
            await callback({}, "foreign-session")
            foreign = deepcopy(race["subsequentTrustedLoad"])
            foreign["scope"]["wireRootId"] = "f" * 32
            await callback(foreign)
            await painted("none")
            for revision, status in ((8, "unavailable"), (7, "none"), (8, "none")):
                agent.rpc_session_update(
                    "beta",
                    update(
                        {
                            **race["subsequentTrustedLoad"],
                            "revision": revision,
                            "status": status,
                        }
                    ),
                )
            await pilot.pause()
            await painted("unavailable")
            old_sequence = agent._private_cursor_sequence - 1
            view.post_message(
                messages.PrivateNativeCursorUpdate(
                    "proven", agent, "beta", old_sequence
                )
            )
            await pilot.pause()
            await painted("unavailable")

            # Independent review regression: a second explicit load supersedes
            # an uncertain first load BEFORE its delayed response can compare
            # buffered epochs. Clearing uncertainty must not erase epoch4.
            for uncertainty in ("malformed", "overflow"):
                agent = Agent(root, AGENT_DATA, "beta")
                agent._message_target = view
                view.agent = agent
                original_post = agent.post_message
                agent.post_message = record
                await load(FIXTURE["trustedLoad"]["cursor"])
                entered, release = asyncio.Event(), asyncio.Event()

                class DelayedResponse:
                    async def wait(self, entered=entered, release=release):
                        entered.set()
                        await release.wait()
                        return {
                            "_meta": {
                                "agentComms": {
                                    "privateNativeCursor": FIXTURE["trustedLoad"][
                                        "cursor"
                                    ]
                                }
                            }
                        }

                with patch(
                    "toad.acp.agent.api.session_load", return_value=DelayedResponse()
                ):
                    pending = asyncio.create_task(agent.acp_load_session())
                    await entered.wait()
                    await callback(race["callbackBeforeTrustedResult"])
                    if uncertainty == "malformed":
                        await callback({})
                    else:
                        for _ in range(32):
                            agent.rpc_session_update(
                                "beta", update(FIXTURE["trustedLoad"]["cursor"])
                            )
                    await load(FIXTURE["trustedLoad"]["cursor"])
                    await painted("unavailable")
                    assert agent._private_cursor.floor.owner_epoch == 4
                    release.set()
                    await pending
                await painted("unavailable")
                await load(race["subsequentTrustedLoad"])
                await painted("none")

            # Separate fresh trusted source covers coverage-only, overflow,
            # malformed metadata and null scope without any input effects.
            coverage = deepcopy(FIXTURE["coverageOnlyExample"])
            coverage["scope"]["sessionId"] = "beta"
            await load(coverage)
            await painted("coverage_only", "coverage-only")
            # Stopped-owner null metadata before the result poisons that request;
            # only a load initiated after the observation may recover.
            await load(
                coverage,
                before=[
                    {
                        "version": 1,
                        "scope": None,
                        "revision": 4,
                        "status": "unavailable",
                    }
                ],
            )
            await painted("unavailable")
            await load(coverage)
            await painted("coverage_only")
            await callback({"version": 2})
            await painted("unavailable")
            await load(coverage, before=[coverage] * 33)
            await painted("unavailable")
            assert len(agent._private_cursor._buffer) == 32
            await load(coverage)
            await painted("coverage_only")
            await callback(
                {"version": 1, "scope": None, "revision": 2, "status": "unavailable"}
            )
            await painted("unavailable")
            await load(coverage)
            before = side_effect_state()
            await agent.stop()
            await pilot.pause()
            await painted("unavailable")
            await callback(coverage)
            assert side_effect_state() == before
            assert app._exception is None
        await asyncio.get_running_loop().shutdown_default_executor()
    print(
        "PASS mounted cursor: actual new/load + callback; canonical postbind/prebind; all four labels; batching/revision/foreign/retired fences; overflow/malformed/null/stop; private data absent; zero queue/input effects"
    )


if __name__ == "__main__":
    asyncio.run(main())
