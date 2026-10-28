"""Retiring an ACP sender whose real peer closed still releases its sessions."""

import asyncio
from contextlib import suppress
import socket

import pytest
from acp import ClientSideConnection


async def test_failed_sender_does_not_prevent_session_retirement(workspace):
    agent = workspace.agents.detached_agent()
    agent.presentation.log_path.parent.mkdir(parents=True, exist_ok=True)
    process = agent.process
    process.sessions.add(agent.session)
    local, peer = socket.socketpair()
    reader, writer = await asyncio.open_connection(sock=local)
    # The outgoing SDK transport is real; no receive loop races the failed send.
    process.connection = ClientSideConnection(process, writer, reader, listening=False)
    peer.close()
    try:
        with pytest.raises((BrokenPipeError, ConnectionResetError)):
            await process.connection.ext_notification("retirement_probe", {})
        await process.retire()
        assert process.connection is None
        assert not process.sessions
        assert agent.session.task is None
        assert not agent.session.accepts_updates
        assert agent.session.retirement.done()
    finally:
        writer.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await writer.wait_closed()
