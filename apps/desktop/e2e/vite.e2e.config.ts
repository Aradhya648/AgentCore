import { defineConfig, mergeConfig } from "vite";
import webapp from "../vite.webapp.config";

/**
 * Webapp Vite config for e2e: force `VITE_API_URL` onto the mock backend.
 * Relying only on process.env is brittle on Windows / Playwright webServer;
 * `define` pins the client-visible value regardless of .env.* load order.
 */
const mockUrl =
  process.env.VITE_API_URL?.trim() || "http://127.0.0.1:18000";
const webPort = Number(process.env.E2E_WEB_PORT ?? 5176);

export default mergeConfig(
  webapp,
  defineConfig({
    define: {
      "import.meta.env.VITE_API_URL": JSON.stringify(mockUrl),
    },
    server: {
      host: "127.0.0.1",
      port: webPort,
      strictPort: true,
    },
  }),
);
