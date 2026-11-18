"""The APK's package closure: every non-stdlib top-level module the APK's start loads.

Run with the interpreter whose packages the APK bundles, from a Toad checkout:
    PYTHONPATH=src python tools/android/closure.py OUT.json
Enters the APK's environment, imports toad.qt.android and loads its client as the APK's start
does (`load_client`, after the first frame), and writes
{top-level name: {"root": path}} for assemble.py.
"""
import json
import sys
import sysconfig
from pathlib import Path

stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
from toad.qt.android_app import enter

enter()
before = set(sys.modules)
import toad.qt.android  # noqa: E402 - the import is the measurement

# The client loads after the first frame, through the call the APK's start makes.
toad.qt.android.load_client()

closure = {}
# Modules with no file of their own on disk: shiboken makes __feature__ at runtime, and
# __mp_main__ is this script under multiprocessing's alias. Their packages ship them.
made_at_runtime = []
for name, module in sorted(sys.modules.items()):
    top = name.split(".")[0]
    if top in closure or top in sys.builtin_module_names or name in before and top != "toad":
        continue
    if module is sys.modules["__main__"]:
        made_at_runtime.append(top)
        continue
    origin = getattr(module, "__file__", None)
    if origin is None:
        continue
    path = Path(origin).resolve()
    if path.is_relative_to(stdlib) and "site-packages" not in path.parts:
        continue
    root_module = sys.modules.get(top)
    root_file = getattr(root_module, "__file__", None)
    if root_file is None:
        continue
    root = Path(root_file).resolve()
    if not root.exists():
        made_at_runtime.append(top)
        continue
    closure[top] = {"root": str(root.parent if root.name == "__init__.py" else root)}

Path(sys.argv[1]).write_text(json.dumps(closure, indent=1))
print(len(closure), "packages:", " ".join(closure))
print("made at runtime, not shipped:", " ".join(sorted(set(made_at_runtime))))
