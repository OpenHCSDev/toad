"""Current UI ownership, action dispatch and history publication contracts."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'src/toad'


def test_conversation_uses_declared_contracts():
    relative = 'widgets/conversation.py'
    for node in ast.walk(ast.parse((ROOT / relative).read_text())):
        if isinstance(node, ast.Name):
            assert node.id not in {'getattr', 'hasattr'}, (relative, node.lineno)


def test_nominal_block_interaction_caller_closure():
    tree=ast.parse((ROOT/'widgets/conversation.py').read_text())
    methods={'copy_block_to_clipboard','copy_block_to_prompt','action_select_block',
             'action_expand_block','action_collapse_block'}
    for method in ast.walk(tree):
        if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)) and method.name in methods:
            for node in ast.walk(method):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                    assert node.func.id not in {'isinstance','issubclass','getattr','hasattr'}, (method.name,node.lineno)


def test_channel_messages_are_drawn_by_the_line_history_alone():
    """The channel view has no paging, preparation or row widgets of its own."""
    from toad.widgets.transcript_history import LineHistory, TranscriptHistory
    from toad.widgets.wire_history import WireHistory

    # A channel is a line history, and not a saved transcript: it covers no live blocks.
    assert issubclass(WireHistory, LineHistory) and not issubclass(WireHistory, TranscriptHistory)
    # Paging, lookahead and trimming are the line history's, for both; the reader's position is the window's.
    for name in ('_load_page', 'extend_source'):
        assert name in vars(LineHistory), name
        assert name not in vars(WireHistory) and name not in vars(TranscriptHistory), name
    for name in ('covers_incoming', 'covers_input', 'coverage_events'):
        assert not hasattr(WireHistory, name), name


def test_a_bus_message_has_one_row_drawing_and_links_open_in_one_place():
    """The channel, saved thread history and live rows build a message's header from `MessageRow`."""
    declared: dict[str, list[str]] = {}
    for path in ROOT.rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                declared.setdefault(node.name, []).append(path.relative_to(ROOT).as_posix())
    # One class says how a link opens; no view or widget keeps actions of its own for it.
    assert declared['OpensLinks'] == ['widgets/linked_rows.py']
    from toad.widgets.message_divider import MessageDivider
    from toad.widgets.linked_rows import OpensLinks

    # The live rule draws the block saved history draws; it has no drawing of its own.
    assert 'render' not in vars(MessageDivider) and issubclass(MessageDivider, OpensLinks)

    # The message owns its menu and one class runs it: a view has no open actions or menu entries of its own.
    for name, home in (('action_link', 'widgets/linked_rows.py'), ('opens', 'project_link.py')):
        assert declared[name] == [home], (name, declared[name])
    assert declared['OpenSenderCommand'] == declared['OpenDestinationCommand'] == ['menus.py']


def test_serialized_history_tree_mutations_use_the_window_fence():
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
                     'widgets/wire_history.py'):
        visit(ast.parse((ROOT / relative).read_text()), relative)


def test_widget_action_availability_has_no_case_catalog():
    """Native action names enter one declaration boundary, never a widget switch."""
    for relative in ('widgets/conversation.py', 'widgets/question.py', 'screens/permissions.py'):
        tree = ast.parse((ROOT / relative).read_text())
        for method in ast.walk(tree):
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name == 'check_action':
                assert not any(isinstance(node, (ast.Compare, ast.Match))
                               for node in ast.walk(method)), (relative, method.lineno)


def test_history_layout_producers_do_not_wait_for_their_own_paint():
    """Native frame handling consumes the resources these transactions build."""
    for path in (*ROOT.rglob('*.py'), *(ROOT.parents[1] / 'tools').rglob('*.py')):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {'preserve_history', '_restore_bodies'}:
                assert not any(isinstance(call, ast.Call)
                               and isinstance(call.func, ast.Attribute)
                               and call.func.attr == 'call_after_refresh'
                               for call in ast.walk(node)), (path, node.lineno)
