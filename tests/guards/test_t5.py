"""T5 retired mechanisms cannot return to production callers."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'src' / 'toad'


def test_t5_deletion_closure():
    history = ast.parse((ROOT / 'widgets/transcript_history.py').read_text())
    retired = {'_committed', '_publication_current', '_filter_overlay', '_filter_scanning', '_filter_force_pending', '_filtered_source'}
    for node in ast.walk(history):
        if isinstance(node, ast.Attribute):
            assert node.attr not in retired, (node.lineno, node.attr)
    for declaration in history.body:
        if isinstance(declaration, ast.ClassDef) and declaration.name == 'TranscriptHistory':
            for node in ast.walk(declaration):
                assert not isinstance(node, ast.Attribute) or node.attr not in {'_closing', '_pruning'}, node.lineno
    for relative in ('navigation_target.py', 'widgets/comms_sidebar.py'):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert not (node.value.id in {'row', 'choice'} and node.attr == 'kind'), (relative, node.lineno)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert node.target.id != 'kind', (relative, node.lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (ast.unparse(node.func.value) == 'NavigationTarget' and node.func.attr == 'decode'), node.lineno
    for relative in ('screens/main.py', 'screens/comms.py'):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {'query_one', 'query_one_optional'}:
                assert not node.args or not isinstance(node.args[0], ast.Constant) or node.args[0].value not in {'#channels-sidebar', '#thread-sidebar'}, (relative, node.lineno)
    chat = (ROOT / 'widgets/comms_chat.py').read_text()
    assert 'isinstance(error, HumanInitialUnknownError)' not in chat
    assert 'isinstance(error, RelationViolationError)' not in chat
    assert '"UNKNOWN outcome" in str(error)' not in chat
    fragment = next(node for node in history.body if isinstance(node, ast.ClassDef) and node.name == 'TranscriptFragmentView')
    for node in ast.walk(fragment):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != 'type', node.lineno

    conversation = ast.parse((ROOT / 'widgets/conversation.py').read_text())
    consumer = next(node for node in conversation.body if isinstance(node, ast.ClassDef) and node.name == 'ConversationCommsConsumer')
    for handler in consumer.body:
        if isinstance(handler, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == 'handles' for decorator in handler.decorator_list):
            assert isinstance(handler, ast.AsyncFunctionDef), handler.name


def test_single_thread_navigation_deletes_placeholder_sessions():
    retired = {'PendingThreadTab', 'PendingThreadScreen', 'PendingTabShells',
               '_pending_thread_modes', '_pending_thread_index', 'pending_tab_shells',
               '_open_pending_thread_tab', 'PREPARED_TAB_SHELLS'}
    for path in ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                assert name not in retired, (path, node.lineno)
    assert not (ROOT / 'screens/pending_thread.py').exists()
