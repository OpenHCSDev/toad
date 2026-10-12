"""The completion peer, which also records that a frame was drawn before its session began."""

import json
from time import monotonic_ns

from completion import CompletionPeer


class FramePeer(CompletionPeer):
    async def new_session(self, cwd, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        frames = list(map(json.loads, (self.project / "frames.jsonl").read_text().splitlines()))
        latest = frames[-1]
        assert latest["ready"] and latest["driver"] == "LinuxDriver", latest
        self.record(new_session_after_frame=latest, peer_time_ns=monotonic_ns())
        return response


if __name__ == "__main__":
    FramePeer.main()
