import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes into the Python package and is served by the local FastAPI backend.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  build: {
    outDir: fileURLToPath(new URL("../src/interis/web/dist", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 0, // no data: URLs – everything is a plain file
  },
  server: {
    port: 5173,
    strictPort: true,
    // during development the API runs at `interis serve --port 8765`
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
});
