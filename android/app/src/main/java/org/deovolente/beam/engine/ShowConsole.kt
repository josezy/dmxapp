package org.deovolente.beam.engine

import kotlin.math.PI
import kotlin.math.floor
import kotlin.math.sin
import kotlin.random.Random
import org.json.JSONArray
import org.json.JSONObject

const val LPC_CH = 7
const val BEAM_CH = 30
private const val UNIVERSE = 512
private const val MAX_EACH = 8
private const val CH6_LINEAR = 25
private const val COLOR_HOLD = 1.2

class RigError(message: String) : IllegalArgumentException(message)

data class Fixture(
    val type: String,
    val index: Int,
    val address: Int,
    val start: Int,
    val channels: Int,
    val label: String,
)

data class Rig(
    val order: String,
    val nLpc: Int,
    val nBeam: Int,
    val fixtures: List<Fixture>,
    val span: Int,
)

data class Slot(
    val name: String,
    val r: Int,
    val g: Int,
    val b: Int,
    val w: Int,
    val halo: IntArray,
    val beam: IntArray,
) {
    fun parRgb(): IntArray {
        if (r != 0 || g != 0 || b != 0) return intArrayOf(r, g, b)
        if (halo.any { it != 0 }) return intArrayOf(halo[0], halo[1], halo[2])
        if (w != 0) return intArrayOf(255, 255, 255)
        return intArrayOf(0, 0, 0)
    }
}

data class Palette(val id: String, val label: String, val colors: List<Slot>)

data class Speed(val id: String, val label: String, val scale: Double)

data class Look(
    val id: String,
    val label: String,
    val kind: String,
    val beam: JSONObject?,
    val lpc: JSONObject?,
)

data class LookGroup(val title: String, val looks: List<Look>)

data class ShowCatalog(
    val groups: List<LookGroup>,
    val looks: Map<String, Look>,
    val palettes: List<Palette>,
    val paletteById: Map<String, Palette>,
    val speeds: List<Speed>,
    val speedById: Map<String, Double>,
)

fun buildRig(nLpc: Int, nBeam: Int, order: String = "lpc_first"): Rig {
    if (order != "lpc_first" && order != "beam_first") throw RigError("unknown order $order")
    for ((name, n) in listOf("LPC008" to nLpc, "BEAM" to nBeam)) {
        if (n < 0) throw RigError("$name count must be >= 0")
        if (n > MAX_EACH) throw RigError("$name count $n is above $MAX_EACH")
    }
    val blocks = mutableListOf(Triple("lpc", nLpc, LPC_CH), Triple("beam", nBeam, BEAM_CH))
    if (order == "beam_first") blocks.reverse()
    val fixtures = mutableListOf<Fixture>()
    var cursor = 0
    val seen = mutableMapOf("lpc" to 0, "beam" to 0)
    for ((kind, count, channels) in blocks) {
        repeat(count) {
            if (cursor + channels > UNIVERSE) {
                throw RigError("el mapa pasa de $UNIVERSE canales ($kind en ${cursor + 1})")
            }
            val index = seen.getValue(kind)
            fixtures += Fixture(kind, index, cursor + 1, cursor, channels, "A%03d".format(cursor + 1))
            seen[kind] = index + 1
            cursor += channels
        }
    }
    return Rig(order, nLpc, nBeam, fixtures, cursor)
}

fun fixturesOf(rig: Rig, kind: String): List<Fixture> = rig.fixtures.filter { it.type == kind }

