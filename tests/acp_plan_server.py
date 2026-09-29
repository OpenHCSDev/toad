"""Local official-SDK ACP peer; a prompt is the external plan to publish.

There is no model, provider call or patched Toad transport in this fixture.
"""
import asyncio
import json
from pathlib import Path

from acp import Agent, Client, run_agent
from acp.schema import (
    AgentPlanUpdate,
    InitializeResponse,
    NewSessionResponse,
    Plan,
    PromptResponse,
)


class PlanPeer(Agent):
    def on_connect(self, conn: Client) -> None:
        self.connection = conn

    async def initialize(self, protocol_version: int, **kwargs):
        return InitializeResponse(protocolVersion=protocol_version)

    async def new_session(self, cwd: str, **kwargs):
        self.project = Path(cwd)
        return NewSessionResponse(sessionId="plan-acceptance")

    async def prompt(self, session_id, prompt, **kwargs):
        for index, raw_plan in enumerate(json.loads(prompt[0].text)):
            plan = Plan.model_validate(raw_plan, strict=True)
            await self.connection.session_update(
                session_id=session_id,
                update=AgentPlanUpdate(sessionUpdate="plan", entries=plan.entries),
            )
            async with asyncio.timeout(20):
                while not (self.project / f"plan-advance-{index}").exists():
                    await asyncio.sleep(.02)
        # A nonconforming external peer can still write arbitrary JSON to its
        # transport. Exercise the installed client's SDK rejection boundary.
        for invalid in (
            {"content": "Invalid status", "priority": "high", "status": "unknown"},
            {"content": "Missing priority", "status": "pending"},
            {"content": 23, "priority": "high", "status": "pending"},
        ):
            print(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                              "params": {"sessionId": session_id,
                                         "update": {"sessionUpdate": "plan", "entries": [invalid]}}}),
                  flush=True)
        return PromptResponse(stopReason="end_turn")


if __name__ == "__main__":
    asyncio.run(run_agent(PlanPeer()))
