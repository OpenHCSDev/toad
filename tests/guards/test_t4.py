"""Deleted T4 mechanisms cannot return to production."""
import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2] / 'src/toad'


def assert_deleted_cursor_contract(path, source):
    """Seal the removed UI family across definitions, imports and callbacks."""
    retired = {'Cursor', 'update_follow', 'watch_follow_widget', 'follow_widget', 'blink_timer'}
    for node in ast.walk(ast.parse(source)):
        match node:
            case (ast.Name(id=name) | ast.Attribute(attr=name)
                  | ast.ClassDef(name=name) | ast.FunctionDef(name=name)
                  | ast.AsyncFunctionDef(name=name) | ast.alias(name=name)):
                assert name not in retired, (path, node.lineno, name)
                if isinstance(node, (ast.Attribute, ast.FunctionDef, ast.AsyncFunctionDef)):
                    assert name != 'follow', (path, node.lineno, name)
            case ast.Call(func=ast.Attribute(attr=('query' | 'query_one' | 'query_one_optional')), args=[ast.Constant(value='Cursor'), *_]):
                raise AssertionError((path, node.lineno, 'Cursor selector'))
            case ast.Constant(value=name) if isinstance(name, str) and name in retired - {'Cursor'}:
                raise AssertionError((path, node.lineno, name))
            case ast.Call(func=ast.Name(id=('getattr' | 'hasattr' | 'setattr')), args=[_, ast.Constant(value='follow'), *_]):
                raise AssertionError((path, node.lineno, 'follow'))


def test_deleted_cursor_family_has_no_callers():
    for path in ROOT.rglob('*.py'):
        assert_deleted_cursor_contract(path, path.read_text())
    for path in ROOT.rglob('*.tcss'):
        assert re.search(r'(?<![\w-])Cursor(?![\w-])', path.read_text()) is None, path


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
    assert not (ROOT/'protocol.py').exists()
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


def test_nominal_block_interaction_caller_closure():
    retired = {'MenuProtocol','ExpandProtocol','get_block_content','get_cursor_block','CUSTOM_BLOCKS'}
    for path in ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Name):
                assert node.id not in retired, (path,node.lineno,node.id)
            if isinstance(node, ast.Attribute):
                assert node.attr not in retired, (path,node.lineno,node.attr)
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                assert node.name not in retired, (path,node.lineno,node.name)
    tree=ast.parse((ROOT/'widgets/conversation.py').read_text())
    methods={'action_copy_to_clipboard','action_copy_to_prompt','action_select_block',
             'action_expand_block','action_collapse_block'}
    for method in ast.walk(tree):
        if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and method.name in methods:
            for node in ast.walk(method):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                    assert node.func.id not in {'isinstance','issubclass','getattr','hasattr'}, (method.name,node.lineno)
    from toad.block_content import BlockContent
    from toad.conversation_markdown import ConversationMarkdown
    assert all(issubclass(block,BlockContent) for block in ConversationMarkdown.BLOCKS.values())


def test_markdown_tokens_use_native_rule_registry():
    """The admitted C0 boundary cannot acquire a token-type switch again."""
    path = ROOT / 'conversation_markdown.py'
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.Compare, ast.Match)):
            assert not any(isinstance(part, ast.Attribute) and part.attr == 'type'
                           for part in ast.walk(node)), (path, node.lineno)


def test_acp_process_retirement_single_owner():
    retired = {'ProcessControl', 'PosixProcessControl', 'WindowsProcessControl',
               '_maintenance_env', '_maintenance_cwd', '_maintenance_root',
               '_maintenance_implicit_root', 'stopping'}
    for relative in ('acp/agent.py', 'acp/agent_process.py', 'acp/maintenance_ingress.py',
                     'acp/agent_controller.py', 'acp/comms_updates.py'):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            if isinstance(node, ast.Name):
                assert node.id not in retired, (relative, node.lineno)
            if isinstance(node, ast.Attribute):
                assert node.attr not in retired, (relative, node.lineno)
                if relative in {'acp/agent_process.py', 'acp/maintenance_ingress.py'}:
                    assert node.attr not in {'killpg', 'terminate', 'kill', 'create_subprocess_shell'}, (relative, node.lineno)
    owner = ast.parse((ROOT / 'acp/agent_process.py').read_text())
    run = next(node for node in ast.walk(owner)
               if isinstance(node, ast.AsyncFunctionDef) and node.name == 'run')
    assert isinstance(run.body[0], ast.Try) and run.body[0].finalbody


