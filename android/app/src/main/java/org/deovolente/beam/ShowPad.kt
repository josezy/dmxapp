package org.deovolente.beam

import org.json.JSONObject

data class SceneButton(val name: String, val label: String)

data class SceneGroup(val title: String, val scenes: List<SceneButton>)

data class ShowPad(val subtitle: String, val groups: List<SceneGroup>) {
    val knownScenes: Set<String> = groups.flatMap { g -> g.scenes.map { it.name } }.toSet()

    companion object {
        fun parse(text: String): ShowPad {
            val root = JSONObject(text)
            val groupsJson = root.getJSONArray("groups")
            val groups =
                buildList {
                    for (i in 0 until groupsJson.length()) {
                        val g = groupsJson.getJSONObject(i)
                        val scenesJson = g.getJSONArray("scenes")
                        val scenes =
                            buildList {
                                for (j in 0 until scenesJson.length()) {
                                    val s = scenesJson.getJSONObject(j)
                                    add(SceneButton(s.getString("name"), s.getString("label")))
                                }
                            }
                        add(SceneGroup(g.getString("title"), scenes))
                    }
                }
            return ShowPad(root.optString("subtitle"), groups)
        }
    }
}
