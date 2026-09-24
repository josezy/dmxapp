package org.deovolente.beam.engine

import java.io.File
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ShowConsoleTest {
    private val showDir = File(System.getenv("SHOW_DIR") ?: error("SHOW_DIR"))
    private val beamDir = File(System.getenv("BEAM_SEQ_DIR") ?: error("BEAM_SEQ_DIR"))
    private val lpcDir = File(System.getenv("LPC_SEQ_DIR") ?: error("LPC_SEQ_DIR"))

    private fun catalog() =
        loadCatalog(
            File(showDir, "looks.json").readText(),
            File(showDir, "palettes.json").readText(),
        )

    private fun jsonDir(dir: File): Map<String, JSONObject> =
        dir.listFiles { file -> file.extension == "json" }!!
            .associate { it.nameWithoutExtension to JSONObject(it.readText()) }

    @Test
    fun rigMatchesWebMap() {
        val duo = buildRig(0, 2)
        assertEquals(listOf(1, 31), duo.fixtures.map { it.address })
        assertEquals(60, duo.span)
        val pars = buildRig(2, 0)
        assertEquals(listOf(1, 8), pars.fixtures.map { it.address })
        assertEquals(14, pars.span)
        val mixed = buildRig(2, 2, "lpc_first")
        assertEquals(listOf("A001", "A008", "A015", "A045"), mixed.fixtures.map { it.label })
        assertEquals(74, mixed.span)
        val flipped = buildRig(2, 2, "beam_first")
        assertEquals(listOf(1, 31, 61, 68), flipped.fixtures.map { it.address })
    }

    @Test
    fun sangreOnParsAndDiscoCyclesAndLightCenters() {
        val cat = catalog()
        val beams = jsonDir(beamDir)
        val lpcs = jsonDir(lpcDir)
        val sangre = cat.paletteById.getValue("sangre")
        val abre = ShowPlayer(buildRig(2, 0), cat.looks.getValue("abre-cierra"), sangre, 1.0, beams, lpcs)
        val buf = abre.frame(0.0, 0.0)
        assertTrue(buf.copyOfRange(0, 7).contentEquals(intArrayOf(255, 255, 0, 8, 0, 25, 0)))
        assertTrue(buf.copyOfRange(7, 14).contentEquals(intArrayOf(255, 200, 0, 0, 0, 25, 0)))

        val disco = cat.paletteById.getValue("disco")
        val cycling = ShowPlayer(buildRig(0, 2), cat.looks.getValue("abre-cierra"), disco, 1.0, beams, lpcs)
        val seen = (0 until 5).map { i -> cycling.frame(i * 1.2, i * 1.2).copyOfRange(7, 11).toList() }.toSet()
        assertEquals(disco.colors.map { it.beam.toList() }.toSet(), seen)

        val light =
            ShowPlayer(
                buildRig(2, 1),
                cat.looks.getValue("breathe"),
                cat.paletteById.getValue("calida"),
                1.0,
                beams,
                lpcs,
                lastPose = listOf(20.0 to 200.0),
            )
        val frame = light.frame(1.0, 0.4)
        assertEquals(44, frame.size)
        assertTrue(frame[0] > 0)
        assertEquals(128, frame[14])
        assertEquals(128, frame[16])

        for (id in listOf("corona", "tiron-disco", "fade")) {
            val player = ShowPlayer(buildRig(2, 2), cat.looks.getValue(id), disco, 1.0, beams, lpcs)
            val out = player.frame(1.0, 0.5)
            assertEquals(id, 74, out.size)
            assertTrue(id, out.all { it in 0..255 })
        }
    }
}
