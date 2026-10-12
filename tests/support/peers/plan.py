"""Publishes the plans in the prompt, one per step.

The prompt is a JSON list of plans (each ``{"entries": [...]}``). After sending plan N the peer waits for
``plan-advance-N`` to exist in the project. When the list is done it writes three malformed plan updates to
its transport, as a nonconforming peer could, so the client's rejection boundary is exercised.
"""

import asyncio
import json

from acp.schema import AgentPlanUpdate, Plan, PromptResponse
from base import Peer


class PlanPeer(Peer):
    session_id = "plan-acceptance"

    async def prompt(self, session_id, prompt, **kwargs):
        for index, raw_plan in enumerate(json.loads(prompt[0].text)):
            plan = Plan.model_validate(raw_plan, strict=True)
            await self.connection.session_update(
                session_id=session_id, update=AgentPlanUpdate(sessionUpdate="plan", entries=plan.entries))
            async with asyncio.timeout(20):
                while not (self.project / f"plan-advance-{index}").exists():
                    await asyncio.sleep(.02)
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
    PlanPeer.main()
