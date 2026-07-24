import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { resolveApiBaseUrl } from "../../../scripts/resolve-api-base-url";

afterEach(() => {
  // Must delete: assigning `undefined` stringifies to "undefined" in process.env.
  Reflect.deleteProperty(process.env, "VITE_API_URL");
});

function envDirWith(files: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), "agentcore-api-base-"));
  for (const [name, body] of Object.entries(files)) {
    writeFileSync(join(dir, name), body, "utf8");
  }
  return dir;
}

const packageDir = join(dirname(fileURLToPath(import.meta.url)), "../../..");

describe("resolveApiBaseUrl", () => {
  it("production build reads .env.production even when process.env has localhost", () => {
    const dir = envDirWith({
      ".env": "VITE_API_URL=http://localhost:8000\n",
      ".env.production": "VITE_API_URL=https://app.fashitianxia.xyz/api\n",
    });
    process.env.VITE_API_URL = "http://localhost:8000";
    expect(resolveApiBaseUrl("production", "build", dir)).toBe(
      "https://app.fashitianxia.xyz/api",
    );
  });

  it("apps/desktop packageDir production build survives shell localhost", () => {
    process.env.VITE_API_URL = "http://localhost:8000";
    expect(resolveApiBaseUrl("production", "build", packageDir)).toBe(
      "https://app.fashitianxia.xyz/api",
    );
  });

  it("dev serve uses .env localhost", () => {
    const dir = envDirWith({
      ".env": "VITE_API_URL=http://localhost:8000\n",
      ".env.production": "VITE_API_URL=https://app.fashitianxia.xyz/api\n",
    });
    expect(resolveApiBaseUrl("development", "serve", dir)).toBe(
      "http://localhost:8000",
    );
  });

  it("build with non-production mode still forces .env.production", () => {
    const dir = envDirWith({
      ".env": "VITE_API_URL=http://localhost:8000\n",
      ".env.development": "VITE_API_URL=http://localhost:8000\n",
      ".env.production": "VITE_API_URL=https://app.fashitianxia.xyz/api\n",
    });
    expect(resolveApiBaseUrl("development", "build", dir)).toBe(
      "https://app.fashitianxia.xyz/api",
    );
  });
});
