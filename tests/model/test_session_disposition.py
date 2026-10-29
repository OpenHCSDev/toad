"""A viewer's handshake is its own input state, never the thread's connection state."""
from dataclasses import dataclass

import pytest

from toad.acp.agent_session import ActiveSessionDisposition


@dataclass
class Handshake:
    ready: bool


@pytest.mark.parametrize("ready", [False, True])
def test_a_loading_session_shows_the_threads_own_state(ready):
    loading = ActiveSessionDisposition(Handshake(ready))
    assert loading.present("⌛ Working", lambda status: status.notice) == "⌛ Working"
