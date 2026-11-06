"""Does what the prompt says: the prompt is a JSON list of steps (see ``steps`` and
``support.agents.script``). A prompt that is not such a list is answered like the echo peer."""

import json

from base import Peer
from steps import PeerStep


class ScriptedPeer(Peer):
    async def answer(self, session_id: str, text: str) -> None:
        try:
            steps = json.loads(text)
        except json.JSONDecodeError:
            steps = None
        if not isinstance(steps, list):
            return await super().answer(session_id, text)
        for step in steps:
            await self.perform(session_id, step)

    async def perform(self, session_id: str, raw: dict) -> object:
        """Run one step, as written, and record that it finished."""
        outcome = await PeerStep.decode(raw).perform(self, session_id)
        self.record(done=raw)
        return outcome


if __name__ == "__main__":
    ScriptedPeer.main()
