"""An acquired ACP binding and an unbound connection permit different work."""
import pytest
from acp.exceptions import RequestError
from agent_comms.nominal.field_codec import AcpSessionId
from toad.acp.agent_controller import SessionBinding


def test_acquired_binding_keeps_its_decoded_identity_and_output():
    binding = SessionBinding.from_sdk("first-session")
    assert binding.require_session_id() == AcpSessionId("first-session")
    assert binding.require_session_id() is binding.session_id
    assert binding.accepts_notification("first-session")
    assert not binding.accepts_notification("replacement-session")
    replacement = SessionBinding.from_sdk("replacement-session")
    assert replacement.output is not binding.output
    assert binding.accepts_notification("first-session")


def test_unbound_connection_cannot_supply_a_session_request_destination():
    binding = SessionBinding.from_sdk(None)
    assert not binding.accepts_notification("first-session")
    with pytest.raises(RequestError) as failure:
        binding.require_session_id()
    assert failure.value.code == -32602
