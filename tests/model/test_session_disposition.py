"""A viewer's handshake is its own input state, never the thread's connection state."""
from dataclasses import dataclass

import pytest

from toad.acp.agent_session import ActiveSessionDisposition, ClosedSessionDisposition


@dataclass
class Handshake:
    ready: bool


@pytest.mark.parametrize("ready", [False, True])
def test_a_loading_session_shows_the_threads_own_state(ready):
    loading = ActiveSessionDisposition(Handshake(ready))
    assert loading.present("⌛ Working", lambda status: status.notice) == "⌛ Working"


def test_only_the_input_waits_for_the_handshake():
    assert ActiveSessionDisposition(Handshake(False)).input_notice("Working") == "Connecting to agent…"
    assert ActiveSessionDisposition(Handshake(True)).input_notice("Working") == "Working"


def test_a_closed_session_still_explains_its_input():
    assert ClosedSessionDisposition().input_notice("Working") == (
        "Thread disconnected: Session closed. Your draft is kept.")