fun loadCatalog(looksText: String, palettesText: String): ShowCatalog {
    val looksJson = JSONObject(looksText)
    val palettesJson = JSONObject(palettesText)
    val groups = mutableListOf<LookGroup>()
    val byId = linkedMapOf<String, Look>()
    val groupArr = looksJson.getJSONArray("groups")
    for (g in 0 until groupArr.length()) {
        val group = groupArr.getJSONObject(g)
        val looks = mutableListOf<Look>()
        val arr = group.getJSONArray("looks")
        for (i in 0 until arr.length()) {
            val raw = arr.getJSONObject(i)
            val look =
                Look(
                    id = raw.getString("id"),
                    label = raw.getString("label"),
                    kind = raw.getString("kind"),
                    beam = if (raw.has("beam")) raw.getJSONObject("beam") else null,
                    lpc = if (raw.has("lpc")) raw.getJSONObject("lpc") else null,
                )
            if (look.kind == "geometry" && look.beam?.has("sequence") != true) {
                throw IllegalArgumentException("look ${look.id} needs beam.sequence")
            }
            if (look.kind == "light" && look.lpc?.has("engine") != true) {
                throw IllegalArgumentException("look ${look.id} needs lpc.engine")
            }
            if (look.id in byId) throw IllegalArgumentException("duplicate look ${look.id}")
            byId[look.id] = look
            looks += look
        }
        groups += LookGroup(group.getString("title"), looks)
    }
    val palettes = mutableListOf<Palette>()
    val palArr = palettesJson.getJSONArray("palettes")
    for (i in 0 until palArr.length()) {
        val raw = palArr.getJSONObject(i)
        val colors = raw.getJSONArray("colors")
        if (colors.length() == 0) throw IllegalArgumentException("palette ${raw.optString("id")} needs colors")
        val slots = List(colors.length()) { slotFrom(colors.getJSONObject(it)) }
        palettes += Palette(raw.getString("id"), raw.getString("label"), slots)
    }
    val speeds = mutableListOf<Speed>()
    val speedArr = looksJson.getJSONArray("speeds")
    for (i in 0 until speedArr.length()) {
        val raw = speedArr.getJSONObject(i)
        speeds += Speed(raw.getString("id"), raw.getString("label"), raw.getDouble("scale"))
    }
    val speedById = speeds.associate { it.id to it.scale }
    if (speedById["medio"] != 1.0) throw IllegalArgumentException("speed 'medio' must be scale 1")
    return ShowCatalog(groups, byId, palettes, palettes.associateBy { it.id }, speeds, speedById)
}

private fun slotFrom(obj: JSONObject): Slot {
    val name = if (obj.has("name")) obj.getString("name") else ""
    val r: Int
    val g: Int
    val b: Int
    val w: Int
    val halo: IntArray
    if (obj.has("beam")) {
        val raw = Seq.ints(obj.getJSONArray("beam"))
        r = raw.getOrElse(0) { 0 }
        g = raw.getOrElse(1) { 0 }
        b = raw.getOrElse(2) { 0 }
        w = raw.getOrElse(3) { 0 }
        halo = if (obj.has("halo")) Seq.ints(obj.getJSONArray("halo")) else intArrayOf(r, g, b)
    } else {
        r = obj.getInt("r")
        g = obj.getInt("g")
        b = obj.getInt("b")
        w = if (obj.has("w")) obj.getInt("w") else 0
        halo = if (obj.has("halo")) Seq.ints(obj.getJSONArray("halo")) else intArrayOf(r, g, b)
    }
    return Slot(name, r, g, b, w, intArrayOf(halo[0], halo[1], halo[2]), intArrayOf(r, g, b, w))
}

private val RATE_KEYS = listOf("pan_hz", "tilt_hz", "open_hz", "flash_hz", "circle_hz", "ring_hz", "pan_dps")
private val PERIOD_KEYS = listOf("color_period", "pan_period", "period", "hold_min", "hold_max")

