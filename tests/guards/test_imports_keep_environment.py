"""Importing any Toad module leaves the importer's environment as it was.

The agent-comms installer imports every Toad module in the worker that later publishes the
new runtime (ClientImportsProbe), and that worker finds the home it publishes into through
HOME. On 2026-11-16 toad.qt.android set HOME at import, the install published into
site-packages/home and rolled back. A process that wants another environment, such as the
APK, enters it itself (toad.qt.android_app.enter). This fails naming each Toad line that
writes a variable while the modules import; a dependency's own writes (PySide6 sets
PYSIDE6_OPTION_PYTHON_ENUM) are its own and not counted.
"""

import os
import subprocess
import sys
from pathlib import Path

import toad

PROBE = r'''
import importlib
import os
import pkgutil
import sys
import toad

source = os.path.dirname(toad.__file__)
writes = []
set_variable, delete_variable = os._Environ.__setitem__, os._Environ.__delitem__

def written(name):
    frame = sys._getframe(2)
    caller = frame.f_code.co_filename
    if caller.startswith(source):
        writes.append(f"{caller[len(source) - 4:]}:{frame.f_lineno} writes {name}")

def setting(environment, name, value):
    written(name)
    set_variable(environment, name, value)

def deleting(environment, name):
    written(name)
    delete_variable(environment, name)

os._Environ.__setitem__, os._Environ.__delitem__ = setting, deleting
for module in pkgutil.walk_packages(toad.__path__, "toad."):
    importlib.import_module(module.name)
print("\n".join(dict.fromkeys(writes)))
'''


def test_importing_every_toad_module_leaves_the_environment_unchanged() -> None:
    source_root = str(Path(toad.__file__).parents[1])
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=300, check=False,
        env={**os.environ, "PYTHONPATH": source_root, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", "Toad code that writes the environment on import:\n" + result.stdout
