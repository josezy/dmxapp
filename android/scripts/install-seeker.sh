#!/bin/bash
# Build the Beam Halo APK in Linux Docker (macOS aapt2 hangs under Gatekeeper)
# and adb-install it on the connected Seeker. No Android Studio.
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
ADB="$ANDROID_HOME/platform-tools/adb"
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
DMX="$(CDPATH= cd -- "$ROOT/.." && pwd)"
APK="$ROOT/app/build/outputs/apk/debug/app-debug.apk"
GRADLE_DIST="${GRADLE_DIST:-$HOME/.gradle/wrapper/dists/gradle-8.14.3-bin/cv11ve7ro1n3o1j4so8xd9n66/gradle-8.14.3}"
IMAGE="${ANDROID_BUILD_IMAGE:-reactnativecommunity/react-native-android:latest}"

export ANDROID_HOME ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/platform-tools:$PATH"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found; needed because macOS aapt2 is blocked by Gatekeeper" >&2
  exit 1
fi
if [ ! -x "$GRADLE_DIST/bin/gradle" ]; then
  echo "Gradle 8.14.3 missing at $GRADLE_DIST" >&2
  exit 1
fi
if [ ! -f "$ROOT/local.docker.properties" ]; then
  echo "sdk.dir=/opt/android" > "$ROOT/local.docker.properties"
fi

echo "Devices:"
perl -e 'alarm 8; exec @ARGV' "$ADB" devices -l || echo "(adb devices timed out; continuing)"

echo "Assembling APK in Docker ($IMAGE)…"
docker run --rm --platform linux/amd64 \
  -v "$DMX":/dmx \
  -v "$ROOT/local.docker.properties":/dmx/android/local.properties:ro \
  -v "$GRADLE_DIST":/opt/gradle-8.14.3:ro \
  -v deovolente-android-gradle:/root/.gradle \
  -v deovolente-android-sdkmanager:/root/.android \
  -w /dmx/android \
  "$IMAGE" \
  bash -lc '
    set -euo pipefail
    export ANDROID_HOME=/opt/android ANDROID_SDK_ROOT=/opt/android
    export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:/opt/gradle-8.14.3/bin:$PATH"
    export GRADLE_OPTS="-Dorg.jansi.library.disabled=true -Dkotlin.colors.enabled=false"
    if [ ! -f /opt/android/platforms/android-35/android.jar ]; then
      echo "Installing platforms;android-35…"
      set +o pipefail
      yes | sdkmanager --sdk_root=/opt/android "platforms;android-35"
      set -o pipefail
    fi
    gradle assembleDebug --no-daemon
  '

if [ ! -f "$APK" ]; then
  echo "APK not produced: $APK" >&2
  exit 1
fi

echo "Installing $APK"
perl -e 'alarm 30; exec @ARGV' "$ADB" install -r "$APK"
echo "Launching org.deovolente.beam"
perl -e 'alarm 15; exec @ARGV' "$ADB" shell am start -n org.deovolente.beam/.MainActivity
echo "OK"
