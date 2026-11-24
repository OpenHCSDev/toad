"""A Toad Qt class does not give a Qt signal or method another meaning.

A property named `destroyed` on a QWidget subclass replaces Qt's `destroyed` signal for every
caller, so `widget.destroyed.connect(...)` raised and the history window could not be built
(2026-11-21); an attribute named `window` makes `widget.window()` raise. Python accepts both
without a word. This names each class member in `toad.qt` that is a property where Qt has a
method, or anything but a signal where Qt has a signal. The members listed in `KNOWN` answer
a shared contract's name (`screen`, `window`) that Qt also uses; each is a trap for a caller
who means Qt's, and a new one is refused.
"""

import os
import subprocess
import sys
from pathlib import Path

import toad

KNOWN = frozenset({
    "toad.qt.conversation.QtConversation.window is a property over Qt's method",
})

PROBE = r'''
import importlib, inspect, pkgutil
import toad.qt
from PySide6.QtCore import QObject, Signal

for module in pkgutil.walk_packages(toad.qt.__path__, "toad.qt."):
    loaded = importlib.import_module(module.name)
    for cls in vars(loaded).values():
        if not (inspect.isclass(cls) and cls.__module__ == loaded.__name__ and issubclass(cls, QObject)):
            continue
        qt_bases = [base for base in cls.__mro__ if base.__module__.startswith("PySide6")]
        for name, member in vars(cls).items():
            if name.startswith("__"):
                continue
            theirs = next((vars(base)[name] for base in qt_bases if name in vars(base)), None)
            if isinstance(theirs, Signal) and not isinstance(member, Signal):
                print(f"{cls.__module__}.{cls.__qualname__}.{name} shadows Qt's signal")
            elif theirs is not None and callable(theirs) and isinstance(member, property):
                print(f"{cls.__module__}.{cls.__qualname__}.{name} is a property over Qt's method")
'''


def test_no_toad_qt_class_gives_a_qt_signal_or_method_another_meaning() -> None:
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=300, check=False,
        env={**os.environ, "PYTHONPATH": str(Path(toad.__file__).parents[1]), "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr
    found = {line for line in result.stdout.splitlines() if " shadows Qt's signal" in line or " over Qt's method" in line}
    assert found - KNOWN == set(), "new Qt members given another meaning:\n" + "\n".join(sorted(found - KNOWN))
    assert KNOWN - found == set(), "no longer shadowed: delete from KNOWN:\n" + "\n".join(sorted(KNOWN - found))