fun prepareSequence(raw: JSONObject, palette: Palette, scale: Double): JSONObject {
    val out = JSONObject(raw.toString())
    if (scale != 1.0) {
        for (key in RATE_KEYS) if (out.has(key)) out.put(key, out.getDouble(key) * scale)
        for (key in PERIOD_KEYS) if (out.has(key)) out.put(key, out.getDouble(key) / scale)
        if (out.has("speed") && out.get("speed") is Number) {
            out.put("speed", clamp(out.getDouble("speed") * scale))
        }
    }
    val rows = JSONArray()
    palette.colors.forEachIndexed { i, slot ->
        rows.put(
            JSONObject()
                .put("name", slot.name.ifEmpty { "c$i" })
                .put("beam", JSONArray(slot.beam.toList()))
                .put("halo", JSONArray(slot.halo.toList())),
        )
    }
    val slotA = palette.colors[0]
    val slotB = palette.colors.getOrElse(1) { slotA }
    if (out.has("a") && out.get("a") is JSONObject && out.getJSONObject("a").has("r")) {
        paintSide(out.getJSONObject("a"), slotA)
        paintSide(out.getJSONObject("b"), slotB)
    }
    if (listOfObjects(out, "colors")) out.put("colors", rows)
    if (listOfObjects(out, "palette")) out.put("palette", rows)
    return out
}

private fun paintSide(side: JSONObject, slot: Slot) {
    side.put("r", slot.r)
    side.put("g", slot.g)
    side.put("b", slot.b)
    side.put("w", slot.w)
    side.put("halo", JSONArray(slot.halo.toList()))
}

private fun listOfObjects(obj: JSONObject, key: String): Boolean {
    if (!obj.has(key) || obj.get(key) !is JSONArray) return false
    val arr = obj.getJSONArray(key)
    return arr.length() > 0 && arr.get(0) is JSONObject
}

fun paletteStep(t: Double, nColors: Int, scale: Double): Int {
    if (nColors <= 2) return 0
    val hold = COLOR_HOLD / (if (scale > 0) scale else 1.0)
    return (floor(t / hold).toInt()) % nColors
}

private fun engineCycles(seq: JSONObject): Boolean = listOfObjects(seq, "colors") || listOfObjects(seq, "palette")

private fun paintBeamColor(frame: IntArray, slot: Slot) {
    frame[7] = slot.beam[0]
    frame[8] = slot.beam[1]
    frame[9] = slot.beam[2]
    frame[10] = slot.beam[3]
    val hr = slot.halo[0]
    val hg = slot.halo[1]
    val hb = slot.halo[2]
    var p = 11
    repeat(6) {
        frame[p++] = hr
        frame[p++] = hg
        frame[p++] = hb
    }
}

fun lpcBytes(r: Int, g: Int, b: Int, dimmer: Int = 255, hardOff: Boolean = false): IntArray {
    if (hardOff || dimmer <= 0) return IntArray(LPC_CH)
    return intArrayOf(dimmer, r, g, b, 0, CH6_LINEAR, 0)
}

fun blackoutBuffer(rig: Rig): IntArray {
    val buf = IntArray(rig.span)
    for (fx in rig.fixtures) {
        if (fx.type == "beam") blackoutFrame().copyInto(buf, fx.start)
    }
    return buf
}

private data class LightState(val r: Int, val g: Int, val b: Int, val dimmer: Int, val hardOff: Boolean)

private class Hold(holdMin: Double, holdMax: Double, private val nColors: Int) {
    private val lo = holdMin
    private val hi = maxOf(holdMax, holdMin)
    var on = Random.nextBoolean()
    private var until = uniform(lo, hi)
    var slot = Random.nextInt(maxOf(1, nColors))

    fun at(t: Double): Pair<Boolean, Int> {
        if (t >= until) {
            on = !on
            slot = Random.nextInt(maxOf(1, nColors))
            until = t + uniform(lo, hi)
        }
        return on to slot
    }
}

private fun uniform(lo: Double, hi: Double): Double = lo + Random.nextDouble() * (hi - lo)

private class Bolt(private val colors: List<IntArray>, private val base: JSONObject, private val fps: Double) {
    private val queue = ArrayDeque<LightState>()
    private var nextT = uniform(0.05, base.optDouble("gap_max", 2.4) * 0.5)

