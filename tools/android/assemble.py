"""Lay out the APK's app folder: the Python closure as source, the entry point, the files
toad.qt.android reads beside it, and buildozer.spec filled in from buildozer.spec.in.

    python tools/android/assemble.py CLOSURE.json APP TOOLCHAIN PROFILE

Run with the interpreter the closure came from: the CA bundle is its certifi's, the icon its
PySide6's and the theme its pywal cache, read through ui_theme's WalFile. TOOLCHAIN is the
folder toolchain.sh fills (sdk/, wheels/); PROFILE is the UI profile the phone holds first,
copied in and never committed. Packages built by python-for-android recipes and the PySide6
wheels are left to the build; every other package ships as source.
"""
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from string import Template

import certifi
import PySide6
from recipe_built import SPEC, import_names
from ui_theme.wal import WalFile

closure_file, app, toolchain, profile = (Path(argument).resolve() for argument in sys.argv[1:5])
HERE = Path(__file__).resolve().parent
app.mkdir(parents=True, exist_ok=True)

built_by_recipes = import_names()
# A source copy of a recipe package left in the app folder shadows the build's compiled one.
for name in built_by_recipes:
    for stale in (app / name, app / f"{name}.py"):
        if stale.is_dir():
            shutil.rmtree(stale)
        elif stale.exists():
            stale.unlink()
# Hidden directories are build state (the native Pi agent under _native), not package code.
ignore = shutil.ignore_patterns("*.so", "*.pyd", "__pycache__", "*.pyc", "tests", "test", ".*")
for name, entry in json.loads(closure_file.read_text()).items():
    if name in built_by_recipes:
        continue
    root = Path(entry["root"])
    target = app / root.name
    if target.exists():
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    if root.is_dir():
        shutil.copytree(root, target, ignore=ignore)
    else:
        shutil.copy2(root, target)
    print(f"{name:26} {sum(1 for _ in target.rglob('*.py')) if target.is_dir() else 1} files")

shutil.copy2(HERE / "main.py", app / "main.py")
held = app / "profile.json"
if profile != held:
    shutil.copyfile(profile, held)
held.chmod(0o600)
shutil.copyfile(certifi.where(), app / "cacert.pem")
wal = WalFile.directory(os.environ) / WalFile.NAME
if wal.is_file():
    (app / "wal").mkdir(exist_ok=True)
    shutil.copyfile(wal, app / "wal" / WalFile.NAME)

sdk = toolchain / "sdk"
wheel = next((toolchain / "wheels").glob(f"pyside6-{PySide6.__version__}-*android_aarch64.whl"))
with zipfile.ZipFile(wheel) as archive:
    for member in archive.namelist():
        if member.startswith("PySide6/jar/") and member.endswith(".jar"):
            archive.extract(member, app / "jar")
(app / "buildozer.spec").write_text(Template(SPEC.read_text()).substitute(
    app=app,
    sdk=sdk,
    ndk=max((sdk / "ndk").iterdir()),
    recipes=HERE / "recipes",
    jars=app / "jar" / "PySide6" / "jar",
    icon=Path(PySide6.__file__).parent / "scripts" / "deploy_lib" / "pyside_icon.jpg",
))
print(f"app folder {app}: main.py, profile.json, cacert.pem, buildozer.spec from {wheel.name}")
