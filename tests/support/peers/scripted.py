"""Does what the prompt says: the prompt is a JSON list of steps (see ``support.agents.script``).

- ``{"update": {...}}`` sends that ``session/update`` as written, valid or not.
- ``{"say": "text"}`` sends an agent message chunk.
- ``{"wait": "name"}`` waits until the test releases ``name`` (``Workspace.release``).

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
            elif "wait" in step:
                async with asyncio.timeout(60):
                    while not (self.project / f"released-{step['wait']}").exists():
                        await asyncio.sleep(.02)
            self.record(done=step)


if __name__ == "__main__":
    ScriptedPeer.main()
