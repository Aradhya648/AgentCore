import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

// Mobile component/unit tests (AUD-012 测试覆盖补强). Separate from vite.config.ts so the
// CSP plugin / build-info define stay out of tests; mirrors apps/desktop/vitest.config.ts
// (node env by default, component tests opt into jsdom via a per-file
// `// @vitest-environment jsdom` directive). `@` → src matches the app alias.
export default defineConfig({
  test: {
    globals: true,
    environment: "node",
  },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
