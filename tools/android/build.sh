#!/usr/bin/env bash
# Build the Toad Qt APK from this checkout, as it stands:
#
#   tools/android/build.sh RUNTIME TOOLCHAIN APP PROFILE
#
# RUNTIME    an installed agent-comms runtime (its bin/python and site-packages are what the
#            APK bundles), e.g. ~/.local/share/agent-comms/runtimes/<current>
# TOOLCHAIN  the folder tools/android/toolchain.sh fills: sdk/, wheels/, venv314/ (buildozer)
# APP        the app folder buildozer builds; reused between builds for its .buildozer cache
# PROFILE    the UI profile the phone holds first; copied into APP, never into git
#
# Prints the APK's path. Nothing here checks out, detaches or resets any checkout.
set -euo pipefail
if [ $# -ne 4 ]; then sed -n '2,12p' "$0"; exit 2; fi
RUNTIME=$(realpath "$1"); TOOLCHAIN=$(realpath "$2"); APP=$(realpath -m "$3"); PROFILE=$(realpath "$4")
HERE=$(cd "$(dirname "$0")" && pwd)
"$HERE/check.sh" "$RUNTIME" "$TOOLCHAIN" "$APP" "$PROFILE"
echo "== build"
cd "$APP"
VIRTUAL_ENV="$TOOLCHAIN/venv314" PATH="$TOOLCHAIN/venv314/bin:$PATH" \
  timeout 3000 buildozer android debug > "$APP/build.log" 2>&1 || { tail -30 "$APP/build.log"; exit 1; }
ls -1 "$APP"/toadcomms-*-debug.apk
