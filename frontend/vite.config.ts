import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig(({ command }) => ({
  base: command === "serve" ? "/" : "/static/dist/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    outDir: "../app/static/dist",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    proxy: {
      "/static": "http://127.0.0.1:8765",
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("origin", "http://127.0.0.1:8765")
          })
        },
      },
    },
  },
}))
