package org.deovolente.beam.engine

import org.json.JSONArray
import org.json.JSONObject

class Seq(val raw: JSONObject) {
    val engine: String = raw.getString("engine")

    fun d(key: String): Double = raw.getDouble(key)

    fun d(key: String, default: Double): Double =
        if (raw.has(key) && !raw.isNull(key)) raw.getDouble(key) else default

    fun i(key: String): Int = raw.getInt(key)

    fun i(key: String, default: Int): Int =
        if (raw.has(key) && !raw.isNull(key)) raw.getInt(key) else default

    fun bool(key: String, default: Boolean): Boolean =
        if (raw.has(key) && !raw.isNull(key)) raw.getBoolean(key) else default

    fun obj(key: String): JSONObject = raw.getJSONObject(key)

    fun arr(key: String): JSONArray = raw.getJSONArray(key)

    fun has(key: String): Boolean = raw.has(key) && !raw.isNull(key)

    fun sideBeam(side: JSONObject): IntArray =
        intArrayOf(side.getInt("r"), side.getInt("g"), side.getInt("b"), side.getInt("w"))

    fun sideHalo(side: JSONObject): IntArray {
        val h = side.getJSONArray("halo")
        return intArrayOf(h.getInt(0), h.getInt(1), h.getInt(2))
    }

    companion object {
        fun parse(text: String): Seq = Seq(JSONObject(text))

        fun ints(arr: JSONArray): IntArray = IntArray(arr.length()) { arr.getInt(it) }
    }
}
