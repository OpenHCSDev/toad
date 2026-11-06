"""A scripted peer whose steps also arrive live, from a test process outside the ACP pipe.

It listens on localhost and writes its port to ``peer-relay.port`` in the project. Each line
it receives is one step (see ``steps``); it performs the step and answers with one line, the
step's outcome as JSON. Toad sees an ordinary ACP agent: every update and every permission
request reaches it over stdio, as a real agent's would.
"""

import asyncio
import json

from scripted import ScriptedPeer

PORT_FILE = "peer-relay.port"


class RelayPeer(ScriptedPeer):
    # The adapter that drives this relay addresses its session by this id.
    session_id = "project"

    async def new_session(self, cwd: str, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        server = await asyncio.start_server(self.relay, "127.0.0.1", 0)
        self.server = server
        (self.project / PORT_FILE).write_text(str(server.sockets[0].getsockname()[1]))
        return response

    async def relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for line in reader:
            outcome = await self.perform(self.session_id, json.loads(line))
            writer.write(json.dumps(outcome).encode() + b"\n")
            await writer.drain()
        writer.close()


if __name__ == "__main__":
    RelayPeer.main()
