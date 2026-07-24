/// <reference path="../../scripts/client-build-info.d.ts" />
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteClientBuildDefine } from "../../scripts/client-build-info.mjs";
import { viteCspPlugin } from "../../scripts/vite-csp.mjs";

const clientBuildDefine = viteClientBuildDefine(new URL("./package.json", import.meta.url));

// Mobile-web dev server runs on 5175. Dev API calls go same-origin through `/api/*`
// (proxy → localhost:8000) so LAN phones need zero per-IP CORS / VITE_API_URL hacks;
// prod/staging still bake an absolute VITE_API_URL (see client.ts). SPA history fallback
// is built into the Vite dev server; the Capacitor shell serves the built SPA directly.
export default defineConfig({
  define: clientBuildDefine,
  plugins: [react(), viteCspPlugin()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5175,
    // Expose on the LAN so a phone can open http://<host-ip>:5175/ (dev topology §本地开发).
    host: true,
    proxy: {
      // Mirrors prod Nginx: /api/v1/... → backend /v1/... (SSE: no buffering).
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  // XSS-001: disable Vite's inline modulepreload polyfill so the prod build has NO inline
  // <script>, letting the injected `script-src 'self'` CSP hold without 'unsafe-inline'.
  build: { modulePreload: { polyfill: false } },
});