    fun lookAt(t: Double): LightState {
        if (queue.isNotEmpty()) return queue.removeFirst()
        if (t >= nextT) {
            queue.addAll(strike())
            val strikeS = queue.size / fps
            val gapMin = base.optDouble("gap_min", 0.5)
            val gapMax = maxOf(base.optDouble("gap_max", 2.4), gapMin)
            nextT = t + strikeS + uniform(gapMin, gapMax)
            return queue.removeFirst()
        }
        return LightState(0, 0, 0, 0, true)
    }

    private fun strike(): List<LightState> {
        val color = colors[Random.nextInt(colors.size)]
        val burstsMin = base.optInt("bursts_min", 1)
        val burstsMax = base.optInt("bursts_max", 3)
        val nBursts = Random.nextInt(burstsMin, burstsMax + 1)
        val flashMin = base.optDouble("flash_min", 0.05)
        val flashMax = base.optDouble("flash_max", 0.14)
        val gapMin = base.optDouble("burst_gap_min", 0.04)
        val gapMax = base.optDouble("burst_gap_max", 0.11)
        val frames = mutableListOf<LightState>()
        for (i in 0 until nBursts) {
            val dim = if (i == 0) 255 else Random.nextInt(90, 201)
            val nOn = maxOf(1, pythonRound(uniform(flashMin, flashMax) * fps))
            repeat(nOn) { frames += LightState(color[0], color[1], color[2], dim, false) }
            if (i + 1 < nBursts) {
                val nOff = maxOf(1, pythonRound(uniform(gapMin, gapMax) * fps))
                repeat(nOff) { frames += LightState(0, 0, 0, 0, true) }
            }
        }
        return frames
    }
}

