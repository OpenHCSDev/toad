"""Lay out the APK's app folder: the Python closure as source and compiled bytecode, the entry point, the files
toad.qt.android reads beside it, and buildozer.spec filled in from buildozer.spec.in.

    python tools/android/assemble.py CLOSURE.json APP TOOLCHAIN PROFILE

Run with the interpreter the closure came from: the CA bundle is its certifi's, the icon its
PySide6's and the theme its pywal cache, read through ui_theme's WalFile. TOOLCHAIN is the
folder toolchain.sh fills (sdk/, wheels/); PROFILE is the UI profile the phone holds first,
copied in and never committed. Packages built by python-for-android recipes and the PySide6
wheels are left to the build; every other package ships as source, with its bytecode.

The app folder is reused between builds, so this script owns its whole set of entries: the
closure's packages and modules and the entries app_folder.py declares. Everything else is a
leftover of an older build and is removed first (a package that left the closure kept
shipping as stale source: 2026-11-18, watchdog), and the folder is checked to hold exactly
that set once it is laid out.

The bytecode is compiled here because the phone would otherwise compile every module the
first time it starts after each install: an install unpacks the app folder afresh, so the
bytecode the last start wrote is gone, and compiling the client's modules adds about six
seconds at a phone's speed to that start. It is compiled as the phone runs Python
(at the optimization level the APK's activity sets, `recipe_built.python_optimize`), and never checked against its
source: an install unpacks source and bytecode together, so they cannot disagree, while a
timestamp check would refuse every file (unpacking gives each a new modification time) and
a hash check would read and hash every source at every start.
"""
import json
import os
import shutil
import sys
import zipfile
from configparser import ConfigParser
from pathlib import Path
from string import Template

import compileall
import py_compile

import certifi
import PySide6
from app_folder import excluded_files, excluded_folders, stale
from recipe_built import SPEC, import_names, python_optimize
from ui_theme.wal import WalFile

closure_file, app, toolchain, profile = (Path(argument).resolve() for argument in sys.argv[1:5])
HERE = Path(__file__).resolve().parent
app.mkdir(parents=True, exist_ok=True)

built_by_recipes = import_names()
closure = {name: Path(entry["root"]) for name, entry in json.loads(closure_file.read_text()).items()
           if name not in built_by_recipes}
closure_names = {root.name for root in closure.values()}
# Neither the closure's nor declared: a package that left the closure, or a recipe package's
# source copy, which would shadow the build's compiled one. The top-level modules' bytecode is
# compiled afresh below, so a module that left keeps none.
for leftover in [*stale(app, closure_names), app / "__pycache__"]:
    if leftover.is_dir():
        shutil.rmtree(leftover)
    elif leftover.exists():
        leftover.unlink()
    print(f"removed {leftover.name}")
# Hidden directories are build state (the native Pi agent under _native), not package code.
ignore = shutil.ignore_patterns("*.so", "*.pyd", "__pycache__", "*.pyc", "tests", "test", ".*")
shipped = []
for name, root in closure.items():
    target = app / root.name
    if target.exists():
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    if root.is_dir():
        shutil.copytree(root, target, ignore=ignore)
    else:
        shutil.copy2(root, target)
    print(f"{name:26} {sum(1 for _ in target.rglob('*.py')) if target.is_dir() else 1} files")
    shipped.append(target)

# The shipped packages only: the app folder also holds the build's own state (.buildozer).
compiled = {"quiet": 1, "optimize": python_optimize(),
            "invalidation_mode": py_compile.PycInvalidationMode.UNCHECKED_HASH}
for target in shipped:
    if target.is_dir():
        compileall.compile_dir(target, workers=1, **compiled)
    elif target.suffix == ".py":
        compileall.compile_file(target, **compiled)
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
    keepalive=HERE / "keepalive",
    jars=app / "jar" / "PySide6" / "jar",
    icon=Path(PySide6.__file__).parent / "scripts" / "deploy_lib" / "pyside_icon.jpg",
    exclude_dirs=excluded_folders(),
    exclude_files=excluded_files(),
))
spec = ConfigParser()
spec.read(app / "buildozer.spec")
# The keep-alive service's manifest, as the one-file library gradle merges (keepalive/),
# at the SDK levels the spec builds for.
with zipfile.ZipFile(app / "keepalive.aar", "w") as aar:
    aar.writestr("AndroidManifest.xml", Template((HERE / "keepalive" / "AndroidManifest.xml").read_text())
                 .substitute(minapi=spec["app"]["android.minapi"], api=spec["app"]["android.api"]))
    aar.writestr("classes.jar", b"PK\x05\x06" + bytes(18))  # an empty jar: the code is java/
    aar.writestr("R.txt", "")
left = stale(app, closure_names)
if left:
    sys.exit(f"error: the app folder holds entries neither the closure's nor declared (app_folder.py): {[path.name for path in left]}")
print(f"app folder {app}: the closure's {len(closure_names)} packages and modules, and the declared entries; buildozer.spec from {wheel.name}")
