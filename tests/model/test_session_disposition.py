"""A viewer's handshake is its own input state, never the thread's connection state."""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from agent_comms.execution.owner_protocol import OtherCoreOwner

from toad.acp.agent_session import ActiveSessionDisposition, HistoryOnlySessionDisposition
from toad.agent_binding import AgentConnection
from toad.client.input_decision import NoLiveAgent


@dataclass
class Handshake:
    ready: bool


@pytest.mark.parametrize("ready", [False, True])
def test_a_loading_session_shows_the_threads_own_state(ready):
    loading = ActiveSessionDisposition(Handshake(ready))
    assert loading.present("⌛ Working", lambda status: status.notice) == "⌛ Working"


def test_a_connected_history_only_session_refuses_input_with_its_owner_reason():
    owner = OtherCoreOwner(thread="peer", core_commit="123456789abcdef")
    disposition = HistoryOnlySessionDisposition(Handshake(True), owner)
    connection = SimpleNamespace(
        ready=True,
        session_disposition=disposition,
        readiness_refusal=NoLiveAgent(disposition),
    )

    decision = AgentConnection.readiness_decision.__get__(connection)

    assert isinstance(decision, NoLiveAgent)
    assert decision.message == f"Thread disconnected: {owner.line()}"