private class LightGesture(
    private val engine: String,
    private val base: JSONObject,
    private val palette: Palette,
    private val scale: Double,
    private val n: Int,
) {
    private val bolts: List<Bolt>
    private val holds: List<Hold>

    init {
        val safe = if (scale > 0) scale else 1.0
        bolts =
            if (engine == "lightning" && n > 0) {
                val colors = palette.colors.map { it.parRgb() }
                List(n) { Bolt(colors, scaledBolt(base, safe), base.optDouble("fps", 12.0)) }
            } else {
                emptyList()
            }
        holds =
            if (engine == "random" && n > 0) {
                val lo = number(base, "holdMin", "hold_min", 0.35) / safe
                val hi = number(base, "holdMax", "hold_max", 1.4) / safe
                List(n) { Hold(lo, maxOf(hi, lo), palette.colors.size) }
            } else {
                emptyList()
            }
    }

    fun states(t: Double): List<LightState> {
        if (n <= 0) return emptyList()
        return when (engine) {
            "dual_breathe" -> breathe(t)
            "alt_strobe" -> strobe(t)
            "chase" -> chase(t)
            "dual_fade" -> fade(t)
            "lightning" -> bolts.map { it.lookAt(t) }
            "random" -> random(t)
            else -> error("unknown light engine $engine")
        }
    }

    private fun breathe(t: Double): List<LightState> {
        val period = base.optDouble("period", 5.0) / (if (scale > 0) scale else 1.0)
        val lo = base.optInt("dimmer_lo", 50)
        val hi = base.optInt("dimmer_hi", 255)
        val dims =
            if (n == 2) {
                val u = 0.5 + 0.5 * sin(2.0 * PI * t / period - PI / 2.0)
                listOf(pythonRound(lo + (hi - lo) * u), pythonRound(lo + (hi - lo) * (1.0 - u)))
            } else {
                List(n) { i ->
                    val u = 0.5 + 0.5 * sin(2.0 * PI * (t / period + i.toDouble() / n) - PI / 2.0)
                    pythonRound(lo + (hi - lo) * u)
                }
            }
        val step = paletteStep(t, palette.colors.size, scale)
        return dims.mapIndexed { i, dim ->
            val rgb = palette.colors[(i + step) % palette.colors.size].parRgb()
            LightState(rgb[0], rgb[1], rgb[2], dim, false)
        }
    }

    private fun strobe(t: Double): List<LightState> {
        val hz = base.optDouble("hz", 1.0) * scale
        val nColors = palette.colors.size
        if (n == 2 && nColors == 2) {
            val stage = (floor(t * hz * 4.0).toInt()) % 4
            val picks = listOf(0 to false, null to true, 1 to false, null to true)
            val (slot, off) = picks[stage]
            return List(2) { i ->
                if (off || slot != i) {
                    LightState(0, 0, 0, 0, true)
                } else {
                    val rgb = palette.colors[i].parRgb()
                    LightState(rgb[0], rgb[1], rgb[2], 255, false)
                }
            }
        }
        return List(n) { i ->
            val phase = pythonMod(t * hz + i.toDouble() / maxOf(n, 1), 1.0)
            if (phase < 0.25) {
                val rgb = palette.colors[(i + floor(t * hz).toInt()) % nColors].parRgb()
                LightState(rgb[0], rgb[1], rgb[2], 255, false)
            } else {
                LightState(0, 0, 0, 0, true)
            }
        }
    }

    private fun chase(t: Double): List<LightState> {
        val hz = base.optDouble("hz", 1.0) * scale
        val nColors = palette.colors.size
        if (n == 2 && nColors == 2) {
            val swap = (floor(t * hz * 2.0).toInt()) % 2
            return List(2) { i ->
                val rgb = palette.colors[i xor swap].parRgb()
                LightState(rgb[0], rgb[1], rgb[2], 255, false)
            }
        }
        val step = (floor(t * hz * nColors).toInt()) % nColors
        return List(n) { i ->
            val rgb = palette.colors[(i + step) % nColors].parRgb()
            LightState(rgb[0], rgb[1], rgb[2], 255, false)
        }
    }

    private fun fade(t: Double): List<LightState> {
        val seconds = base.optDouble("seconds_per", 2.0) / (if (scale > 0) scale else 1.0)
        val dim = base.optInt("dimmer", 255)
        val cols = palette.colors.map { it.parRgb() }
        if (n == 2 && cols.size == 2) {
            val pos = t / seconds
            val u = pos - floor(pos)
            val i = floor(pos).toInt() % 2
            val left = if (i == 0) cols[0] else cols[1]
            val right = if (i == 0) cols[1] else cols[0]
            return listOf(mixState(u, left, right, dim), mixState(u, right, left, dim))
        }
        val nColors = cols.size
        return List(n) { i ->
            val pos = t / seconds + (if (n > 0) i.toDouble() / n else 0.0)
            val u = pos - floor(pos)
            val left = cols[floor(pos).toInt() % nColors]
            val right = cols[(floor(pos).toInt() + 1) % nColors]
            mixState(u, left, right, dim)
        }
    }

    private fun random(t: Double): List<LightState> =
        holds.map { hold ->
            val (on, slot) = hold.at(t)
            if (!on) {
                LightState(0, 0, 0, 0, true)
            } else {
                val rgb = palette.colors[slot % palette.colors.size].parRgb()
                LightState(rgb[0], rgb[1], rgb[2], 255, false)
            }
        }
}

private fun mixState(u: Double, left: IntArray, right: IntArray, dim: Int): LightState {
    val rgb = IntArray(3) { i -> pythonRound(left[i] + (right[i] - left[i]) * u).coerceIn(0, 255) }
    return LightState(rgb[0], rgb[1], rgb[2], dim, false)
}

private fun number(obj: JSONObject, a: String, b: String, default: Double): Double =
    when {
        obj.has(a) -> obj.getDouble(a)
        obj.has(b) -> obj.getDouble(b)
        else -> default
    }

private fun scaledBolt(base: JSONObject, scale: Double): JSONObject {
    val out = JSONObject(base.toString())
    for (key in listOf("gap_min", "gap_max", "flash_min", "flash_max", "burst_gap_min", "burst_gap_max")) {
        if (out.has(key)) out.put(key, out.getDouble(key) / scale)
    }
    return out
}

