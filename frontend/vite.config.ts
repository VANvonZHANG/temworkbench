import { fileURLToPath } from "node:url"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

const backend = process.env.TEMWORKBENCH_DEV_BACKEND ?? "http://127.0.0.1:8765"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { proxy: { "/api": { target: backend, ws: true } } },
  build: {
    assetsDir: "workbench-assets",
    outDir: "../src/temworkbench/web",
    emptyOutDir: true,
    license: { fileName: "workbench-assets/dependencies-LICENSE.md" },
  },
})
