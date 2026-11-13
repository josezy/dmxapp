import looksJson from "../../show/looks.json";
import palettesJson from "../../show/palettes.json";
import type { Json } from "./engine/json";
import { loadCatalog, type ShowCatalog } from "./engine/show";

function byName(modules: Record<string, unknown>): Record<string, Json> {
  const out: Record<string, Json> = {};
  for (const [file, data] of Object.entries(modules)) {
    const name = file.split("/").pop()?.replace(/\.json$/, "");
    if (!name || typeof data !== "object" || data === null) continue;
    out[name] = data as Json;
  }
  return out;
}

const beamMods = import.meta.glob("../../beam-halo-duo/sequences/*.json", {
  eager: true,
  import: "default",
});
const lpcMods = import.meta.glob("../../lpc008-duo/sequences/*.json", {
  eager: true,
  import: "default",
});

export const beamSequences = byName(beamMods);
export const lpcSequences = byName(lpcMods);
export const catalog: ShowCatalog = loadCatalog(looksJson, palettesJson);
