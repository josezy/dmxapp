package org.deovolente.beam

import org.deovolente.beam.engine.Seq

object SequenceStore {
    fun loadAll(read: (String) -> String, names: List<String>): Map<String, Seq> =
        names.associateWith { Seq.parse(read(it)) }
}
