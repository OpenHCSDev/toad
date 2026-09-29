"""Official stdio SDK peer observes actual installed terminal frame admission."""
import asyncio
import json
from time import monotonic_ns

from acp import run_agent
from acp_completion_server import CompletionPeer


class FramePeer(CompletionPeer):
    async def new_session(self, cwd, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        frames = list(map(json.loads, (self.project / "frames.jsonl").read_text().splitlines()))
        latest = frames[-1]
        assert latest["ready"] and latest["driver"] == "LinuxDriver", latest
        self.record({"new_session_after_frame": latest, "peer_time_ns": monotonic_ns()})
        return response


if __name__ == "__main__":
    asyncio.run(run_agent(FramePeer()))
