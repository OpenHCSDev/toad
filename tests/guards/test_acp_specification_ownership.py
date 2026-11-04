"""SDK contract and deletion closure for the specification boundary."""
import inspect
from typing import get_args
from acp import schema
from toad.acp.status import StopReason, ToolCallStatus
from toad.agent_schema import AgentDefinition
from agent_comms.nominal.field_codec import FieldCodec

def test_external_vocabulary_has_one_behavior_family():
    for family, external in ((StopReason, schema.StopReason), (ToolCallStatus, schema.ToolCallStatus)):
        assert set(member.declared_name for member in family.members_with(family)) == set(get_args(external))
        for spelling in get_args(external):
            assert family.member_named(spelling).declared_name == spelling


def test_notification_boundary_retains_the_sdk_notification():
    # The SDK-validated notification itself travels on; the raw record rides only for rejection.
    from acp.schema import SessionNotification
    from toad.acp.sdk_boundary import AcceptedSessionUpdateValidation, ValidateSessionUpdateTask
    for owner in (ValidateSessionUpdateTask, AcceptedSessionUpdateValidation):
        assert inspect.get_annotations(owner, eval_str=True)['notification'] is SessionNotification, owner


def test_agent_definition_retains_its_external_format_without_aliases():
    definition = AgentDefinition.decode({'identity': 'test', 'name': 'Test',
        'run_command': {'*': 'true'}, 'type': 'coding', 'actions': {}})
    record = FieldCodec.encode(definition)
    assert record['type'] == 'coding' and 'kind' not in record
    assert FieldCodec.decode(AgentDefinition, record) == definition
