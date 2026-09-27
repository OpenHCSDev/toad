"""Provider-free mounted private USER channel/DM compose and UNKNOWN no-retry.

Run with an isolated integration source containing reviewed PR116 route guard and
reviewed private USER ingress. This pilot never launches ACP or a provider.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_comms import ThreadRole
from agent_comms.bus_publication import stable_thread_lookup
from agent_comms.cohort_schema import install_private_cohort_schema
from agent_comms.coordination_cohort import accept_initial_cohort
from agent_comms.coordination_store import MutationStore
from agent_comms.declarations import HumanInitialUnknownError
from agent_comms.operations import wire
from default_route_pilot import private_root, route

from toad import messages
from toad.app import ToadApp
from toad.widgets.comms_chat import CommsChatView


async def main() -> None:
    if os.name != "posix" or Path("/var").is_symlink():
        raise RuntimeError("private USER pilot needs real /var/tmp ancestry")
    with tempfile.TemporaryDirectory(
        prefix="toad-user-home-", dir="/dev/shm"
    ) as directory:
        sandbox = Path(directory)
        sandbox.chmod(0o700)
        home = sandbox / "home"
        home.mkdir(mode=0o700)
        with tempfile.TemporaryDirectory(
            prefix="toad-user-private-", dir="/var/tmp"
        ) as private_dir:
            root, root_id = private_root(
                Path(private_dir) / "wire", sandbox, "INITIAL-CHANNEL"
            )
            store = MutationStore(
                str(root / "coordination.sqlite"), clock_ms=lambda: 9999
            )
            install_private_cohort_schema(store)
            for name in ("owner", "peer"):
                thread = wire(root).registry.require(name)
                store.register_participant(
                    stable_thread_lookup(thread.created_at), name, name, committed=True
                )

            def assert_sql_receipt(
                sequence: int, message_id: str, members: int
            ) -> None:
                result = accept_initial_cohort(wire(root).bus, root_id, sequence, store)
                assert result.value.member_count == members
                with sqlite3.connect(root / "coordination.sqlite") as connection:
                    row = connection.execute(
                        "SELECT message_id,member_count,sealed "
                        "FROM claim_batch_receipts WHERE wire_root_id=? AND wire_seq=?",
                        (root_id, sequence),
                    ).fetchone()
                assert row == (message_id, members, 1)

            with patch.dict(
                os.environ,
                {
                    "HOME": str(home),
                    "XDG_CONFIG_HOME": str(sandbox / "config"),
                    "XDG_DATA_HOME": str(sandbox / "data"),
                    "XDG_STATE_HOME": str(sandbox / "state"),
                },
            ):
                os.environ.pop("AGENT_COMMS_ROOT", None)
                route(home, root, root_id)
                app = ToadApp(project_dir=str(sandbox))
                async with app.run_test(size=(115, 38)) as pilot:
                    await pilot.pause()
                    owner_mode = app.current_mode
                    await app.open_comms_session(
                        owner_mode=owner_mode,
                        project_path=sandbox,
                        me="user",
                        target="#team",
                        kind="channel",
                    )
                    channel = app.screen.query_one(CommsChatView)
                    await channel._refresh()
                    await channel.submit_input(
                        messages.UserInputSubmitted("HUMAN-CHANNEL")
                    )
                    await pilot.pause()
                    channel_rows = [
                        message
                        for message, _ in channel._history
                        if message.body == "HUMAN-CHANNEL"
                    ]
                    assert len(channel_rows) == 1
                    channel_receipt = channel_rows[0]
                    assert channel_receipt.sender_role is ThreadRole.USER
                    assert (
                        wire(root)
                        .bus.read_initial_cohort(root_id, channel_receipt.seq)
                        .message
                        == channel_receipt
                    )
                    assert channel.prompt.text == "" and channel._unknown_send is None
                    assert_sql_receipt(
                        channel_receipt.seq, channel_receipt.message_id, 2
                    )

                    await app.open_comms_session(
                        owner_mode=owner_mode,
                        project_path=sandbox,
                        me="user",
                        target="peer",
                        kind="dm",
                    )
                    dm = app.screen.query_one(CommsChatView)
                    await dm._refresh()
                    await dm.submit_input(messages.UserInputSubmitted("HUMAN-DM"))
                    await pilot.pause()
                    dm_rows = [
                        message
                        for message, _ in dm._history
                        if message.body == "HUMAN-DM"
                    ]
                    assert len(dm_rows) == 1
                    dm_receipt = dm_rows[0]
                    assert dm_receipt.sender_role is ThreadRole.USER
                    assert (
                        wire(root)
                        .bus.read_initial_cohort(root_id, dm_receipt.seq)
                        .message
                        == dm_receipt
                    )
                    assert dm.prompt.text == "" and dm._unknown_send is None
                    assert_sql_receipt(dm_receipt.seq, dm_receipt.message_id, 1)

                    original_append = dm._wire.bus._append_private_unlocked
                    original_send = dm._wire.send_user_message
                    unknown_errors: list[HumanInitialUnknownError] = []
                    calls = 0

                    def append_then_lose_receipt(metadata, row):
                        nonlocal calls
                        calls += 1
                        original_append(metadata, row)
                        raise OSError("simulated post-append lost receipt")

                    def observe_unknown(*args, **kwargs):
                        try:
                            return original_send(*args, **kwargs)
                        except HumanInitialUnknownError as error:
                            unknown_errors.append(error)
                            raise

                    with (
                        patch.object(
                            dm._wire.bus,
                            "_append_private_unlocked",
                            append_then_lose_receipt,
                        ),
                        patch.object(dm._wire, "send_user_message", observe_unknown),
                    ):
                        uncertain = messages.UserInputSubmitted("UNCERTAIN-NO-RETRY")
                        await dm.submit_input(uncertain)
                        assert calls == 1
                        assert dm.prompt.text == uncertain.body
                        assert dm.prompt.prompt_text_area.disabled
                        assert len(unknown_errors) == 1
                        assert dm._unknown_send is not None
                        unknown_root, unknown_seq, unknown_id = dm._unknown_send
                        assert dm._unknown_send == (
                            unknown_errors[0].wire_root_id,
                            unknown_errors[0].wire_seq,
                            unknown_errors[0].message_id,
                        )
                        assert unknown_id in dm.status and str(unknown_seq) in dm.status
                        assert unknown_root == root_id
                        actual = wire(root).bus.read_initial_cohort(
                            root_id, unknown_seq
                        )
                        assert actual.message.message_id == unknown_id
                        await dm.submit_input(uncertain)
                        assert calls == 1, "uncertain input was replayed"

                    await app.open_comms_session(
                        owner_mode=owner_mode,
                        project_path=sandbox,
                        me="user",
                        target="#team",
                        kind="channel",
                    )
                    channel = app.screen.query_one(CommsChatView)
                    before = len(wire(root).bus.full_history())
                    original_open = os.open
                    pre_row_calls = 0
                    pre_row_errors: list[HumanInitialUnknownError] = []
                    channel_send = channel._wire.send_user_message

                    def fail_bus_open(path, *args, **kwargs):
                        if Path(path) == root / "bus.jsonl":
                            raise OSError("simulated reservation-only lost append")
                        return original_open(path, *args, **kwargs)

                    def observe_pre_row(*args, **kwargs):
                        nonlocal pre_row_calls
                        pre_row_calls += 1
                        try:
                            return channel_send(*args, **kwargs)
                        except HumanInitialUnknownError as error:
                            pre_row_errors.append(error)
                            raise

                    with (
                        patch("os.open", fail_bus_open),
                        patch.object(
                            channel._wire, "send_user_message", observe_pre_row
                        ),
                    ):
                        pre_row = messages.UserInputSubmitted("PRE-ROW-UNKNOWN")
                        await channel.submit_input(pre_row)
                        assert pre_row_calls == 1 and len(pre_row_errors) == 1
                        assert channel._unknown_send == (
                            pre_row_errors[0].wire_root_id,
                            pre_row_errors[0].wire_seq,
                            pre_row_errors[0].message_id,
                        )
                        assert channel.prompt.text == pre_row.body
                        assert channel.prompt.prompt_text_area.disabled
                        await channel.submit_input(pre_row)
                        assert pre_row_calls == 1
                    assert len(wire(root).bus.full_history()) == before

                    # A different fresh mounted view must also fail closed on
                    # core's permanent human reservation-gap admission.
                    await app.open_comms_session(
                        owner_mode=owner_mode,
                        project_path=sandbox,
                        me="user",
                        target="owner",
                        kind="dm",
                    )
                    blocked = app.screen.query_one(CommsChatView)
                    blocked_send = blocked._wire.send_user_message
                    blocked_calls = 0

                    def observe_blocked(*args, **kwargs):
                        nonlocal blocked_calls
                        blocked_calls += 1
                        return blocked_send(*args, **kwargs)

                    with patch.object(
                        blocked._wire, "send_user_message", observe_blocked
                    ):
                        denied = messages.UserInputSubmitted("AFTER-GAP-BLOCKED")
                        await blocked.submit_input(denied)
                        assert blocked_calls == 1
                        assert blocked._human_admission_blocked
                        assert blocked.prompt.text == denied.body
                        assert blocked.prompt.prompt_text_area.disabled
                        await blocked.submit_input(denied)
                        assert blocked_calls == 1
                    assert len(wire(root).bus.full_history()) == before


if __name__ == "__main__":
    asyncio.run(main())
