"""The scripted peer with an actual SDK new-session response supplied by its caller."""
from pathlib import Path
import sys

from acp.schema import NewSessionResponse
from scripted import ScriptedPeer


class SessionResponsePeer(ScriptedPeer):
    async def new_session(self, cwd: str, **kwargs):
        await super().new_session(cwd, **kwargs)
        return NewSessionResponse.model_validate_json(Path(sys.argv[1]).read_text())


if __name__ == "__main__":
    SessionResponsePeer.main()
