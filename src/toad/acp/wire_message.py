"""External JSON-RPC input decoded once; original ACP payload identity is retained."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from toad.acp.api import API


class IncomingWireMessage(ABC):
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

    @abstractmethod
    async def receive(self, agent, call_jsonrpc, process_owner): ...


@dataclass(frozen=True)
class WireResponse(IncomingWireMessage):
    payload: dict | list[dict]

    async def receive(self, agent, call_jsonrpc, process_owner):
        API.process_response(self.payload)


@dataclass(frozen=True)
class WireCall(IncomingWireMessage):
    payload: dict

    async def receive(self, agent, call_jsonrpc, process_owner):
        import asyncio

        if agent.server.requires_ordered_dispatch(self.payload):
            await call_jsonrpc(self.payload)
        else:
            process_owner.start_operation(call_jsonrpc(self.payload))
            await asyncio.sleep(0)
