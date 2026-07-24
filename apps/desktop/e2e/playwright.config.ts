import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Playwright loads this config as CJS; prefer __dirname over import.meta.
const desktopRoot = path.join(__dirname, "..");
const MOCK_PORT = Number(process.env.E2E_MOCK_PORT ?? 18000);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5176);
const MOCK_URL = `http://127.0.0.1:${MOCK_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;

export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [
    ["list"],
    [
      "html",
      { open: "never", outputFolder: path.join(desktopRoot, "e2e-report") },
    ],
  ],
  outputDir: path.join(desktopRoot, "e2e-results"),
  use: {
    // Origin only — specs navigate to /index.webapp.html (webapp shell, not electron index).
    baseURL: WEB_URL,
    ...devices["Desktop Chrome"],
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
    locale: "zh-CN",
  },
  webServer: [
    {
      command: "pnpm exec tsx e2e/mock/server.ts",
      cwd: desktopRoot,
      url: `${MOCK_URL}/readyz`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        ...process.env,
        E2E_MOCK_PORT: String(MOCK_PORT),
      },
    },
    {
      command: "pnpm exec vite --config e2e/vite.e2e.config.ts",
      cwd: desktopRoot,
      url: `${WEB_URL}/index.webapp.html`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ...process.env,
        VITE_API_URL: MOCK_URL,
        E2E_WEB_PORT: String(WEB_PORT),
        VITE_DEV_USERNAME: "",
        VITE_DEV_PASSWORD: "",
      },
    },
  ],
});
