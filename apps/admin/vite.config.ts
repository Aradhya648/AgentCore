import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteClientBuildDefine } from "../../scripts/client-build-info.mjs";
import { viteCspPlugin } from "../../scripts/vite-csp.mjs";

const clientBuildDefine = viteClientBuildDefine(new URL("./package.json", import.meta.url));

// Standalone web console (独立 origin). Dev runs on 5174 so it never clashes with
// the desktop renderer (5173); the backend must allowlist this origin for
// credentialed CORS (see config.cors_allow_origins + README).
export default defineConfig({
  define: clientBuildDefine,
  plugins: [react(), tailwindcss(), viteCspPlugin()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5174,
    strictPort: true,
  },
  // XSS-001: disable Vite's inline modulepreload polyfill so the prod build has NO inline
  // <script>, letting the injected `script-src 'self'` CSP hold without 'unsafe-inline'.
  build: { modulePreload: { polyfill: false } },
});
