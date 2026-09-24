package org.deovolente.beam.engine

import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

fun interface FrameMaker {
    fun frame(t: Double, now: Double): IntArray
}

data class EngineRun(val fps: Double, val make: FrameMaker)

data class PumpStats(
    val frames: Int,
    val usbFail: Int,
    val stopped: Boolean,
    val usbDead: Boolean,
    val skipped: Int,
)

private const val TWO_PI = 2.0 * PI

fun nowPerf(): Double = System.nanoTime() / 1_000_000_000.0

fun waitUntilBusy(deadline: Double, stop: AtomicBoolean): Boolean {
    while (true) {
        if (stop.get()) return true
        val remain = deadline - nowPerf()
        if (remain <= 0.0) return false
        val slice = if (remain < 0.01) remain else 0.01
        val ms = (slice * 1000.0).toLong()
        val nanos = ((slice * 1_000_000_000.0).toLong() - ms * 1_000_000L).coerceAtLeast(0L)
        try {
            Thread.sleep(ms.coerceAtLeast(0L), nanos.toInt().coerceIn(0, 999_999))
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            return true
        }
    }
}

fun syncFrame(
    t0: Double,
    nIn: Int,
    step: Double,
    stop: AtomicBoolean,
    onSkip: (Int) -> Unit,
): Pair<Int, Boolean> {
    var n = nIn
    val now = nowPerf()
    var target = t0 + n * step
    if (now - target > step) {
        val jumped = ((now - t0) / step).toInt()
        onSkip((jumped - n).coerceAtLeast(0))
        n = jumped
        target = t0 + n * step
    }
    if (waitUntilBusy(target, stop)) return n to true
    return n to false
}

fun pump(
    fps: Double,
    stop: AtomicBoolean,
    sendOnce: (IntArray) -> Boolean,
    isDead: () -> Boolean,
    make: FrameMaker,
    onSkip: (Int) -> Unit = {},
): PumpStats {
    val step = 1.0 / maxOf(1.0, fps)
    val t0 = nowPerf()
    var n = 0
    var fails = 0
    var skipped = 0
    while (!stop.get()) {
        val synced = syncFrame(t0, n, step, stop) { skipped += it }
        n = synced.first
        if (synced.second) break
        val now = nowPerf()
        val frame = make.frame(now - t0, now)
        if (!sendOnce(frame)) fails++
        if (isDead()) {
            return PumpStats(n, fails, stop.get(), true, skipped)
        }
        n++
    }
    return PumpStats(n, fails, stop.get(), false, skipped)
}

fun sweepPose(seq: Seq, t: Double): DoubleArray {
    val panC = seq.d("pan_center", 128.0)
    val tiltC = seq.d("tilt_center", 128.0)
    val panAmp = seq.d("pan_amp", 90.0)
    val tiltAmp = seq.d("tilt_amp", 40.0)
    val panHz = seq.d("pan_hz")
    val tiltHz = seq.d("tilt_hz")
    val sPan = sin(TWO_PI * panHz * t)
    val sTilt = sin(TWO_PI * tiltHz * t)
    val panA = panC + panAmp * sPan
    val tiltA = tiltC + tiltAmp * sTilt
    return if (seq.bool("mirror", true)) {
        doubleArrayOf(panA, tiltA, panC - panAmp * sPan, tiltC - tiltAmp * sTilt)
    } else {
        doubleArrayOf(panA, tiltA, panA, tiltA)
    }
}

fun haloHand(t: Double, hz: Double, hand: IntArray): IntArray {
    val phase = pythonMod(t * hz * 6.0, 6.0)
    val i = phase.toInt()
    val frac = phase - i
    val segs = Array(6) { intArrayOf(0, 0, 0) }
    val j = (i + 1) % 6
    segs[i] = IntArray(3) { c -> clamp(hand[c] * (1.0 - frac)) }
    segs[j] = IntArray(3) { c -> clamp(hand[c] * frac) }
    val out = IntArray(18)
    var p = 0
    for (rgb in segs) {
        out[p++] = rgb[0]
        out[p++] = rgb[1]
        out[p++] = rgb[2]
    }
    return out
}
