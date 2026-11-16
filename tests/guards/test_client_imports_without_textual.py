"""Every module under toad.client imports with Textual blocked.

toad.client is the code every frontend shares; the Qt client on Android ships without
Textual. A Textual import reached from a shared module makes the Qt client unable to
import it, so it fails here, naming the chain of Toad files that reached Textual.
"""

import subprocess
import sys
from pathlib import Path

import toad.client

PROBE = r'''
import importlib
import pkgutil
import sys
import traceback

class BlockTextual:
    def find_spec(self, name, path=None, target=None):
        if name == "textual" or name.startswith("textual."):
            chain = [f"{frame.filename.split('/src/')[-1]}:{frame.lineno}"
                     for frame in traceback.extract_stack() if "/toad/" in frame.filename]
            raise ImportError(f"{name} reached via " + " -> ".join(chain))

sys.meta_path.insert(0, BlockTextual())
import toad.client
failures = []
for module in pkgutil.walk_packages(toad.client.__path__, "toad.client."):
    try:
        importlib.import_module(module.name)
    except ImportError as error:
        failures.append(f"{module.name}: {error}")
print("\n".join(failures))
'''


def test_every_client_module_imports_without_textual() -> None:
    source_root = str(Path(toad.client.__file__).parents[2])
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=120,
        env={"PYTHONPATH": source_root, "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", "toad.client modules that reach Textual:\n" + result.stdout
