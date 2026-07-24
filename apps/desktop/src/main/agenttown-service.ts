import { spawn } from "node:child_process";
import { constants } from "node:fs";
import { access } from "node:fs/promises";
import { mkdir, readFile, unlink, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import {
  AGENTTOWN_CHANNELS,
  type AgentTownLaunchResult,
  type AgentTownSessionFile,
  type WriteSessionInput,
  type WriteSessionResult,
} from "@shared/agenttown-contract";
import { app, ipcMain, session } from "electron";
import { isRecord } from "./ipc-validate";

const ACCESS_COOKIE = "access_token";
const REFRESH_COOKIE = "refresh_token";

declare const __API_BASE_URL__: string;

function defaultApiBase(): string {
  try {
    return new URL(__API_BASE_URL__).origin;
  } catch {
    return "http://localhost:8000";
  }
}

function sessionFilePath(): string {
  return join(app.getPath("appData"), "AgentCore", "session.json");
}

function jwtExpiresAtIso(token: string): string | undefined {
  try {
    const segment = token.split(".")[1];
    if (!segment) return undefined;
    const padded = segment.replace(/-/g, "+").replace(/_/g, "/");
    const json = JSON.parse(
      Buffer.from(padded, "base64").toString("utf-8"),
    ) as { exp?: number };
    if (typeof json.exp === "number" && Number.isFinite(json.exp)) {
      return new Date(json.exp * 1000).toISOString();
    }
  } catch {
    /* non-JWT or malformed — optional field stays absent */
  }
  return undefined;
}

async function readAuthCookies(): Promise<{
  access_token?: string;
  refresh_token?: string;
}> {
  const all = await session.defaultSession.cookies.get({});
  const access = all.find((c) => c.name === ACCESS_COOKIE)?.value;
  const refresh = all.find((c) => c.name === REFRESH_COOKIE)?.value;
  return { access_token: access, refresh_token: refresh };
}

async function pathExists(filePath: string): Promise<boolean> {
  try {
    await access(filePath, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function agentTownExeName(): string {
  if (process.platform === "win32") return "AgentTown.exe";
  if (process.platform === "darwin") return "AgentTown";
  return "AgentTown";
}

/**
 * §10 路径发现：AGENTTOWN_PATH → 同目录（打包）→ 仓库 Builds（开发）→
 * Program Files/AgentCore/AgentTown/
 */
export function agentTownCandidatePaths(): string[] {
  const exeName = agentTownExeName();
  const candidates: string[] = [];

  const envPath = process.env.AGENTTOWN_PATH?.trim();
  if (envPath) {
    candidates.push(
      envPath.toLowerCase().endsWith(".exe") || envPath.endsWith("AgentTown")
        ? envPath
        : join(envPath, exeName),
    );
  }

  if (app.isPackaged) {
    candidates.push(join(dirname(process.execPath), exeName));
  } else {
    // Dev: apps/desktop → ../town/Builds/Windows/AgentTown.exe
    candidates.push(
      join(app.getAppPath(), "..", "town", "Builds", "Windows", exeName),
    );
  }

  const programFiles =
    process.env.ProgramFiles ??
    (process.platform === "win32" ? "C:\\Program Files" : "");
  if (programFiles) {
    candidates.push(join(programFiles, "AgentCore", "AgentTown", exeName));
  }

  return candidates;
}

export async function resolveAgentTownExe(): Promise<string | null> {
  for (const candidate of agentTownCandidatePaths()) {
    if (await pathExists(candidate)) return candidate;
  }
  return null;
}

export async function writeSessionFile(
  input: WriteSessionInput,
): Promise<WriteSessionResult> {
  const api_base = input.api_base?.trim();
  if (!api_base) {
    return {
      ok: false,
      reason: "invalid_args",
      message: "缺少 api_base",
    };
  }

  let access_token = input.access_token?.trim();
  let refresh_token = input.refresh_token?.trim();

  if (!access_token) {
    const cookies = await readAuthCookies();
    access_token = cookies.access_token;
    refresh_token = refresh_token ?? cookies.refresh_token;
  }

  if (!access_token) {
    return {
      ok: false,
      reason: "missing_token",
      message: "未找到 access_token（请先登录）",
    };
  }

  const payload: AgentTownSessionFile = {
    api_base,
    access_token,
  };
  if (refresh_token) payload.refresh_token = refresh_token;
  const expires_at = input.expires_at ?? jwtExpiresAtIso(access_token);
  if (expires_at) payload.expires_at = expires_at;

  const filePath = sessionFilePath();
  try {
    await mkdir(dirname(filePath), { recursive: true });
    await writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
    return { ok: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      ok: false,
      reason: "write_failed",
      message: `写入 session.json 失败：${message}`,
    };
  }
}

export async function clearSessionFile(): Promise<void> {
  try {
    await unlink(sessionFilePath());
  } catch {
    /* absent file is fine */
  }
}

export async function launchAgentTown(opts?: {
  runId?: string;
}): Promise<AgentTownLaunchResult> {
  const candidates = agentTownCandidatePaths();
  const exePath = await resolveAgentTownExe();
  if (!exePath) {
    const listed = candidates.map((p) => `  · ${p}`).join("\n");
    const hint = app.isPackaged
      ? "请安装 AgentTown 独立客户端，或设置 AGENTTOWN_PATH 指向可执行文件。"
      : "开发期请先在仓库根目录执行 pnpm town:build，生成 apps/town/Builds/Windows/AgentTown.exe；或设置 AGENTTOWN_PATH。";
    return {
      ok: false,
      reason: "not_found",
      candidates,
      message: `未找到 AgentTown。\n${hint}\n已检查路径：\n${listed}`,
    };
  }

  let sessionData: AgentTownSessionFile | null = null;
  try {
    const raw = await readFile(sessionFilePath(), "utf-8");
    sessionData = JSON.parse(raw) as AgentTownSessionFile;
  } catch {
    sessionData = null;
  }

  const apiBase = sessionData?.api_base?.trim() || defaultApiBase();
  const token = sessionData?.access_token?.trim();
  if (!token) {
    const cookies = await readAuthCookies();
    if (!cookies.access_token) {
      return {
        ok: false,
        reason: "missing_token",
        message: "未找到登录凭据，请先在 Desktop 登录。",
      };
    }
    const wrote = await writeSessionFile({ api_base: apiBase });
    if (!wrote.ok) {
      return {
        ok: false,
        reason:
          wrote.reason === "missing_token"
            ? "missing_token"
            : wrote.reason === "invalid_args"
              ? "invalid_args"
              : "spawn_failed",
        message: wrote.message,
      };
    }
    const reread = await readFile(sessionFilePath(), "utf-8");
    sessionData = JSON.parse(reread) as AgentTownSessionFile;
  }

  const accessToken = sessionData?.access_token?.trim();
  if (!accessToken) {
    return {
      ok: false,
      reason: "missing_token",
      message: "未找到 access_token",
    };
  }

  const args = ["--api", apiBase, "--token", accessToken];
  const runId = opts?.runId?.trim();
  if (runId) args.push("--run-id", runId);

  return new Promise((resolve) => {
    try {
      const child = spawn(exePath, args, {
        detached: true,
        stdio: "ignore",
        windowsHide: true,
      });
      child.on("error", (err) => {
        resolve({
          ok: false,
          reason: "spawn_failed",
          message: `启动 AgentTown 失败：${err.message}`,
        });
      });
      child.on("spawn", () => {
        child.unref();
        resolve({ ok: true });
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      resolve({
        ok: false,
        reason: "spawn_failed",
        message: `启动 AgentTown 失败：${message}`,
      });
    }
  });
}

export function registerAgentTownIpc(): void {
  ipcMain.handle(AGENTTOWN_CHANNELS.writeSession, async (_e, payload) => {
    if (!isRecord(payload) || typeof payload.api_base !== "string") {
      return {
        ok: false,
        reason: "invalid_args",
        message: "无效的请求参数",
      } satisfies WriteSessionResult;
    }
    const input: WriteSessionInput = { api_base: payload.api_base };
    if (typeof payload.access_token === "string") {
      input.access_token = payload.access_token;
    }
    if (typeof payload.refresh_token === "string") {
      input.refresh_token = payload.refresh_token;
    }
    if (typeof payload.expires_at === "string") {
      input.expires_at = payload.expires_at;
    }
    return writeSessionFile(input);
  });

  ipcMain.handle(AGENTTOWN_CHANNELS.clearSession, async () => {
    await clearSessionFile();
  });

  ipcMain.handle(AGENTTOWN_CHANNELS.launch, async (_e, payload) => {
    const runId =
      payload != null && isRecord(payload) && typeof payload.runId === "string"
        ? payload.runId
        : undefined;
    if (payload != null && !isRecord(payload) && payload !== undefined) {
      return {
        ok: false,
        reason: "invalid_args",
        message: "无效的请求参数",
      } satisfies AgentTownLaunchResult;
    }
    if (
      payload != null &&
      isRecord(payload) &&
      payload.runId != null &&
      typeof payload.runId !== "string"
    ) {
      return {
        ok: false,
        reason: "invalid_args",
        message: "无效的请求参数",
      } satisfies AgentTownLaunchResult;
    }
    return launchAgentTown({ runId });
  });
}
