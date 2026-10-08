"""External JSON-RPC input decoded once; original ACP payload identity is retained."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
import json

from toad.acp.api import API
from toad.render_backend import RenderTask


@dataclass(frozen=True, kw_only=True)
class IncomingWireMessage(ABC):
    source: str | None = None

    @classmethod
    def read(cls, line: bytes):
        """Acquire strict text and its envelope before touching session state."""
        try:
            source = line.decode("utf-8")
        except Exception as error:
            return WireInputFailure(message=f"[error] Unable to decode utf-8 from agent: {error}")
        try:
            value = json.loads(source)
        except Exception as error:
            return WireInputFailure(source=source, message=f"[error] failed to decode JSON from agent: {error}")
        try:
            return replace(cls.decode(value), source=source)
        except ValueError as error:
            return WireInputFailure(source=source, message=f"[error] {error}")

    @classmethod
    def decode(cls, value):
        if isinstance(value, dict):
            return (
                WireResponse(value)
                if "result" in value or "error" in value
                else WireCall(value)
            )
        if isinstance(value, list) and all(
            isinstance(item, dict) and ("result" in item or "error" in item)
            for item in value
        ):
            return WireResponse(value)
        raise ValueError("Agent sent an invalid JSON-RPC object or response batch")

    async def receive(self, process, call_jsonrpc):
        # Logging precedes delivery, including failed JSON/envelope reads.
        # Actual membership and route admission remain process-owned at use.
        if self.source is not None:
            for session in tuple(process.sessions):
                session.agent.log(f"[agent] {self.source}")
        await self.deliver(process, call_jsonrpc)

    @abstractmethod
    async def deliver(self, process, call_jsonrpc): ...


@dataclass(frozen=True)
class WireInputFailure(IncomingWireMessage):
    message: str

    async def deliver(self, process, call_jsonrpc):
        process.agent.log(self.message)


@dataclass(frozen=True)
class WireResponse(IncomingWireMessage):
    payload: dict | list[dict]

    async def deliver(self, process, call_jsonrpc):
        API.process_response(self.payload)


@dataclass(frozen=True)
class WireCall(IncomingWireMessage):
    payload: dict

    async def deliver(self, process, call_jsonrpc):
        import asyncio

        agent = process.recipient(self.payload)
        if agent is None or agent.server.requires_ordered_dispatch(self.payload):
            await call_jsonrpc(self.payload, agent)
        else:
            agent.session.start_operation(call_jsonrpc(self.payload, agent))
            await asyncio.sleep(0)


@dataclass(frozen=True)
class ReadAgentWireTask(RenderTask[IncomingWireMessage]):
    """Submit the original wire acquisition to the existing SDK worker owner."""

    line: bytes

    def execute(self) -> IncomingWireMessage:
        return IncomingWireMessage.read(self.line)

    def accept_result(self, result: object) -> IncomingWireMessage:
        if not isinstance(result, IncomingWireMessage):
            raise TypeError("ACP wire worker returned an invalid result")
        return result
