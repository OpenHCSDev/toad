"""Does what the prompt says: the prompt is a JSON list of steps (see ``support.agents.script``).

- ``{"update": {...}}`` sends that ``session/update`` as written, valid or not.
- ``{"say": "text"}`` sends an agent message chunk.
- ``{"wait": "name"}`` waits until the test releases ``name`` (``Workspace.release``).
- ``{"ask": "title", "options": ["Allow", "Reject"]}`` asks the user for permission and records
  the answer as ``{"answered": <option name or "cancelled">}``.

A prompt that is not such a list is answered like the echo peer.
"""

import asyncio
import json

from base import Peer


class ScriptedPeer(Peer):
    async def answer(self, session_id: str, text: str) -> None:
        try:
            steps = json.loads(text)
        except json.JSONDecodeError:
            steps = None
        if not isinstance(steps, list):
            return await super().answer(session_id, text)
        for step in steps:
            if "update" in step:
                print(json.dumps({"jsonrpc": "2.0", "method": "session/update",
                                  "params": {"sessionId": session_id, "update": step["update"]}}), flush=True)
            elif "say" in step:
                await self.say(session_id, step["say"])
            elif "ask" in step:
                from acp.schema import PermissionOption, ToolCallUpdate

                names = step.get("options", ["Allow", "Reject"])
                kinds = {"Allow": "allow_once", "Reject": "reject_once"}
                answer = await self.connection.request_permission(
                    session_id=session_id,
                    tool_call=ToolCallUpdate(tool_call_id="scripted-ask", title=step["ask"], kind="other"),
                    options=[PermissionOption(option_id=name, name=name, kind=kinds.get(name, "allow_once"))
                             for name in names])
                self.record(answered=getattr(answer.outcome, "option_id", "cancelled"))
            elif "wait" in step:
                async with asyncio.timeout(60):
                    while not (self.project / f"released-{step['wait']}").exists():
                        await asyncio.sleep(.02)
            self.record(done=step)


if __name__ == "__main__":
    ScriptedPeer.main()
