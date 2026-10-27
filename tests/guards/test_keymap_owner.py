"""Keys belong to the Action family (plans/KEYMAP-PLAN.md, wave K0).

Each measure counts one way a binding is written outside its owner. A ceiling is the count
at the head this guard landed on and only falls: a migration wave lowers it in the same
change, and nothing raises it. The second test is the registry's conflict check: an app key
that a binding closer to the focus also claims is a conflict unless the app action yields
(YieldingKey) or the claimant is a modal screen, which owns the keyboard while it is up.
"""
import ast
import importlib
import inspect
from pathlib import Path
from typing import ClassVar, Iterator

from textual.binding import Binding
from textual.dom import DOMNode
from textual.screen import ModalScreen

ROOT = Path(__file__).resolve().parents[2] / 'src/toad'
OWNER = ROOT / 'widget_actions.py'
PREFERENCES = ROOT / 'preferences.py'
# External contracts, not bindings: text routed to the prompt, keys passed to a child process.
CONTRACT_HANDLERS = {ROOT / 'widgets/conversation.py', ROOT / 'widgets/terminal.py'}


class KeymapMeasure:
    """One way of writing a key outside the Action family, and its ceiling."""
    members: ClassVar[list[type['KeymapMeasure']]] = []
    ceiling: ClassVar[int]
    exempt: ClassVar[frozenset[Path]] = frozenset({OWNER})

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        KeymapMeasure.members.append(cls)

    @classmethod
    def sites(cls) -> list[tuple[Path, int]]:
        return [(path, line) for path in sorted(ROOT.rglob('*.py')) if path not in cls.exempt
                for line in cls.lines(ast.parse(path.read_text()))]

    @classmethod
    def lines(cls, tree: ast.Module) -> Iterator[int]:
        raise NotImplementedError(cls)


class RawBindings(KeymapMeasure):
    """`BINDINGS =` written by hand on a class."""
    ceiling = 22

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.ClassDef(body=body):
                    for item in body:
                        match item:
                            case (ast.Assign(targets=[ast.Name(id='BINDINGS')])
                                  | ast.AnnAssign(target=ast.Name(id='BINDINGS'))):
                                yield item.lineno


class HandBindings(KeymapMeasure):
    """`Binding(key, "action_name")` written by hand: a key tied to an action by its name."""
    ceiling = 30

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.Call(func=ast.Name(id='Binding') | ast.Attribute(attr='Binding')):
                    yield node.lineno


class ActionMethods(KeymapMeasure):
    """`def action_*`: behaviour Textual finds by string name."""
    ceiling = 72

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if name.startswith('action_'):
                    yield node.lineno


class KeyHandlers(KeymapMeasure):
    """An `on_key` handler deciding by the pressed key: bindings no menu can show."""
    ceiling = 2
    exempt = frozenset({OWNER, *CONTRACT_HANDLERS})

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.FunctionDef(name='on_key' | '_on_key') | ast.AsyncFunctionDef(name='on_key' | '_on_key'):
                    if any(KeyLiterals.compares_key(compare) for compare in ast.walk(node)):
                        yield node.lineno


class VimFlagReads(KeymapMeasure):
    """The `vim_keys` flag read outside the preference store: a mode decided by a bool."""
    ceiling = 0
    exempt = frozenset({PREFERENCES})

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.Attribute(attr='vim_keys') | ast.FunctionDef(name='vim_keys'):
                    yield node.lineno


class MenuOrders(KeymapMeasure):
    """`menu_order`: a hand-numbered rank where declaration order already orders."""
    ceiling = 0
    exempt = frozenset()

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.Name(id='menu_order') | ast.Attribute(attr='menu_order'):
                    yield node.lineno


class KeyLiterals(KeymapMeasure):
    """A key spelled outside an action's default and the preference store: compared with
    an event's key, given as a `key_display`, or kept in a `*_KEYS` constant."""
    ceiling = 3
    exempt = frozenset({OWNER, PREFERENCES, *CONTRACT_HANDLERS})

    @staticmethod
    def compares_key(node: ast.AST) -> bool:
        match node:
            case ast.Compare(left=left, comparators=comparators):
                return any(isinstance(side, ast.Attribute) and side.attr in {'key', 'character'}
                           for side in (left, *comparators))
        return False

    @classmethod
    def lines(cls, tree):
        for node in ast.walk(tree):
            match node:
                case ast.Compare() if cls.compares_key(node):
                    yield from (constant.lineno for constant in ast.walk(node)
                                if isinstance(constant, ast.Constant) and isinstance(constant.value, str))
                case ast.keyword(arg='key_display', value=ast.Constant(value=str())):
                    yield node.value.lineno
                case ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=str())) if name.endswith('_KEYS'):
                    yield node.lineno


def test_keys_written_outside_the_action_family_only_fall():
    over = {measure.__name__: (len(sites), measure.ceiling, sites[:5])
            for measure in KeymapMeasure.members
            if len(sites := measure.sites()) > measure.ceiling}
    assert not over, over


def declared_nodes() -> Iterator[type[DOMNode]]:
    for path in sorted(ROOT.rglob('*.py')):
        module = importlib.import_module('.'.join(('toad', *path.relative_to(ROOT).with_suffix('').parts)))
        yield from (owner for owner in vars(module).values()
                    if inspect.isclass(owner) and issubclass(owner, DOMNode)
                    and owner.__module__ == module.__name__ and 'BINDINGS' in owner.__dict__)


def keys(binding: Binding) -> list[str]:
    return [key.strip() for key in binding.key.split(',')]


def test_no_app_key_is_claimed_twice_without_a_declaration():
    from toad.app import ToadApp
    from toad.widget_actions import ApplicationAction, YieldingKey
    app = {key: action for action in ApplicationAction.members_with(ApplicationAction)
           if not issubclass(action, YieldingKey) for binding in action.bindings() for key in keys(binding)}
    conflicts = [(key, app[key].__name__, f'{owner.__module__}.{owner.__qualname__}', str(binding.action))
                 for owner in declared_nodes() if owner is not ToadApp and not issubclass(owner, ModalScreen)
                 for binding in Binding.make_bindings(owner.__dict__['BINDINGS'])
                 for key in keys(binding)
                 if key in app and str(binding.action) != app[key].binding_name()]
    assert not conflicts, conflicts
