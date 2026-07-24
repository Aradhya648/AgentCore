import { resolve } from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Production web client build/serve of the desktop renderer (P1 多端：web = 「云工作区」
// 一等入口；cross-platform-frontend §7 / 前端技术与架构 §七). The renderer is a normal
// Vite React app; its only Electron coupling is four injected globals, stubbed by the
// web entry (src/renderer/main.webapp.tsx → preview/browserStubs, which also sets
// window.__WEB__ so capability proxies degrade local-only features). Unlike the offline
// preview (vite.web.config.ts → main.web.tsx, which sets __WEB_PREVIEW__ to skip auth),
// this entry keeps real cookie auth against VITE_API_URL.
//
// Dev server runs on 5175 — already in the backend's default CORS allowlist
// (apps/server/agentcore/config/auth.py), so `pnpm dev:webapp` works against a local
// backend with NO backend change. Production must serve same-site with the API for
// SameSite cookies (see apps/server/.env.example CORS note).
export default defineConfig({
  root: resolve("src/renderer"),
  publicDir: resolve("public"),
  // envDir defaults to `root`; without this, apps/desktop/.env.production is never
  // loaded and VITE_API_URL falls back to localhost:8000 → the deployed web client
  // can't reach the backend ("后端不可用"). Point it at the package root where the
  // .env.production (and .env.production.local override) actually live.
  envDir: resolve("."),
  resolve: {
    alias: {
      "@": resolve("src/renderer"),
      "@shared": resolve("src/shared"),
    },
  },
  server: {
    port: 5175,
  },
  build: {
    // MUST stay outside electron-vite `out/` — electron-builder packs `out/**` into
    // the installer (electron-builder.yml `files`), same constraint as shoot-out/.
    outDir: resolve("dist-web"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve("src/renderer/index.webapp.html"),
    },
  },
  plugins: [react()],
});
