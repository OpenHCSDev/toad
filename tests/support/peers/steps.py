"""One step a scripted peer performs, decoded once from its JSON form.

- ``{"update": {...}}`` sends that ``session/update`` as written, valid or not.
- ``{"say": "text"}`` sends an agent message chunk.
- ``{"wait": "name"}`` waits until the test releases ``name`` (``Workspace.release``).
- ``{"ask": "title", "options": ["Allow", "Reject"]}`` asks the user for permission.
- ``{"permission": {"toolCall": {...}, "options": [...]}}`` asks with an ACP request as given.

Any step may carry ``"session"``: the session id it acts under, instead of the peer's own.
Each step answers with its outcome; an ask's is the permission outcome as the pipe carries it.
"""

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass, replace
import json
from typing import ClassVar, Literal, Self

from acp.schema import AllowedOutcome, PermissionOption, RequestPermissionResponse, ToolCallUpdate
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

OptionKind = Literal["allow_once", "allow_always", "reject_once", "reject_always"]


class PeerSession(ABC):
    """Which session a step acts under."""

    @classmethod
    def decode(cls, raw: dict) -> "PeerSession":
        """The JSON boundary: a step that names a session acts under it."""
        return NamedSession(TypeAdapter(str).validate_python(raw["session"])) if "session" in raw else OwnSession()

    @abstractmethod
    def session_for(self, own: str) -> str: ...


@dataclass(frozen=True)
class OwnSession(PeerSession):
    """The peer's own session."""

    def session_for(self, own: str) -> str:
        return own


@dataclass(frozen=True)
class NamedSession(PeerSession):
    """Another session id, sent as given (Toad refuses one it does not hold)."""

    name: str

    def session_for(self, own: str) -> str:
        return self.name


@dataclass(frozen=True, kw_only=True)
class PeerStep(ABC):
    """A step names its member by the one key it carries; its fields are decoded once, here."""

    key: ClassVar[str]
    members: ClassVar[dict[str, type["PeerStep"]]] = {}
    session: PeerSession = OwnSession()

    def __init_subclass__(cls, *, key: str | None = None, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if key is not None:
            cls.key = key
            PeerStep.members[key] = cls

    @classmethod
    def decode(cls, raw: dict) -> "PeerStep":
        """The JSON boundary: the step's one known key selects its member, which decodes the rest."""
        (key,) = raw.keys() & cls.members.keys()
        return replace(cls.members[key].from_raw(raw[key], raw), session=PeerSession.decode(raw))

    @classmethod
    @abstractmethod
    def from_raw(cls, value: object, raw: dict) -> Self: ...

    def session_for(self, session_id: str) -> str:
        return self.session.session_for(session_id)

    @abstractmethod
    async def perform(self, peer, session_id: str) -> object:
        """Do the step for ``session_id``; the outcome goes back to whoever sent it."""


@dataclass(frozen=True, kw_only=True)
class UpdateStep(PeerStep, key="update"):
    update: dict[str, JsonValue]

    @classmethod
    def from_raw(cls, value: object, raw: dict) -> Self:
        return cls(update=TypeAdapter(dict[str, JsonValue]).validate_python(value))

    async def perform(self, peer, session_id: str) -> object:
        print(json.dumps({"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": self.session_for(session_id), "update": self.update}}), flush=True)
        return {}


@dataclass(frozen=True, kw_only=True)
class SayStep(PeerStep, key="say"):
    text: str

    @classmethod
    def from_raw(cls, value: object, raw: dict) -> Self:
        return cls(text=TypeAdapter(str).validate_python(value))

    async def perform(self, peer, session_id: str) -> object:
        await peer.say(self.session_for(session_id), self.text)
        return {}


@dataclass(frozen=True, kw_only=True)
class WaitStep(PeerStep, key="wait"):
    name: str

    @classmethod
    def from_raw(cls, value: object, raw: dict) -> Self:
        return cls(name=TypeAdapter(str).validate_python(value))

    async def perform(self, peer, session_id: str) -> object:
        async with asyncio.timeout(60):
            while not (peer.project / f"released-{self.name}").exists():
                await asyncio.sleep(.02)
        return {}


@dataclass(frozen=True, kw_only=True)
class AsksPermission(PeerStep):
    """Ask Toad's user; recording and answering are the same for every way of asking."""

    tool_call: ToolCallUpdate
    options: tuple[PermissionOption, ...]

    async def perform(self, peer, session_id: str) -> object:
        answer = await peer.connection.request_permission(
            session_id=self.session_for(session_id), tool_call=self.tool_call, options=list(self.options))
        peer.record(answered=self.answered(answer))
        return answer.model_dump(mode="json", by_alias=True, exclude_none=True)

    @staticmethod
    def answered(answer: RequestPermissionResponse) -> str:
        """The ACP outcome union, decoded at the boundary: the chosen option, or cancelled."""
        match answer.outcome:
            case AllowedOutcome(option_id=chosen):
                return chosen
            case _:
                return "cancelled"


@dataclass(frozen=True, kw_only=True)
class AskStep(AsksPermission, key="ask"):
    kinds: ClassVar[dict[str, OptionKind]] = {"Allow": "allow_once", "Reject": "reject_once"}

    @classmethod
    def from_raw(cls, value: object, raw: dict) -> Self:
        names = TypeAdapter(list[str]).validate_python(raw.get("options", ["Allow", "Reject"]))
        return cls(
            tool_call=ToolCallUpdate(tool_call_id="scripted-ask", title=TypeAdapter(str).validate_python(value),
                                     kind="other"),
            options=tuple(PermissionOption(option_id=name, name=name, kind=cls.kinds.get(name, "allow_once"))
                          for name in names),
        )


@dataclass(frozen=True, kw_only=True)
class PermissionStep(AsksPermission, key="permission"):
    @classmethod
    def from_raw(cls, value: object, raw: dict) -> Self:
        request = PermissionRequestShape.model_validate(value)
        return cls(tool_call=request.tool_call, options=tuple(request.options))


class PermissionRequestShape(BaseModel):
    """The ACP permission request a ``permission`` step carries, validated as one record."""

    model_config = ConfigDict(populate_by_name=True)
    tool_call: ToolCallUpdate = Field(alias="toolCall")
    options: list[PermissionOption]
