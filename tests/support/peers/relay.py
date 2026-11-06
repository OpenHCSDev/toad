"""A scripted peer whose steps also arrive live, from a test process outside the ACP pipe.

It listens on localhost and publishes its port in the project (``relay_socket``). Each line
it receives is one step (see ``steps``); it performs the step and answers with one line, the
step's outcome or its failure. Toad sees an ordinary ACP agent: every update and every
permission request reaches it over stdio, as a real agent's would.
"""

import asyncio
import json

from relay_socket import RelaySocket, answer
from scripted import ScriptedPeer


class RelayPeer(ScriptedPeer):
    async def new_session(self, cwd: str, **kwargs):
        response = await super().new_session(cwd, **kwargs)
        self.server = await asyncio.start_server(self.relay, "127.0.0.1", 0)
        RelaySocket.port_file(self.project).write_text(str(self.server.sockets[0].getsockname()[1]))
        return response

    async def relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async for line in reader:
            writer.write(await answer(self.perform_line(line)))
            await writer.drain()
        writer.close()

    async def perform_line(self, line: bytes) -> object:
        return await self.perform(self.session_id, json.loads(line))


if __name__ == "__main__":
    RelayPeer.main()
