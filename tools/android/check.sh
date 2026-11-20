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
# imports a static read cannot see. First, every emoji-default symbol must carry U+FE0E
# (glyph_check.py), or it draws as a coloured picture. Exits non-zero on any finding.
# Arguments are build.sh's; APP is filled here, so a gate passes a scratch folder.
#
# The shipped-app check and run are the slow part, and they answer for a tree, a runtime and a
# profile, not for a folder: the merge gate runs them on a PR's head and the build that follows
# the merge would run them again on the same tree. A pass is remembered under
# ~/.cache/toad/shipped-app-check and the same tree is not checked twice; APP is still
# assembled, since the build needs it. A checkout with uncommitted changes under src or tools
# is always checked.
set -euo pipefail
if [ $# -ne 4 ]; then sed -n '2,10p' "$0"; exit 2; fi
RUNTIME=$(realpath "$1"); TOOLCHAIN=$(realpath "$2"); APP=$(realpath -m "$3"); PROFILE=$(realpath "$4")
HERE=$(cd "$(dirname "$0")" && pwd)
CHECKOUT=$(cd "$HERE/../.." && pwd)
RT="$RUNTIME/bin/python"
SITE=$("$RT" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
mkdir -p "$APP"
PASSED=""
if [ -z "$(git -C "$CHECKOUT" status --porcelain -- src tools)" ]; then
  KEY=$( { git -C "$CHECKOUT" rev-parse 'HEAD^{tree}'; echo "$RUNTIME"; echo "$TOOLCHAIN"; sha256sum < "$PROFILE"; } | sha256sum | cut -c1-32)
  PASSED="${XDG_CACHE_HOME:-$HOME/.cache}/toad/shipped-app-check/$KEY"
fi
echo "== emoji-default symbols carry U+FE0E (text presentation)"
(cd "$CHECKOUT" && "$RT" tools/glyph_check.py | tail -1)
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
if [ -n "$PASSED" ] && [ -e "$PASSED" ]; then
  echo "== shipped app check and run: this tree already passed ($(cat "$PASSED")); not run again"
  exit 0
fi
echo "== shipped app check (no site-packages)"
timeout 180 "$RT" "$HERE/bundle_check.py" "$APP" "$SITE"
echo "== shipped app run (scratch bus, no site-packages)"
(cd "$HERE" && timeout 900 "$RT" "$HERE/shipped_run.py" "$RUNTIME" "$APP" "$SITE")
if [ -n "$PASSED" ]; then
  mkdir -p "$(dirname "$PASSED")"
  echo "$(git -C "$CHECKOUT" log -1 --format='%h') on $(date -Is)" > "$PASSED"
fi
