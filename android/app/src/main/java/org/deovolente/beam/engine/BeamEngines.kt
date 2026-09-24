package org.deovolente.beam.engine

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

private const val TWO_PI = 2.0 * PI

fun engineFor(seq: Seq): EngineRun {
    return when (seq.engine) {
        "sweep_mirror", "unison_search" -> makeSweepMirror(seq)
        "sweep_mirror_flash" -> makeSweepFlash(seq)
        "sweep_mirror_fade" -> makeSweepFade(seq)
        "abanico_tilt" -> makeAbanicoTilt(seq, contra = false)
        "contra_tilt" -> makeAbanicoTilt(seq, contra = true)
        "simetrico_abre_cierra" -> makeAbreCierra(seq)
        "spin_espejo" -> makeSpinEspejo(seq)
        "circulo_espejo" -> makeCirculo(seq)
        "paralelo_search" -> makeParalelo(seq)
        "tirones_random_calido" -> makeTironesRandom(seq)
        "abanico_random_frio" -> makeAbanicoRandom(seq)
        "abre_cierra_random_andino" -> makeAbreCierraRandom(seq)
        "corona_reloj_dardo" -> makeCoronaReloj(seq)
        "abanico_tiron_disco" -> makeAbanicoTironDisco(seq)
        else -> error("unknown beam engine ${seq.engine}")
    }
}

private fun makeSweepMirror(seq: Seq): EngineRun {
    val speed = seq.i("speed", 20)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val a = seq.obj("a")
    val b = seq.obj("b")
    val beamA = seq.sideBeam(a)
    val haloA = seq.sideHalo(a)
    val beamB = seq.sideBeam(b)
    val haloB = seq.sideHalo(b)
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val pose = sweepPose(seq, t)
        pack(
            headFrame(pose[0], pose[1], speed, dimmer, strobe, beamA, haloRgb = haloA),
            headFrame(pose[2], pose[3], speed, dimmer, strobe, beamB, haloRgb = haloB),
        )
    }
}

private fun makeSweepFlash(seq: Seq): EngineRun {
    val speed = seq.i("speed", 20)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val colors = seq.arr("colors")
    val hz = seq.d("flash_hz", 2.0)
    val beams = (0 until colors.length()).map { i ->
        val c = colors.getJSONObject(i)
        Seq.ints(c.getJSONArray("beam")) to Seq.ints(c.getJSONArray("halo"))
    }
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val i = (t * hz).toInt().mod(beams.size)
        val (beam, halo) = beams[i]
        val pose = sweepPose(seq, t)
        val fa = headFrame(pose[0], pose[1], speed, dimmer, strobe, beam, haloRgb = halo)
        val fb = headFrame(pose[2], pose[3], speed, dimmer, strobe, beam, haloRgb = halo)
        pack(fa, fb)
    }
}

private fun makeSweepFade(seq: Seq): EngineRun {
    val speed = seq.i("speed", 50)
    val dimmer = seq.i("dimmer", 180)
    val strobe = seq.i("strobe", 0)
    val pal = seq.arr("palette")
    val period = seq.d("color_period", 4.0)
    val beams = (0 until pal.length()).map { Seq.ints(pal.getJSONObject(it).getJSONArray("beam")) }
    val halos = (0 until pal.length()).map { Seq.ints(pal.getJSONObject(it).getJSONArray("halo")) }
    fun colorAt(t: Double, values: List<IntArray>): IntArray {
        val n = values.size
        val phase = pythonMod(t / period, n.toDouble())
        val i = phase.toInt()
        val frac = phase - i
        return lerpVec(values[i], values[(i + 1) % n], frac)
    }
    return EngineRun(seq.d("fps", 16.0)) { t, _ ->
        val beam = colorAt(t, beams)
        val halo = colorAt(t, halos)
        val pose = sweepPose(seq, t)
        val fa = headFrame(pose[0], pose[1], speed, dimmer, strobe, beam, haloRgb = halo)
        val fb = headFrame(pose[2], pose[3], speed, dimmer, strobe, beam, haloRgb = halo)
        pack(fa, fb)
    }
}

