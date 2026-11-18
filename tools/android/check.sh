#!/usr/bin/env bash
# Check what the Toad Qt APK would ship from this checkout, as it stands, without building it:
#
#   tools/android/check.sh RUNTIME TOOLCHAIN APP PROFILE
#
# The steps tools/android/build.sh runs before buildozer: the import closure of the APK's
# start (closure.py), the app folder laid out from it (assemble.py, which must remove an older
# build's leftovers planted in it first), and the shipped-app check
# (bundle_check.py: the start imports without site-packages, and no function-local import
# reaches a package the APK does not ship beyond its baseline), then the shipped app RUN on a
# scratch bus through every view kind and bound key (shipped_run.py), which catches the
# imports a static read cannot see. Exits non-zero on any finding.
# Arguments are build.sh's; APP is filled here, so a gate passes a scratch folder.
set -euo pipefail
if [ $# -ne 4 ]; then sed -n '2,10p' "$0"; exit 2; fi
RUNTIME=$(realpath "$1"); TOOLCHAIN=$(realpath "$2"); APP=$(realpath -m "$3"); PROFILE=$(realpath "$4")
HERE=$(cd "$(dirname "$0")" && pwd)
CHECKOUT=$(cd "$HERE/../.." && pwd)
RT="$RUNTIME/bin/python"
SITE=$("$RT" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
mkdir -p "$APP"
echo "== closure ($(git -C "$CHECKOUT" log -1 --format='%h %s'))"
(cd "$CHECKOUT" && PYTHONPATH=src timeout 120 "$RT" "$HERE/closure.py" "$APP/closure.json")
echo "== assemble (into a folder holding an older build's leftovers)"
# Leftovers an older build leaves: a package and a module that left the closure, an earlier
# layout's folder, and a departed module's bytecode. assemble.py must remove each.
PLANTED=("$APP/left_closure_package/__init__.py" "$APP/left_closure_module.py"
         "$APP/deployment/recipes/old_recipe/__init__.py"
         "$APP/__pycache__/left_closure_module.cpython-314.opt-1.pyc")
for planted in "${PLANTED[@]}"; do mkdir -p "$(dirname "$planted")"; : > "$planted"; done
timeout 300 "$RT" "$HERE/assemble.py" "$APP/closure.json" "$APP" "$TOOLCHAIN" "$PROFILE"
for planted in "${PLANTED[@]}"; do
  if [ -e "$planted" ]; then echo "error: assemble.py left the stale $planted in the app folder"; exit 1; fi
done
echo "assemble removed every planted leftover"
echo "== shipped app check (no site-packages)"
timeout 180 "$RT" "$HERE/bundle_check.py" "$APP" "$SITE"
echo "== shipped app run (scratch bus, no site-packages)"
(cd "$HERE" && timeout 900 "$RT" "$HERE/shipped_run.py" "$RUNTIME" "$APP" "$SITE")
