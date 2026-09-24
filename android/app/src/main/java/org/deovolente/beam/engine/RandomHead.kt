package org.deovolente.beam.engine

import kotlin.random.Random

class RandomHead(
    seq: Seq,
    private val rng: Random = Random.Default,
    haloAlwaysOn: Boolean = false,
    haloOffset: Int = 0,
    now: Double = nowPerf(),
) {
    private val palette: List<Pair<IntArray, IntArray>>
    private val holdMin: Double = seq.d("hold_min", 0.1)
    private val holdMax: Double = seq.d("hold_max", 1.5)
    private val haloAlwaysOn: Boolean = haloAlwaysOn
    private val haloOffset: Int = haloOffset
    var on: Boolean = rng.nextBoolean()
        private set
    private var until: Double = now + uniform(holdMin, holdMax)
    private var idx: Int
    var beam: IntArray
        private set
    var halo: IntArray
        private set

    init {
        val pal = seq.arr("palette")
        palette =
            (0 until pal.length()).map { i ->
                val item = pal.getJSONObject(i)
                Seq.ints(item.getJSONArray("beam")) to Seq.ints(item.getJSONArray("halo"))
            }
        idx = rng.nextInt(palette.size)
        val applied = apply(idx)
        beam = applied.first
        halo = applied.second
    }

    private fun uniform(lo: Double, hi: Double): Double = lo + rng.nextDouble() * (hi - lo)

    private fun apply(i: Int): Pair<IntArray, IntArray> {
        idx = i.mod(palette.size)
        val beam = palette[idx].first
        val haloI = (idx + haloOffset).mod(palette.size)
        val halo = palette[haloI].second
        return beam to halo
    }

    fun tick(now: Double) {
        if (now < until) return
        on = !on
        until = now + uniform(holdMin, holdMax)
        val nxt = rng.nextInt(palette.size)
        if (haloAlwaysOn) {
            halo = palette[nxt].second
            if (on) beam = palette[nxt].first
        } else if (on) {
            val applied = apply(nxt)
            beam = applied.first
            halo = applied.second
        }
    }

    fun dart(dimmerOn: Int, dimmerOff: Int, dartOffZero: Boolean): Triple<Int, IntArray, IntArray> {
        if (on) return Triple(dimmerOn, beam, halo)
        if (dartOffZero) return Triple(dimmerOn, intArrayOf(0, 0, 0, 0), halo)
        return Triple(dimmerOff, beam, halo)
    }
}
