"""A real SDK peer with a foreign descendant, for process-group retirement."""
import asyncio
from pathlib import Path
import sys

from acp.schema import NewSessionResponse
from agent_comms.child_process import ProcessIdentity
from agent_comms.nominal.field_codec import FieldCodec
from base import Peer


class RetirementPeer(Peer):
    async def new_session(self, cwd: str, **kwargs: object) -> NewSessionResponse:
        response = await super().new_session(cwd, **kwargs)
        child = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("retirement_child.py")),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.record(descendant=FieldCodec.encode(ProcessIdentity.capture(child.pid)))
        return self.after_child(response)

    def after_child(self, response: NewSessionResponse) -> NewSessionResponse:
        return response


if __name__ == "__main__":
    RetirementPeer.main()
