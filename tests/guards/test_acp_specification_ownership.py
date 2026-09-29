"""SDK contract and deletion closure for the specification boundary."""
import ast
from pathlib import Path
from typing import get_args
from acp import schema
from toad.acp.status import StopReason, ToolCallStatus
from toad.agent_schema import AgentDefinition
from agent_comms.field_codec import FieldCodec

ROOT = Path(__file__).resolve().parents[2]


def test_external_vocabulary_has_one_behavior_family():
    for family, external in ((StopReason, schema.StopReason), (ToolCallStatus, schema.ToolCallStatus)):
        assert set(member.declared_name for member in family.members_with(family)) == set(get_args(external))
        for spelling in get_args(external):
            assert family.decode(spelling).declared_name == spelling


def test_sdk_consumers_do_not_read_raw_protocol_records():
    assert not (ROOT / 'src/toad/acp/protocol.py').exists()
    for relative in ('src/toad/acp/agent_session.py', 'src/toad/acp/session_updates.py', 'src/toad/acp/messages.py'):
        tree = ast.parse((ROOT / relative).read_text())
        assert not any(isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                       and isinstance(node.slice.value, str) for node in ast.walk(tree)), relative
    for path in (ROOT / 'src/toad/acp').glob('*.py'):
        assert '_agent_data' not in path.read_text(), path
    tree = ast.parse((ROOT / 'src/toad/acp/agent_session.py').read_text())
    assert not any(isinstance(node, ast.ClassDef) and node.name == 'Mode' for node in ast.walk(tree))
    source = (ROOT / 'src/toad/acp/sdk_boundary.py').read_text()
    assert 'cast(' not in source and 'return notification' in source


def test_agent_definition_retains_its_external_format_without_aliases():
    definition = AgentDefinition.decode({'identity': 'test', 'name': 'Test',
        'run_command': {'*': 'true'}, 'type': 'coding', 'actions': {}})
    record = FieldCodec.encode(definition)
    assert record['type'] == 'coding' and 'kind' not in record
    assert FieldCodec.decode(AgentDefinition, record) == definition
