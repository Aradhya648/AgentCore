/**
 * DesktopBrowserBridge（L8）——本机 loopback HTTP + 主进程签发短时 token。
 *
 * 仅绑定 127.0.0.1；无 Bearer token / 过期 / 错 token → 401。
 * 动作：`GET /health`、`POST /navigate`、`POST /command`（六动作对齐 browser_*）。
 * Local live 帧：server Hub attach 后周期 POST screenshot（frame_b64+width+height）。
 * 鉴权/handler 纯逻辑见 bridge-handler.ts（可单测）。
 *
 * Sidecar 探测：主进程在 initialize / startTurn / resume 下发 ``browserBridge``
 *（与 inference 同构，见 sidecar-service ``currentBrowserBridge``）；server 侧
 * ``apply_desktop_bridge_from_turn`` + ``desktop_bridge_health`` 探活。
 * 未打包开发态仍可写入 userData ``browser-bridge.dev.json`` 供外部 probe 脚本。
 */

import { writeFileSync, unlinkSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { join } from "node:path";
import { app } from "electron";
import {
  createBridgeAuth,
  handleBridgeRequest,
} from "./bridge-handler";
import { bridgeDispatchLocalBrowser } from "./host";

export {
  createBridgeAuth,
  handleBridgeRequest,
  BRIDGE_ACTIONS,
} from "./bridge-handler";
export type {
  BridgeAction,
  BridgeDispatch,
  BridgeHostResult,
} from "./bridge-handler";

export interface DesktopBrowserBridge {
  /** 例：http://127.0.0.1:51234 */
  baseUrl: string;
  /** 当前有效 token（主进程签发；勿入 renderer）。 */
  token: string;
  close: () => Promise<void>;
  /** 轮换 token（sidecar 重连时可调）。 */
  rotateToken: () => string;
}

let running: {
  server: Server;
  auth: ReturnType<typeof createBridgeAuth>;
  port: number;
} | null = null;

const DEV_BRIDGE_FILE = "browser-bridge.dev.json";
/** 打包版短 TTL；未打包 dogfood / probe 用长 TTL，避免 dump 文件几分钟就 401。 */
const BRIDGE_TOKEN_TTL_MS = app.isPackaged ? 5 * 60_000 : 60 * 60_000;

/** 未打包时落盘凭证，供本机 sidecar probe；打包版 / 未就绪 → no-op。 */
function dumpDevBridgeCredentials(baseUrl: string, token: string): void {
  if (app.isPackaged) return;
  try {
    const path = join(app.getPath("userData"), DEV_BRIDGE_FILE);
    writeFileSync(
      path,
      JSON.stringify({ baseUrl, token, writtenAt: new Date().toISOString() }, null, 2),
      { encoding: "utf-8", mode: 0o600 },
    );
  } catch (err) {
    console.warn("[browser-bridge] dev credential dump failed:", err);
  }
}

function clearDevBridgeCredentials(): void {
  if (app.isPackaged) return;
  try {
    unlinkSync(join(app.getPath("userData"), DEV_BRIDGE_FILE));
  } catch {
    /* missing ok */
  }
}

/**
 * 启动 Bridge（127.0.0.1 随机端口）。幂等：已启动则轮换 token 并返回现 endpoint。
 */
export async function startDesktopBrowserBridge(): Promise<DesktopBrowserBridge> {
  if (running) {
    const token = running.auth.issueToken(BRIDGE_TOKEN_TTL_MS);
    const baseUrl = `http://127.0.0.1:${running.port}`;
    dumpDevBridgeCredentials(baseUrl, token);
    return {
      baseUrl,
      token,
      close: stopDesktopBrowserBridge,
      rotateToken: () => {
        const t = running!.auth.issueToken(BRIDGE_TOKEN_TTL_MS);
        dumpDevBridgeCredentials(`http://127.0.0.1:${running!.port}`, t);
        return t;
      },
    };
  }

  const auth = createBridgeAuth();
  const token = auth.issueToken(BRIDGE_TOKEN_TTL_MS);

  const server = createServer((req, res) => {
    void handleBridgeRequest(
      req,
      res,
      (t) => auth.validateToken(t),
      bridgeDispatchLocalBrowser,
    );
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });

  const addr = server.address();
  if (!addr || typeof addr === "string") {
    server.close();
    throw new Error("DesktopBrowserBridge: failed to bind loopback");
  }

  running = { server, auth, port: addr.port };
  const baseUrl = `http://127.0.0.1:${addr.port}`;
  dumpDevBridgeCredentials(baseUrl, token);
  console.info(
    `[browser-bridge] listening on ${baseUrl} (token issued)`,
  );

  return {
    baseUrl,
    token,
    close: stopDesktopBrowserBridge,
    rotateToken: () => {
      const t = running!.auth.issueToken(BRIDGE_TOKEN_TTL_MS);
      dumpDevBridgeCredentials(baseUrl, t);
      return t;
    },
  };
}

export async function stopDesktopBrowserBridge(): Promise<void> {
  if (!running) return;
  const { server } = running;
  running = null;
  clearDevBridgeCredentials();
  await new Promise<void>((resolve) => {
    server.close(() => resolve());
  });
}

/** 测试 / 诊断：当前 Bridge 是否在跑（不含 token）。 */
export function getDesktopBrowserBridgeInfo(): {
  baseUrl: string;
  hasToken: boolean;
} | null {
  if (!running) return null;
  return {
    baseUrl: `http://127.0.0.1:${running.port}`,
    hasToken: Boolean(running.auth.state.token),
  };
}

/**
 * 主进程专用：给 sidecar spawn 注入的 URL+token（勿经 preload / renderer）。
 * 若 Bridge 未启则返回 null。
 */
export function getDesktopBrowserBridgeCredentials(): {
  baseUrl: string;
  token: string;
} | null {
  if (!running || !running.auth.state.token) return null;
  // 过期则轮换，避免 sidecar 拿到已失效 token。
  if (Date.now() >= running.auth.state.expiresAt) {
    running.auth.issueToken(BRIDGE_TOKEN_TTL_MS);
  }
  const out = {
    baseUrl: `http://127.0.0.1:${running.port}`,
    token: running.auth.state.token!,
  };
  dumpDevBridgeCredentials(out.baseUrl, out.token);
  return out;
}

/** Sidecar 重连：轮换 token 并返回新凭证。 */
export function rotateDesktopBrowserBridgeCredentials(): {
  baseUrl: string;
  token: string;
} | null {
  if (!running) return null;
  const token = running.auth.issueToken(BRIDGE_TOKEN_TTL_MS);
  const out = {
    baseUrl: `http://127.0.0.1:${running.port}`,
    token,
  };
  dumpDevBridgeCredentials(out.baseUrl, out.token);
  return out;
}