def test_startup_failure_declaration_caller_closure():
    for relative in ('agent.py', 'acp/agent.py', 'acp/agent_process.py',
                     'acp/comms_updates.py', 'widgets/conversation.py'):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            if isinstance(node, ast.Name):
                assert node.id != 'AGENT_FAIL_HELP', (relative, node.lineno)
            if isinstance(node, ast.Call):
                assert not (isinstance(node.func, ast.Name) and node.func.id == 'AgentFail'), (relative, node.lineno)
                assert all(keyword.arg != 'help' for keyword in node.keywords), (relative, node.lineno)


def test_channel_history_has_one_publication_owner():
    tree = ast.parse((ROOT / 'widgets/comms_chat.py').read_text())
    retired = {'_history', '_has_older', '_has_newer', '_history_initialized',
               '_poll_cursor', '_edge_load_scheduled', '_edge_check_on_resume',
               '_refresh_lock', '_wire', '_revision', '_display_identity',
               '_ack_page', '_channel_ack_pages', '_historical_ack_pages',
               '_ack_inflight', 'irc_style', '_mount_page', '_insert_page',
               '_mark_visible_after_layout', '_mark_painted_page',
               '_mark_historical_paint', '_load_history_edge', '_history_request'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in retired, (node.lineno, node.attr)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in retired, (node.lineno, node.name)


def test_serialized_history_tree_mutations_use_native_publication():
    """A source lock cannot substitute for the window's native frame fence."""
    mutations = {'mount', 'remove_children', 'remove', 'extend', 'trim',
                 'update_fragments', 'insert_page', '_extend_and_trim'}

    def visit(node, path, source_locked=False, publication=False):
        if isinstance(node, ast.AsyncWith):
            contexts = {item.context_expr.func.attr
                        if isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Attribute)
                        else item.context_expr.attr
                        for item in node.items
                        if isinstance(item.context_expr, ast.Attribute)
                        or isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Attribute)}
            source_locked |= 'history_lock' in contexts
            publication |= 'preserve_history' in contexts
        if source_locked and isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call = node.value.func
            if isinstance(call, ast.Attribute) and call.attr in mutations:
                assert publication, (path, node.lineno, call.attr)
        for child in ast.iter_child_nodes(node):
            visit(child, path, source_locked, publication)

    for relative in ('widgets/transcript_history.py', 'transcript_filter.py',
                     'mounted_message_history.py', 'widgets/viewport_body.py'):
        visit(ast.parse((ROOT / relative).read_text()), relative)


def test_widget_action_availability_has_no_case_catalog():
    """Native action names enter one declaration boundary, never a widget switch."""
    for relative in ('widgets/conversation.py', 'widgets/question.py', 'screens/permissions.py'):
        tree = ast.parse((ROOT / relative).read_text())
        for method in ast.walk(tree):
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name == 'check_action':
                assert not any(isinstance(node, (ast.Compare, ast.Match))
                               for node in ast.walk(method)), (relative, method.lineno)
    for relative in ('widgets/conversation.py', 'widgets/question.py'):
        tree = ast.parse((ROOT / relative).read_text())
        retired = ({'action_focus_terminal', 'action_expand_block', 'action_collapse_block',
                    'action_mode_switcher', 'action_cancel'} if 'conversation' in relative else
                   {'action_selection_up', 'action_selection_down', 'action_select', 'action_select_kind'})
        assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in retired
                       for node in ast.walk(tree)), relative


def test_history_layout_producers_do_not_wait_for_their_own_paint():
    """Native frame admission consumes the resources these transactions build."""
    for path in (*ROOT.rglob('*.py'), *(ROOT.parents[1] / 'tools').rglob('*.py')):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = node.id if isinstance(node, ast.Name) else node.attr
                assert name != 'history_paint_ready', (path, node.lineno)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name != '_restore_body', (path, node.lineno)
                if node.name in {'preserve_history', '_restore_bodies'}:
                    assert not any(isinstance(call, ast.Call)
                                   and isinstance(call.func, ast.Attribute)
                                   and call.func.attr == 'call_after_refresh'
                                   for call in ast.walk(node)), (path, node.lineno)
