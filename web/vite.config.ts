import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const root = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  server: {
    fs: {
      allow: [path.resolve(root, "..")],
    },
  },
  test: {
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
