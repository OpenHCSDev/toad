"""Deleted T4 mechanisms cannot return to production."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'src/toad'


def test_t4_ownership_and_deletion():
    for relative in ('widgets/conversation.py', 'widgets/prompt.py', 'slash_command.py'):
        tree=ast.parse((ROOT/relative).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Attribute):
                assert node.attr not in {'turn','_managed_turn_id','_turn_lifecycle_source','_turn_lifecycle_sequence'}, (relative,node.lineno)
            if isinstance(node,ast.Name):
                assert node.id!='BlockProtocol', (relative,node.lineno)
                if relative == 'widgets/conversation.py':
                    assert node.id not in {'getattr', 'hasattr'}, (relative,node.lineno)
    assert 'BlockProtocol' not in (ROOT/'protocol.py').read_text()
    response=ast.parse((ROOT/'widgets/agent_response.py').read_text())
    for node in ast.walk(response):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            assert node.name not in {'block_cursor_up','block_cursor_down','block_cursor_clear','block_select','get_cursor_block'}
        if isinstance(node,ast.Name):
            assert node.id!='block_cursor_offset'
    agent=ast.parse((ROOT/'acp/agent.py').read_text())
    for node in ast.walk(agent):
        if isinstance(node,ast.Attribute):
            assert node.attr not in {'_process','_process_group_id','_agent_task','_task','_stopping','_log_file_path'}
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            assert node.name not in {'_run_agent','_process_group_alive'}
    question=ast.parse((ROOT/'widgets/question.py').read_text())
    for node in ast.walk(question):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'query_one','query_one_optional'}:
            assert not node.args or not isinstance(node.args[0],ast.Constant) or node.args[0].value!='#option-container'
    for relative in ('conversation_turn.py','block_navigation.py','question_presentation.py','acp/agent_process.py'):
        for node in ast.parse((ROOT/relative).read_text()).body:
            if isinstance(node,ast.ClassDef):
                assert not node.name.endswith('Mixin')
