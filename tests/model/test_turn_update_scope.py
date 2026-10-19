from types import SimpleNamespace

from agent_comms.acp_extension import McpClientAcknowledgementUpdate, TurnChangedUpdate
from agent_comms.pi_payloads import McpLiveAcknowledgement
from agent_comms.turn_lease import ActiveTurn, TurnState
from toad.conversation_turn import ConversationTurn, ManagedTurn, ManagedTurnBinding, NoTurn


def acknowledgement(turn_id):
    return McpClientAcknowledgementUpdate(
        turn_id, McpLiveAcknowledgement(1, "pi-mcp-client", "a" * 32, "running", turn_id, ())
    )


def test_no_turn_accepts_session_facts_but_not_another_turn():
    for owner in (NoTurn(), ManagedTurn()):
        assert owner.accepts_update(TurnChangedUpdate(TurnState()))
        assert not owner.accepts_update(acknowledgement("finished-turn"))


def test_running_turn_uses_the_update_owner_to_match_identity():
    owner = ManagedTurn(TurnState(ActiveTurn("live-turn", 123)))
    assert owner.accepts_update(TurnChangedUpdate(TurnState()))
    assert owner.accepts_update(acknowledgement("live-turn"))
    assert not owner.accepts_update(acknowledgement("another-turn"))


def test_published_turn_change_notifies_the_already_updated_binding():
    binding = ManagedTurnBinding(object())
    changed = []
    turns = ConversationTurn(changed.append, lambda: binding)
    assert binding.receive(TurnState(ActiveTurn("live-turn", 123)))
    assert turns.changed(SimpleNamespace(event=SimpleNamespace(sequence=binding.sequence)))
    assert changed == [binding.owner]
