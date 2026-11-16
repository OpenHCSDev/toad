#!/usr/bin/env bash
# Fill TOOLCHAIN with what build.sh needs: the Android SDK (cmdline tools, platform 35, build
# tools, NDK r28c) under sdk/, the PySide6 and shiboken6 Android wheels under wheels/, and
# buildozer in venv314/. Needs JDK 17 (JAVA_HOME) and uv. Rerunning skips what is there.
#
#   tools/android/toolchain.sh TOOLCHAIN
set -euo pipefail
if [ $# -ne 1 ]; then sed -n '2,6p' "$0"; exit 2; fi
T=$(realpath -m "$1")
: "${JAVA_HOME:=/usr/lib/jvm/java-17-openjdk}"
export JAVA_HOME
"$JAVA_HOME/bin/java" -version 2>&1 | grep -q '"17' || { echo "JDK 17 is needed at JAVA_HOME ($JAVA_HOME)"; exit 1; }
mkdir -p "$T/wheels" "$T/sdk"
cd "$T"
for w in pyside6/pyside6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl shiboken6/shiboken6-6.12.0-6.12.0-cp310-abi3-android_aarch64.whl; do
  [ -f "wheels/${w#*/}" ] || timeout 600 curl -sSL -o "wheels/${w#*/}" "https://download.qt.io/official_releases/QtForPython/$w"
done
if [ ! -x sdk/cmdline-tools/latest/bin/sdkmanager ]; then
  timeout 600 curl -sSL -o cmdline-tools.zip https://dl.google.com/android/repository/commandlinetools-linux-13114758_latest.zip
  rm -rf sdk/cmdline-tools && mkdir -p sdk/cmdline-tools
  unzip -q cmdline-tools.zip -d sdk/cmdline-tools && mv sdk/cmdline-tools/cmdline-tools sdk/cmdline-tools/latest
  rm cmdline-tools.zip
fi
SM=sdk/cmdline-tools/latest/bin/sdkmanager
yes | timeout 300 "$SM" --sdk_root="$T/sdk" --licenses > /dev/null || true
timeout 1800 "$SM" --sdk_root="$T/sdk" "platform-tools" "platforms;android-35" "build-tools;35.0.0" "ndk;28.2.13676358" | tail -3
[ -x venv314/bin/buildozer ] || { uv venv -q --python 3.14 venv314 && uv pip install -q --python venv314/bin/python buildozer==1.6.0 cython==0.29.33 setuptools; }
echo "toolchain ready: $T"