private fun colorFromSeq(seq: Seq, index: Int, t: Double): Pair<IntArray, IntArray> {
    if (seq.has("colors")) {
        val colors = seq.arr("colors")
        if (colors.length() > 0 && colors.get(0) is JSONObject && colors.getJSONObject(0).has("beam")) {
            val hz = seq.d("flash_hz", 2.0)
            val picked = colors.getJSONObject((floor(t * hz).toInt()) % colors.length())
            return beam4(Seq.ints(picked.getJSONArray("beam"))) to halo3(picked, beam4(Seq.ints(picked.getJSONArray("beam"))))
        }
    }
    if (seq.has("palette")) {
        val palette = seq.arr("palette")
        if (palette.length() > 0 && palette.get(0) is JSONObject && palette.getJSONObject(0).has("beam")) {
            val period = seq.d("color_period", 4.0).let { if (it == 0.0) 4.0 else it }
            val n = palette.length()
            val phase = pythonMod(t / period + index.toDouble() / n, n.toDouble())
            val picked = palette.getJSONObject(phase.toInt() % n)
            val beam = beam4(Seq.ints(picked.getJSONArray("beam")))
            return beam to halo3(picked, beam)
        }
    }
    val side = if (index % 2 == 0) seq.obj("a") else seq.obj("b")
    return seq.sideBeam(side) to seq.sideHalo(side)
}

private fun beam4(raw: IntArray): IntArray = IntArray(4) { i -> raw.getOrElse(i) { 0 } }

private fun halo3(obj: JSONObject, beam: IntArray): IntArray =
    if (obj.has("halo")) {
        val h = Seq.ints(obj.getJSONArray("halo"))
        intArrayOf(h[0], h[1], h[2])
    } else {
        intArrayOf(beam[0], beam[1], beam[2])
    }

private fun beamFanHeads(seq: Seq, n: Int, t: Double): List<IntArray> {
    val hz =
        listOf("pan_hz", "open_hz", "circle_hz", "tilt_hz")
            .firstOrNull { seq.has(it) && seq.d(it) != 0.0 }
            ?.let { seq.d(it) }
            ?: 0.3
    val tiltHz = if (seq.has("tilt_hz")) seq.d("tilt_hz") else hz * 0.6
    val amp = seq.d("pan_amp", seq.d("spread_max", 70.0))
    val tiltAmp = seq.d("tilt_amp", 35.0)
    val speed = seq.i("speed", 25)
    val dimmer = if (seq.has("dimmer")) seq.i("dimmer") else seq.i("dimmer_on", 255)
    val strobe = seq.i("strobe", 0)
    return List(n) { i ->
        val pair = minOf(i, n - 1 - i)
        val phase = pair.toDouble() / n
        val sign = if (i <= (n - 1) / 2.0) 1.0 else -1.0
        val pan = 128.0 + sign * amp * sin(2.0 * PI * (hz * t + phase))
        val tilt = 128.0 + tiltAmp * sin(2.0 * PI * (tiltHz * t + i.toDouble() / n))
        val (color, halo) = colorFromSeq(seq, i, t)
        headFrame(pan, tilt, speed, dimmer, strobe, color, haloRgb = halo)
    }
}

private fun beamFromState(state: LightState): IntArray {
    if (state.hardOff || state.dimmer <= 0) {
        val frame = blackoutFrame()
        frame[0] = 128
        frame[2] = 128
        return frame
    }
    return headFrame(
        128.0,
        128.0,
        180,
        state.dimmer,
        0,
        intArrayOf(state.r, state.g, state.b, 0),
        haloRgb = intArrayOf(state.r, state.g, state.b),
    )
}

