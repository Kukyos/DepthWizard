import { defineConfig } from "vite";

// Relative base so the built viewer works both from a web server and from file://
// inside the Electron shell, with no rewrite step. Hard rule 6: fully offline.
export default defineConfig({
  base: "./",
  server: { port: 5173, strictPort: true },
  build: {
    outDir: "dist",
    target: "es2022",
    // Babylon is large, so raise the warning threshold rather than hand-splitting chunks.
    // Tree-shaken side-effect imports already keep this well under a megabyte, and the
    // app loads from disk in the Electron build where chunking buys nothing.
    chunkSizeWarningLimit: 2000,
  },
});
