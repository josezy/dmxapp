#!/bin/sh
# Compile engine + golden tests by invoking the Kotlin compiler JAR (not kotlinc).
# Jansi native load hangs in this environment; keep it disabled.
set -e
JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/kotlinc-test"
GLIB="/Users/joseb/.gradle/wrapper/dists/gradle-8.14.3-bin/cv11ve7ro1n3o1j4so8xd9n66/gradle-8.14.3/lib"
STDLIB="/opt/homebrew/opt/kotlin/libexec/lib/kotlin-stdlib.jar"
COMPILER="/opt/homebrew/opt/kotlin/libexec/lib/kotlin-compiler.jar"
JSON="$OUT/json-20240303.jar"
mkdir -p "$OUT/classes"
if [ ! -f "$JSON" ]; then
  echo "missing $JSON" >&2
  exit 1
fi
CP="$JSON:$GLIB/junit-4.13.2.jar:$GLIB/hamcrest-core-1.3.jar"
"$JAVA_HOME/bin/java" -Xmx1g \
  -Dkotlin.compiler.execution.strategy=in-process \
  -Djava.awt.headless=true \
  -Dorg.jansi.library.disabled=true \
  -Dkotlin.colors.enabled=false \
  -cp "$COMPILER" org.jetbrains.kotlin.cli.jvm.K2JVMCompiler \
  -cp "$CP" \
  -d "$OUT/classes" \
  -jvm-target 17 \
  "$ROOT/app/src/main/java/org/deovolente/beam/engine/Head.kt" \
  "$ROOT/app/src/main/java/org/deovolente/beam/engine/Seq.kt" \
  "$ROOT/app/src/main/java/org/deovolente/beam/engine/RandomHead.kt" \
  "$ROOT/app/src/main/java/org/deovolente/beam/engine/FramePump.kt" \
  "$ROOT/app/src/main/java/org/deovolente/beam/engine/BeamEngines.kt" \
  "$ROOT/app/src/main/java/org/deovolente/beam/ShowPad.kt" \
  "$ROOT/app/src/test/java/org/deovolente/beam/engine/GoldenFrameTest.kt"
export BEAM_SEQ_DIR="$ROOT/../beam-halo-duo/sequences"
export BEAM_GOLDEN_DIR="$ROOT/app/src/test/resources/goldens"
"$JAVA_HOME/bin/java" -cp "$OUT/classes:$CP:$STDLIB" org.junit.runner.JUnitCore org.deovolente.beam.engine.GoldenFrameTest