private fun makeAbanicoTilt(seq: Seq, contra: Boolean): EngineRun {
    val speed = seq.i("speed", 30)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val panA = seq.d("pan_a")
    val panB = seq.d("pan_b")
    val tiltC = seq.d("tilt_center", 128.0)
    val tiltAmp = seq.d("tilt_amp", 70.0)
    val tiltHz = seq.d("tilt_hz")
    val a = seq.obj("a")
    val b = seq.obj("b")
    val beamA = seq.sideBeam(a)
    val haloA = seq.sideHalo(a)
    val beamB = seq.sideBeam(b)
    val haloB = seq.sideHalo(b)
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val s = sin(TWO_PI * tiltHz * t)
        val ta = tiltC + tiltAmp * s
        val tb = if (contra) tiltC - tiltAmp * s else ta
        pack(
            headFrame(panA, ta, speed, dimmer, strobe, beamA, haloRgb = haloA),
            headFrame(panB, tb, speed, dimmer, strobe, beamB, haloRgb = haloB),
        )
    }
}

private fun makeAbreCierra(seq: Seq): EngineRun {
    val speed = seq.i("speed", 25)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val openHz = seq.d("open_hz")
    val tiltHz = seq.d("tilt_hz")
    val spreadMin = seq.d("spread_min")
    val spreadMax = seq.d("spread_max")
    val panC = seq.d("pan_center", 128.0)
    val tiltC = seq.d("tilt_center", 128.0)
    val tiltAmp = seq.d("tilt_amp", 35.0)
    val a = seq.obj("a")
    val b = seq.obj("b")
    val beamA = seq.sideBeam(a)
    val haloA = seq.sideHalo(a)
    val beamB = seq.sideBeam(b)
    val haloB = seq.sideHalo(b)
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val k = 0.5 + 0.5 * sin(TWO_PI * openHz * t)
        val spread = spreadMin + (spreadMax - spreadMin) * k
        val tilt = tiltC + tiltAmp * sin(TWO_PI * tiltHz * t)
        pack(
            headFrame(panC - spread, tilt, speed, dimmer, strobe, beamA, haloRgb = haloA),
            headFrame(panC + spread, tilt, speed, dimmer, strobe, beamB, haloRgb = haloB),
        )
    }
}

private fun makeSpinEspejo(seq: Seq): EngineRun {
    val speed = seq.i("speed", 30)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val dps = seq.d("pan_dps")
    val tiltHz = seq.d("tilt_hz")
    val tiltAmp = seq.d("tilt_amp", 30.0)
    val tiltC = seq.d("tilt_center", 128.0)
    val a = seq.obj("a")
    val b = seq.obj("b")
    val beamA = seq.sideBeam(a)
    val haloA = seq.sideHalo(a)
    val beamB = seq.sideBeam(b)
    val haloB = seq.sideHalo(b)
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val panA = pythonMod(t * dps, 256.0)
        val panB = pythonMod(-t * dps, 256.0)
        val tilt = tiltC + tiltAmp * sin(TWO_PI * tiltHz * t)
        pack(
            headFrame(panA, tilt, speed, dimmer, strobe, beamA, haloRgb = haloA),
            headFrame(panB, tilt, speed, dimmer, strobe, beamB, haloRgb = haloB),
        )
    }
}

private fun makeCirculo(seq: Seq): EngineRun {
    val speed = seq.i("speed", 25)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val hz = seq.d("circle_hz")
    val panAmp = seq.d("pan_amp")
    val tiltAmp = seq.d("tilt_amp")
    val panC = seq.d("pan_center", 128.0)
    val tiltC = seq.d("tilt_center", 128.0)
    val a = seq.obj("a")
    val b = seq.obj("b")
    val beamA = seq.sideBeam(a)
    val haloA = seq.sideHalo(a)
    val beamB = seq.sideBeam(b)
    val haloB = seq.sideHalo(b)
    val mirror = seq.bool("mirror_pan", true)
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val w = TWO_PI * hz * t
        val s = sin(w)
        val c = cos(w)
        val panA = panC + panAmp * s
        val panB = if (mirror) panC - panAmp * s else panA
        val tilt = tiltC + tiltAmp * c
        pack(
            headFrame(panA, tilt, speed, dimmer, strobe, beamA, haloRgb = haloA),
            headFrame(panB, tilt, speed, dimmer, strobe, beamB, haloRgb = haloB),
        )
    }
}

