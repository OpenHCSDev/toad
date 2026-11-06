"""One step a scripted peer performs, decoded once from its JSON form.

- ``{"update": {...}}`` sends that ``session/update`` as written, valid or not; ``"session"``
  names another session id to send it under.
- ``{"say": "text"}`` sends an agent message chunk.
- ``{"wait": "name"}`` waits until the test releases ``name`` (``Workspace.release``).
- ``{"ask": "title", "options": ["Allow", "Reject"]}`` asks the user for permission.
- ``{"permission": {"toolCall": {...}, "options": [...]}}`` asks with an ACP request as given.

Each step answers with its outcome: an ask's is the permission outcome as the pipe carries it.
"""

import asyncio
import json
from typing import ClassVar

from acp.schema import PermissionOption, ToolCallUpdate


class PeerStep:
    """A step names its class by the one key it carries."""

    key: ClassVar[str]
    members: ClassVar[dict[str, type["PeerStep"]]] = {}

    def __init_subclass__(cls, *, key: str | None = None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if key is not None:
            cls.key = key
            PeerStep.members[key] = cls

    def __init__(self, raw: dict) -> None:
        self.raw = raw

    @classmethod
    def decode(cls, raw: dict) -> "PeerStep":
        """The JSON boundary: the step's one known key selects its member."""
        (key,) = raw.keys() & cls.members.keys()
        return cls.members[key](raw)

    async def perform(self, peer, session_id: str) -> object:
        """Do the step for ``session_id``; the outcome goes back to whoever sent it."""
        raise NotImplementedError


class UpdateStep(PeerStep, key="update"):
    async def perform(self, peer, session_id: str) -> object:
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": self.raw.get("session", session_id), "update": self.raw["update"]}}), flush=True)
        return {}


class SayStep(PeerStep, key="say"):
    async def perform(self, peer, session_id: str) -> object:
        await peer.say(session_id, self.raw["say"])
        return {}


class WaitStep(PeerStep, key="wait"):
    async def perform(self, peer, session_id: str) -> object:
        async with asyncio.timeout(60):
            while not (peer.project / f"released-{self.raw['wait']}").exists():
                await asyncio.sleep(.02)
        return {}


class AsksPermission(PeerStep):
    """Ask Toad's user; the record and the answer are the same for every way of asking."""

    def tool_call(self) -> ToolCallUpdate:
        raise NotImplementedError

    def options(self) -> list[PermissionOption]:
        raise NotImplementedError

    async def perform(self, peer, session_id: str) -> object:
        answer = await peer.connection.request_permission(
            session_id=session_id, tool_call=self.tool_call(), options=self.options())
        peer.record(answered=getattr(answer.outcome, "option_id", "cancelled"))
        return answer.model_dump(mode="json", by_alias=True, exclude_none=True)


class AskStep(AsksPermission, key="ask"):
    kinds: ClassVar[dict[str, str]] = {"Allow": "allow_once", "Reject": "reject_once"}

    def tool_call(self) -> ToolCallUpdate:
        return ToolCallUpdate(tool_call_id="scripted-ask", title=self.raw["ask"], kind="other")

    def options(self) -> list[PermissionOption]:
        return [PermissionOption(option_id=name, name=name, kind=self.kinds.get(name, "allow_once"))
                for name in self.raw.get("options", ["Allow", "Reject"])]


class PermissionStep(AsksPermission, key="permission"):
    def tool_call(self) -> ToolCallUpdate:
        return ToolCallUpdate.model_validate(self.raw["permission"]["toolCall"])

    def options(self) -> list[PermissionOption]:
        return [PermissionOption.model_validate(option) for option in self.raw["permission"]["options"]]
