import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const base = process.env.TEMP || process.env.TMPDIR || "/tmp";
  return {
    resourcesPath: `${base}/sidecar-spawn-res-${Math.random().toString(36).slice(2)}`,
    isPackaged: true,
  };
});

vi.mock("electron", () => ({
  app: {
    get isPackaged() {
      return h.isPackaged;
    },
    getAppPath: () => "",
    on: vi.fn(),
  },
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
}));

import { resolveSpawnConfig, scrubSocksProxyEnv } from "../sidecar-service";

describe("scrubSocksProxyEnv", () => {
  it("removes socks5(h) proxy vars and keeps http proxies", () => {
    const out = scrubSocksProxyEnv({
      ALL_PROXY: "socks5://127.0.0.1:7890",
      HTTPS_PROXY: "socks5h://127.0.0.1:7890",
      HTTP_PROXY: "http://127.0.0.1:8080",
      PATH: "/usr/bin",
    });
    expect(out.ALL_PROXY).toBeUndefined();
    expect(out.HTTPS_PROXY).toBeUndefined();
    expect(out.HTTP_PROXY).toBe("http://127.0.0.1:8080");
    expect(out.PATH).toBe("/usr/bin");
  });
});

describe("resolveSpawnConfig packaged unix", () => {
  const prevResources = (process as NodeJS.Process & { resourcesPath?: string })
    .resourcesPath;
  const prevOverride = process.env.AGENTCORE_SIDECAR_CMD;
  const prevPlatform = Object.getOwnPropertyDescriptor(process, "platform");

  beforeEach(() => {
    Reflect.deleteProperty(process.env, "AGENTCORE_SIDECAR_CMD");
    h.isPackaged = true;
    (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath =
      h.resourcesPath;
    Object.defineProperty(process, "platform", {
      value: "darwin",
      configurable: true,
    });
    rmSync(h.resourcesPath, { recursive: true, force: true });
  });

  afterEach(() => {
    rmSync(h.resourcesPath, { recursive: true, force: true });
    if (prevResources === undefined) {
      Reflect.deleteProperty(process, "resourcesPath");
    } else {
      (process as NodeJS.Process & { resourcesPath?: string }).resourcesPath =
        prevResources;
    }
    if (prevOverride === undefined) {
      Reflect.deleteProperty(process.env, "AGENTCORE_SIDECAR_CMD");
    } else {
      process.env.AGENTCORE_SIDECAR_CMD = prevOverride;
    }
    if (prevPlatform) {
      Object.defineProperty(process, "platform", prevPlatform);
    }
  });

  it("packaged darwin prefers python3.13 when present", () => {
    const bin = join(h.resourcesPath, "sidecar", "python", "bin");
    mkdirSync(bin, { recursive: true });
    writeFileSync(join(bin, "python3.13"), "");
    writeFileSync(join(bin, "python3"), "");

    const cfg = resolveSpawnConfig();
    expect(cfg.cmd).toBe(join(bin, "python3.13"));
    expect(cfg.args).toEqual(["-m", "agentcore.sidecar"]);
    expect(cfg.env?.PYTHONPATH).toBe(
      join(h.resourcesPath, "sidecar", "site-packages"),
    );
  });

  it("packaged darwin falls back to python3 when python3.13 missing", () => {
    const bin = join(h.resourcesPath, "sidecar", "python", "bin");
    mkdirSync(bin, { recursive: true });
    writeFileSync(join(bin, "python3"), "");

    const cfg = resolveSpawnConfig();
    expect(cfg.cmd).toBe(join(bin, "python3"));
  });
});
