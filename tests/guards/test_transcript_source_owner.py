"""Deleted root transcript state; transcript cases inherit one application join."""
import ast
from pathlib import Path


def test_transcript_loaders_use_captured_actor():
    tree = ast.parse((Path(__file__).parents[2] / 'src/toad/transcript_publication.py').read_text())
    loaders = [node.args[1] for node in ast.walk(tree)
               if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == 'TranscriptHistory']
    assert loaders
    assert all(ast.unparse(loader) == 'self.agent.get_transcript_page' for loader in loaders)


def test_root_transcript_state_deleted():
    tree = ast.parse((Path(__file__).parents[2]/'src/toad/widgets/conversation.py').read_text())
    removed = {'_transcript_generation','_transcript_dirty','_needs_transcript_checkpoint',
               'displayed_transcript_cursor','_record_displayed_transcript','_compact_committed_history',
               'on_transcript_snapshot','on_transcript_changed'}
    assert not [node for node in ast.walk(tree)
                if isinstance(node,ast.Attribute) and node.attr in removed
                or isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in removed]


def test_source_operation_flags_deleted():
    root = Path(__file__).parents[2] / 'src/toad'
    for relative in ('widgets/transcript_history.py', 'transcript_source_preparation.py',
                     'transcript_state.py'):
        tree = ast.parse((root / relative).read_text())
        assert not [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                    and node.attr in {'_loading', '_advancing'}], relative


def test_native_page_coverage_is_joined():
    """A page that joins the history is reported inside its own change, never after its frame."""
    tree = ast.parse((Path(__file__).parents[2] / 'src/toad/widgets/transcript_history.py').read_text())
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    declarations = [node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == '_page_added']
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == '_page_added']
    assert declarations and calls
    assert all(isinstance(node, ast.AsyncFunctionDef) for node in declarations)
    assert all(isinstance(parents[node], ast.Await) for node in calls)


def test_presentation_retirement_has_one_owner():
    tree = ast.parse((Path(__file__).parents[2] / 'src/toad/transcript_publication.py').read_text())
    owners = [node.name for node in tree.body if isinstance(node, ast.ClassDef)
              for member in node.body
              if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
              and member.name == 'retire_presentations']
    assert owners == ['TranscriptPresentation']


def test_transcript_cases_inherit_the_application_join():
    tree = ast.parse((Path(__file__).parents[2] / 'src/toad/transcript_publication.py').read_text())
    cases = [node for node in tree.body if isinstance(node, ast.ClassDef)
             and any(isinstance(base, ast.Name) and base.id in
                     {'TranscriptPublication', 'CanonicalSourcePublication'} for base in node.bases)]
    assert cases
    assert not [member for case in cases for member in case.body
                if isinstance(member, ast.AsyncFunctionDef) and member.name == 'publish']
