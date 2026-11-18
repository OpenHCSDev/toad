"""Fail when an empty method shadows a real implementation of the same name in a class's MRO.

Three bugs on 2026-11-17 had this one shape: a base declared a method with only a docstring
(or `pass` / `...`), without `@abstractmethod`, and some class's MRO put that empty body ahead
of a concrete implementation further along — so the real behaviour silently never ran:
  - `HistoryWindow.tail_follow_changed` hid `JumpsToLatest`'s (back-to-bottom vanished),
  - `ThreadStatusOwner.thread_observed` hid `ThreadBindingDispatch`'s (Qt dropped every live update),
  - a stub `open_transfer` on the shared app hid the real one (TUI Export/Import did nothing).
Only SIBLING shadows count: an empty method on a base that is not a subclass of the class
holding the real implementation. A subclass emptying its own parent's method (a null object or
a state that ignores an event) is deliberate and is not reported.
An intended "no-op default" on a mixin must be spelled so it cannot hide anything: make it
`@abstractmethod`, give it a real body, or delete it.

KNOWN_SHADOWS is the debt when this check landed; it only shrinks.
Run with an interpreter that has PySide6 and Textual (the agent-comms runtime):
  QT_QPA_PLATFORM=offscreen PYTHONPATH=src <runtime>/bin/python tools/shadow_check.py
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import sys
import textwrap

KNOWN_SHADOWS: dict[str, str] = {}


def empty_body(function) -> bool:
    """Only a docstring and/or `pass` / `...`. A lambda is an expression, never a stub."""
    if function.__name__ == "<lambda>":
        return False
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    except (OSError, TypeError, SyntaxError):
        return False  # no parseable `def` source to judge (builtins, generated functions)
    definition = tree.body[0]
    if not isinstance(definition, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    statements = list(definition.body)
    if statements and isinstance(statements[0], ast.Expr) and isinstance(statements[0].value, ast.Constant) \
            and isinstance(statements[0].value.value, str):
        statements = statements[1:]
    return all(isinstance(statement, ast.Pass)
               or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                   and statement.value.value is Ellipsis)
               for statement in statements)


def plain_function(value):
    """The function behind a class attribute, or None for anything that isn't one."""
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if isinstance(value, property):
        value = value.fget
    return value if inspect.isfunction(value) else None


def classes() -> dict[str, type]:
    package = importlib.import_module("toad")
    found: dict[str, type] = {}
    for info in pkgutil.walk_packages(package.__path__, "toad."):
        module = importlib.import_module(info.name)  # an import failure is a failure
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__:
                found[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return found


def shadows() -> dict[str, str]:
    found: dict[str, str] = {}
    for path, cls in classes().items():
        toad_mro = [base for base in cls.__mro__ if base.__module__.startswith("toad")]
        for index, owner in enumerate(toad_mro):
            for name, value in vars(owner).items():
                function = plain_function(value)
                if function is None or getattr(function, "__isabstractmethod__", False) or not empty_body(function):
                    continue
                if any(name in vars(earlier) for earlier in toad_mro[:index]):
                    continue  # something ahead of the empty body already answers it
                for later in cls.__mro__[cls.__mro__.index(owner) + 1:]:
                    real = plain_function(vars(later).get(name))
                    if real is not None and not empty_body(real) and not getattr(real, "__isabstractmethod__", False):
                        # A subclass that empties its parent's method is a deliberate null/state
                        # override; an empty method on a SIBLING base that the MRO happens to put
                        # first is the silent-shadow bug.
                        if not issubclass(owner, later):
                            key = f"{owner.__module__}.{owner.__qualname__}.{name}"
                            found.setdefault(key, f"hides {later.__module__}.{later.__qualname__}.{name} in {path}")
                        break
    return found


def main() -> int:
    found = shadows()
    new = sorted(set(found) - set(KNOWN_SHADOWS))
    fixed = sorted(set(KNOWN_SHADOWS) - set(found))
    for key in new:
        print(f"NEW SHADOW  {key} {found[key]}")
    for key in fixed:
        print(f"FIXED       {key} no longer shadows anything: delete its KNOWN_SHADOWS line")
    print(f"empty methods shadowing real ones: {len(found)} (baseline {len(KNOWN_SHADOWS)})")
    return 1 if new or fixed else 0


if __name__ == "__main__":
    sys.exit(main())
