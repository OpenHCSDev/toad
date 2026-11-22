#!/usr/bin/env bash
# Build the Qt libraries the APK takes from here instead of from the PySide6 wheel, into
# TOOLCHAIN/qt/: the wheel's Qt version plus the upstream commits listed in COMMITS, built as
# Qt's official Android package is (its NDK, its options). The build copies them over the
# wheel's (buildozer.spec.in's android.add_libs_arm64_v8a) and fails unless the APK holds them
# (apk_qt_libs.py). Needs what toolchain.sh needs (JDK 17, uv) and git, cmake. Rerunning
# skips what is there; the first run compiles Qt's Gui library (about 15 minutes on 8 jobs).
#
#   tools/android/qt_libs.sh TOOLCHAIN
#
# Why (2026-11-21, Pixel 8a, simpleperf on the GUI thread while Toad was in use): Qt 6.12.0
# shows a widget window on Android by copying the WHOLE window's picture (10 MB at 1080x2400)
# before uploading the part that changed: QImage::copy < QImage::detach <
# QPlatformBackingStore::rhiFlush held 21% of the thread and freeing the copies 8%, so a
# throbber frame cost 13-21 ms whatever its size. The same code on a desktop
# (QT_WIDGETS_RHI=1): a tiny frame costs 0.4 ms in a 1 MB window, 4.7 ms at 10 MB, 45 ms at
# 41 MB. Qt fixed it as QTBUG-151881 on 2026-11-01 ("copy only the dirty part for upload"),
# after 6.12.0 was released.
#
# This goes when the PySide6 wheel's Qt carries COMMITS: delete this file, its call in
# toolchain.sh, apk_qt_libs.py and its call in build.sh, and the spec's android.add_libs_arm64_v8a.
set -euo pipefail
if [ $# -ne 1 ]; then sed -n '2,9p' "$0"; exit 2; fi
T=$(realpath "$1")
# Upstream qtbase commits (branch 6.12) applied on the wheel's version, oldest first.
COMMITS="f9d9f89b50615d971c4d69b83792636a7cd91324"
LIBRARIES="Gui"
NDK_VERSION=27.2.12479018  # r27c: the wheel's libraries name it in their .note.android.ident
: "${JAVA_HOME:=/usr/lib/jvm/java-17-openjdk}"; export JAVA_HOME
WHEEL=$(ls "$T"/wheels/pyside6-*-android_aarch64.whl)
VERSION=$(basename "$WHEEL" | cut -d- -f2)
W=$(realpath -m "$T/qt-build"); mkdir -p "$W" "$T/qt"
STAMP="$T/qt/BUILT"
WANT="qt $VERSION + $COMMITS : $LIBRARIES"
if [ -f "$STAMP" ] && [ "$(head -1 "$STAMP")" = "$WANT" ] && (cd "$T/qt" && tail -n +2 BUILT | sha256sum -c --status); then
  echo "qt libraries: $WANT (already built)"; exit 0
fi
cd "$W"
[ -x venv/bin/aqt ] || { uv venv -q --python 3.12 venv && uv pip install -q --python venv/bin/python aqtinstall ninja; }
# The host's Qt of the same version: its moc, rcc and build scripts drive the cross build.
[ -x "host/$VERSION/gcc_64/libexec/moc" ] || venv/bin/aqt install-qt linux desktop "$VERSION" linux_gcc_64 --archives qtbase icu -O "$W/host" | tail -1
[ -f "$T/sdk/ndk/$NDK_VERSION/source.properties" ] || timeout 1800 "$T/sdk/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$T/sdk" "ndk;$NDK_VERSION" | tail -1
NDK="$T/sdk/ndk/$NDK_VERSION"
[ -d qtbase/.git ] || git clone -q --depth 1 --branch "v$VERSION" https://code.qt.io/qt/qtbase.git qtbase
for commit in $COMMITS; do
  if ! git -C qtbase log --format=%b "v$VERSION..HEAD" | grep -q "$commit"; then
    git -C qtbase cat-file -e "$commit" 2> /dev/null || git -C qtbase fetch -q --shallow-since=2026-10-01 origin "${VERSION%.*}"
    git -C qtbase -c user.name=toolchain -c user.email=toolchain@localhost cherry-pick -x "$commit" > /dev/null
  fi
done
# The options of Qt's own Android package (its config_qtbase.opt), minus what only its packaging
# needs. QT_ALLOW_DOWNLOAD skips the configure-time check of Gradle's cache: the Java parts are
# never built here.
[ -f build-android/build.ninja ] || PATH="$W/venv/bin:$PATH" timeout 900 cmake -S qtbase -B build-android -GNinja \
  -DCMAKE_MAKE_PROGRAM="$W/venv/bin/ninja" -DQT_HOST_PATH="$W/host/$VERSION/gcc_64" \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" -DANDROID_SDK_ROOT="$T/sdk" -DANDROID_NDK_ROOT="$NDK" \
  -DANDROID_ABI=arm64-v8a -DCMAKE_BUILD_TYPE=RelWithDebInfo -DQT_BUILD_EXAMPLES=OFF -DQT_BUILD_TESTS=OFF \
  "-DQT_QPA_PLATFORMS=android;offscreen" -DQT_ALLOW_DOWNLOAD=ON \
  -DCMAKE_C_COMPILER_FRONTEND_VARIANT=GNU -DCMAKE_CXX_COMPILER_FRONTEND_VARIANT=GNU > configure.log 2>&1 \
  || { tail -30 configure.log; exit 1; }
# shellcheck disable=SC2086
PATH="$W/venv/bin:$PATH" timeout 3000 venv/bin/ninja -C build-android -j "${QT_LIBS_JOBS:-8}" $LIBRARIES > build.log 2>&1 || { tail -30 build.log; exit 1; }
TOOLS="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
rm -f "$STAMP"
for library in $LIBRARIES; do
  name="libQt6${library}_arm64-v8a.so"
  # The library replaces the wheel's under the wheel's other libraries and the bindings, so it
  # must define exactly the symbols the wheel's does.
  mkdir -p wheel-lib && unzip -o -q "$WHEEL" "PySide6/Qt/lib/$name" -d wheel-lib
  if ! diff <("$TOOLS/llvm-nm" -D --defined-only --format=just-symbols "wheel-lib/PySide6/Qt/lib/$name" | sort) \
            <("$TOOLS/llvm-nm" -D --defined-only --format=just-symbols "build-android/lib/$name" | sort) > symbols.diff; then
    echo "$name defines other symbols than the wheel's ($(grep -c '^[<>]' symbols.diff) differ; $W/symbols.diff)"; exit 1
  fi
  "$TOOLS/llvm-strip" --strip-unneeded -o "$T/qt/$name" "build-android/lib/$name"
done
{ echo "$WANT"; (cd "$T/qt" && sha256sum -- *.so); } > "$STAMP"
echo "qt libraries: $WANT"; (cd "$T/qt" && ls -la -- *.so)