private fun makeParalelo(seq: Seq): EngineRun {
    val speed = seq.i("speed", 25)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val panHz = seq.d("pan_hz")
    val tiltHz = seq.d("tilt_hz")
    val panAmp = seq.d("pan_amp")
    val tiltAmp = seq.d("tilt_amp")
    val panC = seq.d("pan_center", 128.0)
    val tiltC = seq.d("tilt_center", 128.0)
    val offset = seq.d("pan_offset", 44.0)
    val a = seq.obj("a")
    val b = seq.obj("b")
    val beamA = seq.sideBeam(a)
    val haloA = seq.sideHalo(a)
    val beamB = seq.sideBeam(b)
    val haloB = seq.sideHalo(b)
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val sweep = panAmp * sin(TWO_PI * panHz * t)
        val tilt = tiltC + tiltAmp * sin(TWO_PI * tiltHz * t)
        pack(
            headFrame(panC + sweep - offset / 2, tilt, speed, dimmer, strobe, beamA, haloRgb = haloA),
            headFrame(panC + sweep + offset / 2, tilt, speed, dimmer, strobe, beamB, haloRgb = haloB),
        )
    }
}

private fun makeTironesRandom(seq: Seq): EngineRun {
    val speed = seq.i("speed", 0)
    val strobe = seq.i("strobe", 0)
    val dimOn = seq.i("dimmer_on", 255)
    val dimOff = seq.i("dimmer_off", 0)
    val panPeriod = seq.d("pan_period")
    val tiltHz = seq.d("tilt_hz")
    val panLo = seq.d("pan_lo")
    val panHi = seq.d("pan_hi")
    val tiltLo = seq.d("tilt_lo")
    val tiltHi = seq.d("tilt_hi")
    val offset = seq.i("halo_offset", 2)
    val heads = listOf(
        RandomHead(seq, haloOffset = offset),
        RandomHead(seq, haloOffset = offset),
    )
    return EngineRun(seq.d("fps", 18.0)) { t, now ->
        for (h in heads) h.tick(now)
        val phase = pythonMod(t / panPeriod, 1.0)
        val panA = lerp(panLo, panHi, phase)
        val panB = lerp(panHi, panLo, phase)
        val mid = (tiltLo + tiltHi) / 2
        val amp = (tiltHi - tiltLo) / 2
        val tilt = mid + amp * sin(TWO_PI * tiltHz * t)
        val pans = doubleArrayOf(panA, panB)
        val frames = Array(2) { i ->
            val (dim, beam, halo) = heads[i].dart(dimOn, dimOff, false)
            headFrame(pans[i], tilt, speed, dim, strobe, beam, haloRgb = halo)
        }
        pack(frames[0], frames[1])
    }
}

private fun makeAbanicoRandom(seq: Seq): EngineRun {
    val speed = seq.i("speed", 30)
    val strobe = seq.i("strobe", 0)
    val dimOn = seq.i("dimmer_on", 255)
    val dimOff = seq.i("dimmer_off", 0)
    val panA = seq.d("pan_a")
    val panB = seq.d("pan_b")
    val tiltC = seq.d("tilt_center", 128.0)
    val tiltAmp = seq.d("tilt_amp", 70.0)
    val tiltHz = seq.d("tilt_hz")
    val heads = listOf(RandomHead(seq), RandomHead(seq))
    return EngineRun(seq.d("fps", 18.0)) { t, now ->
        for (h in heads) h.tick(now)
        val tilt = tiltC + tiltAmp * sin(TWO_PI * tiltHz * t)
        val pans = doubleArrayOf(panA, panB)
        val frames = Array(2) { i ->
            val (dim, beam, halo) = heads[i].dart(dimOn, dimOff, false)
            headFrame(pans[i], tilt, speed, dim, strobe, beam, haloRgb = halo)
        }
        pack(frames[0], frames[1])
    }
}

