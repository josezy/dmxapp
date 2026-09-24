package org.deovolente.beam.engine

import java.io.File
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoldenFrameTest {
    private val seqDir = File(System.getenv("BEAM_SEQ_DIR") ?: error("BEAM_SEQ_DIR"))
    private val goldenDir = File(System.getenv("BEAM_GOLDEN_DIR") ?: error("BEAM_GOLDEN_DIR"))

    @Test
    fun pythonRoundMatchesCPython3() {
        assertEquals(0, pythonRound(0.4))
        assertEquals(0, pythonRound(0.5))
        assertEquals(2, pythonRound(1.5))
        assertEquals(2, pythonRound(2.5))
        assertEquals(4, pythonRound(3.5))
        assertEquals(128, pythonRound(127.5))
        assertEquals(126, pythonRound(126.5))
        assertEquals(0, pythonRound(-0.5))
        assertEquals(-2, pythonRound(-1.5))
        assertEquals(0, clamp(-1.5))
        assertEquals(255, clamp(300.0))
    }

    @Test
    fun blackoutIsSixtyBytes() {
        val frame = blackoutUniverse()
        assertEquals(60, frame.size)
        assertEquals(128, frame[0])
        assertEquals(128, frame[2])
        assertEquals(180, frame[4])
        assertEquals(128, frame[30])
        assertEquals(0, frame[5])
        assertEquals(0, frame[35])
    }

    @Test
    fun deterministicGoldensMatchPython() {
        val files = goldenDir.listFiles { _, name -> name.endsWith(".json") } ?: emptyArray()
        assertTrue("no goldens in $goldenDir", files.isNotEmpty())
        for (file in files.sortedBy { it.name }) {
            val golden = JSONObject(file.readText())
            val name = golden.getString("sequence")
            val seq = Seq.parse(File(seqDir, "$name.json").readText())
            val run = engineFor(seq)
            assertEquals(name, golden.getString("engine"), seq.engine)
            assertEquals(name, golden.getDouble("fps"), run.fps, 1e-9)
            val frames = golden.getJSONArray("frames")
            assertEquals("$name frame count", 24, frames.length())
            for (n in 0 until frames.length()) {
                val t = n / run.fps
                val got = run.make.frame(t, t)
                val want = Seq.ints(frames.getJSONArray(n))
                assertArrayEquals("$name frame $n", want, got)
            }
        }
    }

    @Test
    fun randomEnginesEmitSixtyChannels() {
        val names =
            listOf(
                "tirones-random-calido",
                "abanico-random-frio",
                "abre-cierra-random-andino",
                "abanico-tiron-disco",
            )
        for (name in names) {
            val seq = Seq.parse(File(seqDir, "$name.json").readText())
            val run = engineFor(seq)
            val frame = run.make.frame(0.0, 0.0)
            assertEquals(name, 60, frame.size)
            assertTrue(name, frame.all { it in 0..255 })
            val later = run.make.frame(1.0, 1.0)
            assertEquals(name, 60, later.size)
        }
    }

    @Test
    fun allPadScenesHaveJson() {
        val show = org.deovolente.beam.ShowPad.parse(File(seqDir.parentFile, "show.json").readText())
        assertTrue("empty show.json", show.groups.isNotEmpty())
        for (group in show.groups) {
            for (scene in group.scenes) {
                val f = File(seqDir, "${scene.name}.json")
                assertTrue(scene.name, f.isFile)
                val seq = Seq.parse(f.readText())
                engineFor(seq)
            }
        }
    }
}
