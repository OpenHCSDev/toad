"""The relay's socket, both ends of it: where the peer publishes its port, and one step's
request and answer on the line.

A step that raises answers with its failure, so the sender gets the peer's own error
(Toad's refusal, a bad step) instead of a closed socket it can only report as "maybe".
Standard library only: the relay peer imports it as a script, the tests as a module.
"""

import asyncio
from collections.abc import Awaitable
import json
from pathlib import Path
from typing import Any

PORT_FILE = "peer-relay.port"


class RelayStepFailed(Exception):
    """The peer ran the step and it raised, or the peer closed without answering."""


async def answer(outcome: Awaitable[Any]) -> bytes:
    """The peer's side: one step's outcome, or its failure, as one line."""
    try:
        reply = {"done": await outcome}
    except Exception as error:  # Every failure goes back to the sender, named.
        # The error's own fields too: an ACP RequestError keeps its code and data there,
        # and its message alone ("Invalid params") says nothing about why.
        reply = {"failed": f"{type(error).__name__}: {error} {vars(error)}"}
    return json.dumps(reply).encode() + b"\n"


class RelaySocket:
    """The sender's side: one step per connection, so a pending ask never holds up an update."""

    def __init__(self, port: int) -> None:
        self.port = port

    @staticmethod
    def port_file(project: Path) -> Path:
        return project / PORT_FILE

    @classmethod
    def published(cls, project: Path) -> "RelaySocket":
        return cls(int(cls.port_file(project).read_text()))

    async def step(self, raw: dict[str, Any]) -> Any:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            writer.write(json.dumps(raw).encode() + b"\n")
            await writer.drain()
            line = await reader.readline()
        finally:
            writer.close()
        if not line:
            raise RelayStepFailed("The relay closed without answering")
        match json.loads(line):
            case {"done": outcome}:
                return outcome
            case {"failed": reason}:
                raise RelayStepFailed(reason)