private fun makeAbreCierraRandom(seq: Seq): EngineRun {
    val speed = seq.i("speed", 25)
    val strobe = seq.i("strobe", 0)
    val dimOn = seq.i("dimmer_on", 255)
    val dimOff = seq.i("dimmer_off", 0)
    val openHz = seq.d("open_hz")
    val tiltHz = seq.d("tilt_hz")
    val spreadMin = seq.d("spread_min")
    val spreadMax = seq.d("spread_max")
    val panC = seq.d("pan_center", 128.0)
    val tiltC = seq.d("tilt_center", 128.0)
    val tiltAmp = seq.d("tilt_amp", 35.0)
    val heads = listOf(RandomHead(seq), RandomHead(seq))
    return EngineRun(seq.d("fps", 18.0)) { t, now ->
        for (h in heads) h.tick(now)
        val k = 0.5 + 0.5 * sin(TWO_PI * openHz * t)
        val spread = spreadMin + (spreadMax - spreadMin) * k
        val tilt = tiltC + tiltAmp * sin(TWO_PI * tiltHz * t)
        val pans = doubleArrayOf(panC - spread, panC + spread)
        val frames = Array(2) { i ->
            val (dim, beam, halo) = heads[i].dart(dimOn, dimOff, false)
            headFrame(pans[i], tilt, speed, dim, strobe, beam, haloRgb = halo)
        }
        pack(frames[0], frames[1])
    }
}

private fun makeCoronaReloj(seq: Seq): EngineRun {
    val speed = seq.i("speed", 30)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val panA = seq.d("pan_a")
    val panB = seq.d("pan_b")
    val tiltC = seq.d("tilt_center", 128.0)
    val tiltAmp = seq.d("tilt_amp", 70.0)
    val tiltHz = seq.d("tilt_hz")
    val ringHz = seq.d("ring_hz", 0.7)
    val colorPeriod = seq.d("color_period", 2.4)
    val hand = Seq.ints(seq.arr("hand"))
    val pal = seq.arr("palette")
    val beams = (0 until pal.length()).map { Seq.ints(pal.getJSONObject(it).getJSONArray("beam")) }
    return EngineRun(seq.d("fps", 18.0)) { t, _ ->
        val tilt = tiltC + tiltAmp * sin(TWO_PI * tiltHz * t)
        val beam = beams[(t / colorPeriod).toInt().mod(beams.size)]
        val halo = haloHand(t, ringHz, hand)
        val fa = headFrame(panA, tilt, speed, dimmer, strobe, beam, haloBytes = halo)
        val fb = headFrame(panB, tilt, speed, dimmer, strobe, beam, haloBytes = halo)
        pack(fa, fb)
    }
}

private fun makeAbanicoTironDisco(seq: Seq): EngineRun {
    val speed = seq.i("speed", 0)
    val dimmer = seq.i("dimmer", 255)
    val strobe = seq.i("strobe", 0)
    val period = seq.d("period", 2.2)
    val panA = Seq.ints(seq.arr("pan_a"))
    val panB = Seq.ints(seq.arr("pan_b"))
    val tiltR = Seq.ints(seq.arr("tilt"))
    val heads = listOf(
        RandomHead(seq, haloAlwaysOn = seq.bool("halo_always_on", true)),
        RandomHead(seq, haloAlwaysOn = seq.bool("halo_always_on", true)),
    )
    val dartZero = seq.bool("dart_off_beam_zero", true)
    return EngineRun(seq.d("fps", 18.0)) { t, now ->
        for (h in heads) h.tick(now)
        val phase = pythonMod(t / period, 1.0)
        val tilt = lerp(tiltR[0].toDouble(), tiltR[1].toDouble(), phase)
        val pa = lerp(panA[0].toDouble(), panA[1].toDouble(), phase)
        val pb = lerp(panB[0].toDouble(), panB[1].toDouble(), phase)
        val pans = doubleArrayOf(pa, pb)
        val frames = Array(2) { i ->
            val (dim, beam, halo) = heads[i].dart(dimmer, 0, dartZero)
            headFrame(pans[i], tilt, speed, dim, strobe, beam, haloRgb = halo)
        }
        pack(frames[0], frames[1])
    }
}
