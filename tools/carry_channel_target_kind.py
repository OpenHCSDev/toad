"""Carry saved channel history tabs onto the tagged ChannelTarget shape.

agent-comms 38bf91a8c made CommandTarget a declared family, so a channel target is stored
with its member tag. Tabs saved before it hold the bare target and refuse to decode, which
stops Toad at launch. The installer's carries cannot reach Toad's state file, so this step
runs once by hand on that file and is deleted after the live run. A carried file holds
no bare target, so a second run changes nothing.

    python tools/carry_channel_target_kind.py [--apply] [PATH]
"""

import argparse
import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from agent_comms.channel_targets import ChannelTarget

from toad.conversation_kind import ChannelConversation
from toad.db import DB, OpenTabRow, ToadDatabase
from toad.tab_identity import TabIdentity
from toad.tab_identity.kinds import HistoryTab

(IDENTITY,) = (field for field in OpenTabRow._fields if field.name == "identity")
TARGET_TAG = {ChannelTarget.family_discriminator: ChannelTarget.declared_name}


def carried(stored: dict) -> bool:
    """Tag the bare target of a saved channel history tab; report whether it changed."""
    tab = TabIdentity.family_discriminator
    conversation = ChannelConversation.family_discriminator
    if stored.get(tab) != HistoryTab.declared_name:
        return False
    key = stored["key"]
    if key.get(conversation) != ChannelConversation.declared_name:
        return False
    if ChannelTarget.family_discriminator in key["target"]:
        return False
    key["target"] = {**TARGET_TAG, **key["target"]}
    return True


def carry(path: Path, *, apply: bool) -> int:
    stored = DB(path).transaction(lambda db: [
        IDENTITY.storage.from_sql(identity)
        for (identity,) in db.execute(OpenTabRow._sql(
            f'SELECT {{identity}} FROM "{OpenTabRow.declared_name}" ORDER BY {{position}}'
        ))
    ])
    changed = sum(map(carried, stored))
    identities = tuple(map(IDENTITY.value.decode, stored))
    print(f"{path}: {len(identities)} tabs decode, {changed} carried")
    if apply and changed:
        backup = path.with_name(f"{path.name}.before-channel-target-kind")
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as copy:
            source.backup(copy)
        asyncio.run(DB(path).tab_roster(identities))
        print(f"backup {backup}")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", type=Path, default=ToadDatabase.path())
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    carry(arguments.path, apply=arguments.apply)


if __name__ == "__main__":
    main()
