package org.deovolente.beam.engine

import kotlin.math.floor

/** Python 3 `round` (ties to even), then clamp 0–255 like `beam_halo_duo.clamp`. */
fun pythonRound(n: Double): Int {
    if (n.isNaN()) return 0
    val fl = floor(n)
    val frac = n - fl
    val lo = fl.toInt()
    return when {
        frac > 0.5 -> lo + 1
        frac < 0.5 -> lo
        else -> if (lo % 2 == 0) lo else lo + 1
    }
}

fun clamp(n: Double): Int = pythonRound(n).coerceIn(0, 255)

fun clamp(n: Int): Int = n.coerceIn(0, 255)

fun lerp(a: Double, b: Double, t: Double): Double = a + (b - a) * t

fun lerpVec(a: IntArray, b: IntArray, t: Double): IntArray {
    val u = t.coerceIn(0.0, 1.0)
    return IntArray(a.size) { i -> clamp(a[i] + (b[i] - a[i]) * u) }
}

/** Python `a % m` for floats (result in [0, m)). */
fun pythonMod(a: Double, m: Double): Double {
    val r = a % m
    return if (r < 0) r + m else r
}

fun headFrame(
    pan: Double,
    tilt: Double,
    speed: Int,
    dimmer: Int,
    strobe: Int,
    beam: IntArray,
    haloRgb: IntArray? = null,
    haloBytes: IntArray? = null,
): IntArray {
    val r = clamp(beam[0])
    val g = clamp(beam[1])
    val b = clamp(beam[2])
    val w = clamp(beam[3])
    val halo: IntArray =
        if (haloBytes != null) {
            IntArray(haloBytes.size) { clamp(haloBytes[it]) }
        } else {
            val hr = clamp(haloRgb!![0])
            val hg = clamp(haloRgb[1])
            val hb = clamp(haloRgb[2])
            IntArray(18) { i ->
                when (i % 3) {
                    0 -> hr
                    1 -> hg
                    else -> hb
                }
            }
        }
    require(halo.size == 18) { "halo must be 18 bytes" }
    val out = IntArray(30)
    out[0] = clamp(pan)
    out[1] = 0
    out[2] = clamp(tilt)
    out[3] = 0
    out[4] = clamp(speed)
    out[5] = clamp(dimmer)
    out[6] = clamp(strobe)
    out[7] = r
    out[8] = g
    out[9] = b
    out[10] = w
    halo.copyInto(out, 11)
    out[29] = 0
    return out
}

fun blackoutFrame(): IntArray {
    val out = IntArray(30)
    out[0] = 128
    out[2] = 128
    out[4] = 180
    return out
}

fun pack(a: IntArray, b: IntArray): IntArray = a + b

fun blackoutUniverse(): IntArray = pack(blackoutFrame(), blackoutFrame())

fun toUsbBytes(values: IntArray): ByteArray =
    ByteArray(values.size) { i -> values[i].toByte() }
