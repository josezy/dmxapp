import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const needed = [
  "show/looks.json",
  "show/palettes.json",
  "beam-halo-duo/sequences/golpe-blanco.json",
  "lpc008-duo/sequences/breathe-calida.json",
];

const missing = needed.filter((rel) => !existsSync(path.join(root, rel)));
if (missing.length) {
  console.error(
    [
      "Faltan los JSON del show junto a la carpeta web/:",
      ...missing.map((rel) => `  ${rel}`),
      "",
      "En Vercel: Root Directory = web, y activa",
      '"Include source files outside of the Root Directory in the Build Step".',
      "Esos archivos viven en el repo, no dentro de web/.",
    ].join("\n"),
  );
  process.exit(1);
}