class ShowPlayer(
    val rig: Rig,
    private val look: Look,
    private val palette: Palette,
    private val scale: Double,
    beamSequences: Map<String, JSONObject>,
    lpcSequences: Map<String, JSONObject>,
    lastPose: List<Pair<Double, Double>> = emptyList(),
) {
    var fps: Double = 18.0
        private set
    val lastPose: MutableList<Pair<Double, Double>>
    private val lpcFx = fixturesOf(rig, "lpc")
    private val beamFx = fixturesOf(rig, "beam")
    private var duo: FrameMaker? = null
    private var prepared: JSONObject? = null
    private var lightLpc: LightGesture? = null
    private var lightBeam: LightGesture? = null

    init {
        this.lastPose = lastPose.toMutableList()
        while (this.lastPose.size < beamFx.size) this.lastPose += 128.0 to 128.0
        if (look.kind == "geometry") {
            val name = look.beam!!.getString("sequence")
            val raw = beamSequences[name] ?: error("secuencia ausente: $name")
            val seq = prepareSequence(raw, palette, scale)
            prepared = seq
            val n = beamFx.size
            if (n == 1 || n == 2) {
                val run = engineFor(Seq(seq))
                duo = run.make
                fps = run.fps
            } else if (n > 2) {
                fps = seq.optDouble("fps", 18.0)
            }
        } else {
            val lpc = look.lpc ?: error("look ${look.id} needs lpc")
            val base = JSONObject()
            val seqName = lpc.optString("sequence", "")
            if (seqName.isNotEmpty()) {
                val raw = lpcSequences[seqName] ?: error("secuencia ausente: $seqName")
                val copy = JSONObject(raw.toString())
                val keys = copy.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    base.put(key, copy.get(key))
                }
            }
            val overlay = lpc.keys()
            while (overlay.hasNext()) {
                val key = overlay.next()
                if (key != "sequence") base.put(key, lpc.get(key))
            }
            fps = base.optDouble("fps", 12.0)
            val engine = base.getString("engine")
            lightLpc = LightGesture(engine, base, palette, scale, lpcFx.size)
            lightBeam = LightGesture(engine, base, palette, scale, beamFx.size)
        }
    }

    fun frame(now: Double, t: Double): IntArray {
        val buf = IntArray(rig.span)
        if (look.kind == "geometry") {
            val step = paletteStep(t, palette.colors.size, scale)
            lpcFx.forEachIndexed { i, fx ->
                val rgb = palette.colors[(i + step) % palette.colors.size].parRgb()
                lpcBytes(rgb[0], rgb[1], rgb[2]).copyInto(buf, fx.start)
            }
            val heads = beamHeads(now, t)
            beamFx.zip(heads).forEach { (fx, raw) ->
                raw.copyInto(buf, fx.start)
                lastPose[fx.index] = raw[0].toDouble() to raw[2].toDouble()
            }
            return buf
        }
        val lpcStates = lightLpc?.states(t).orEmpty()
        lpcFx.zip(lpcStates).forEach { (fx, state) ->
            lpcBytes(state.r, state.g, state.b, state.dimmer, state.hardOff).copyInto(buf, fx.start)
        }
        val beamStates = lightBeam?.states(t).orEmpty()
        beamFx.zip(beamStates).forEach { (fx, state) ->
            val raw = beamFromState(state)
            raw.copyInto(buf, fx.start)
            lastPose[fx.index] = 128.0 to 128.0
        }
        return buf
    }

    private fun beamHeads(now: Double, t: Double): List<IntArray> {
        val n = beamFx.size
        if (n <= 0) return emptyList()
        val heads =
            if (n > 2) {
                beamFanHeads(Seq(prepared!!), n, t)
            } else {
                val duoFrame = duo!!.frame(t, now)
                if (n == 1) listOf(duoFrame.copyOfRange(0, BEAM_CH))
                else listOf(duoFrame.copyOfRange(0, BEAM_CH), duoFrame.copyOfRange(BEAM_CH, BEAM_CH * 2))
            }
        val seq = prepared
        if (seq != null && !engineCycles(seq) && palette.colors.size > 2) {
            val step = paletteStep(t, palette.colors.size, scale)
            heads.forEachIndexed { i, raw ->
                paintBeamColor(raw, palette.colors[(step + i) % palette.colors.size])
            }
        }
        return heads
    }
}
