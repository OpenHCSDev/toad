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
# One build at a time in APP: buildozer rewrites APP's dist while it packages it, so a second
# build started meanwhile removes files from under the first. A second build waits here.
mkdir -p "$APP"
exec 9>"$APP/.build.lock"
flock -n 9 || { echo "== waiting for the build already running in $APP"; flock 9; }
# The toolchain's Qt libraries are this checkout's (its commits and patches): built again when
# they are not, which takes minutes, and one line when they are.
"$HERE/qt_libs.sh" "$TOOLCHAIN"
"$HERE/check.sh" "$RUNTIME" "$TOOLCHAIN" "$APP" "$PROFILE"
# The APK's interpreter is the runtime's Python version: that runtime compiles the bytecode
# it ships and runs every check above (tools/android/recipes/python3 reads this).
export TOAD_ANDROID_PYTHON=$("$RUNTIME/bin/python" -c 'import platform; print(platform.python_version())')
# An empty XDG_CONFIG_HOME (as systemd/ACP sessions export) violates the XDG spec and
# makes Android Gradle Plugin resolve `.android/debug.keystore` relative to the dist dir
# instead of `~/.config/.android/debug.keystore`.
[ -n "${XDG_CONFIG_HOME:-}" ] || export XDG_CONFIG_HOME="${HOME}/.config"
echo "== build (Python $TOAD_ANDROID_PYTHON)"
cd "$APP"
VIRTUAL_ENV="$TOOLCHAIN/venv314" PATH="$TOOLCHAIN/venv314/bin:$PATH" \
  timeout 3000 buildozer android debug > "$APP/build.log" 2>&1 || { tail -30 "$APP/build.log"; exit 1; }
APK=$(ls -1t "$APP"/toadcomms-*-debug.apk | head -1)
"$RUNTIME/bin/python" "$HERE/apk_python.py" "$APK" "$TOAD_ANDROID_PYTHON"
"$RUNTIME/bin/python" "$HERE/apk_qt_libs.py" "$APK" "$TOOLCHAIN/qt"
echo "$APK"
