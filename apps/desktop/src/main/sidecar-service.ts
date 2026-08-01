import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import {
  SIDECAR_CHANNELS,
  type SidecarAttachRequest,
  type SidecarAttachResponse,
  type SidecarCancelRequest,
  type SidecarDebateSteerRequest,
  type SidecarInference,
  type SidecarListBrowserSessionsRequest,
  type SidecarListBrowserSessionsResult,
  type SidecarPausedTurn,
  type SidecarProbeRequest,
  type SidecarRecoveryRequest,
  type SidecarRecoveryResponse,
  type SidecarRespondRequest,
  type SidecarRestoreTurnBaselineRequest,
  type SidecarResumeRequest,
  type SidecarRunRedirectRequest,
  type SidecarStartTurnRequest,
  type SidecarStatusPush,
  type SidecarTurnFilesDiffRequest,
  type SidecarTurnFilesDiffResult,
  type SidecarTurnResult,
  buildSidecarResumeRpcParams,
} from "@shared/sidecar-contract";
import { BrowserWindow, type WebContents, app, ipcMain } from "electron";
import { getDesktopBrowserBridgeCredentials } from "./browser";
import { getStoredRoot } from "./fs-service";
import { listSessionRoots } from "./fs/roots";
import {
  IpcInvalidArgsError,
  assertShape,
  ipcInvalidArgsLogFields,
} from "./ipc-validate";
import { logDesktop } from "./log-service";
import { listUnsyncedSummaries, sidecarDataDir } from "./outbox-writeback";
import { SidecarEventBuffer } from "./sidecar-event-buffer";

// 本地回合的审批门（双模式工作区 / 远期规划 §一）。开启后，sidecar 引擎对 worker 的「碰真实
// 机器」工具（file_write / code_execute 等 GRANTABLE）挂起审批，与云端 local 模式同语义——
// 审批请求随回合事件流回 renderer，用户的决定经 `window.sidecarApi.respond` 结算回这条 stdio
// 链路（renderer 把统一结算入口 `resolveInteraction` 在本地回合改走 sidecar）。
const SIDECAR_APPROVALS_ENABLED = true;

// sidecar 的本机数据目录（app 私有）：持久挂起帧落 `<dataDir>/paused/<message_id>.json`，
// 渐进 outbox 落 `<dataDir>/outbox/`，录制（DEMO_TAPE_RECORD_ENABLED）落 `<dataDir>/recordings/`
// （D8 分处理器，同目录根）。主进程在 initialize 时下发 dataDir。

/**
 * 直接读本机帧文件，列出某会话待续跑的持久挂起帧（不拉起 sidecar 进程）。
 *
 * 续跑帧由 Python `LocalPausedTurnStore` 落在 `<dataDir>/paused/*.json`，每条记录含顶层
 * `conversation_id` / `created_at` 与已投影好的 `summary`（= 服务端 `PausedTurnSummary` 形状）。
 * 这里只读这几个顶层字段、按会话过滤、按时间排序，返回 `summary` 原样——与 Python 的
 * `listPaused` RPC 同源（summary 在落盘时算好存入），但读列表这一步无需引擎在跑。
 * 经 `recovery` IPC 的 `paused[]` 返回（原独立 listPaused 通道已退役）。
 * 尽力而为：任何读/解析失败都降级为「无待续跑」，绝不阻塞重开会话。
 */
async function readLocalPausedSummaries(
  conversationId: string,
): Promise<SidecarPausedTurn[]> {
  const dir = join(sidecarDataDir(), "paused");
  let names: string[];
  try {
    names = await readdir(dir);
  } catch {
    return []; // 目录还不存在（从未挂起过）——无待续跑
  }
  const records: { createdAt: number; summary: SidecarPausedTurn }[] = [];
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    try {
      const raw = await readFile(join(dir, name), "utf-8");
      const record = JSON.parse(raw) as {
        conversation_id?: string;
        created_at?: number;
        summary?: SidecarPausedTurn;
      };
      if (record.conversation_id !== conversationId || !record.summary)
        continue;
      records.push({
        createdAt: record.created_at ?? 0,
        summary: record.summary,
      });
    } catch {
      // 撕裂 / 非法帧——跳过这一条，不让它拖垮整次列举
    }
  }
  records.sort((a, b) => a.createdAt - b.createdAt); // oldest-first，与云端一致
  return records.map((r) => r.summary);
}

// --- 传输层（与 child_process 解耦，便于单测）---

/** sidecar 进程的双向行管道：发一行、收一行、感知断开、关闭。 */
export interface Transport {
  /** 写一行（已含结尾 `\n`）到子进程 stdin。 */
  send(line: string): void;
  /** 注册「收到一整行 stdout」回调（行内不含结尾 `\n`）。 */
  onLine(cb: (line: string) => void): void;
  /** 注册「进程退出 / 出错」回调（err 为退出原因，正常退出可为 undefined）。 */
  onClose(cb: (err?: Error) => void): void;
  /** 终止进程。 */
  close(): void;
}

interface SpawnConfig {
  cmd: string;
  args: string[];
  cwd: string;
  /** 额外环境变量，合并覆盖继承的环境（如内置运行时旁路 site-packages 的 `PYTHONPATH`）。 */
  env?: Record<string, string>;
}

/**
 * DesktopBrowserBridge 本回合句柄（B-Arch · 与 inference 同构）。
 * 主进程签发；经 initialize / startTurn / resume 下发，不再依赖 spawn env。
 */
function currentBrowserBridge(): { baseUrl: string; token: string } | null {
  const creds = getDesktopBrowserBridgeCredentials();
  if (!creds) return null;
  return { baseUrl: creds.baseUrl, token: creds.token };
}

/**
 * 解析拉起 sidecar 的命令。
 *
 * **打包态**（`app.isPackaged`）走**内置 Python 运行时**（远期规划 §一.1「内置 Python 打包」
 * 方案 B）：随包带一份独立 CPython 发行版 + `--target` 装好的 site-packages（构建见
 * `scripts/bundle-sidecar.mjs`），由 electron-builder `extraResources` 拷到
 * `process.resourcesPath/sidecar`。用户机器**无需任何系统 Python / venv / uv**；引擎包不在
 * 解释器自带 site-packages、而在旁路目录，故经 `PYTHONPATH` 注入（免 venv 重定位之痛）。
 *
 * **dev 态**（未打包）保持原行为：服务端 venv 的 python > `uv run python`。`AGENTCORE_SIDECAR_CMD`
 * 覆写**始终最高优先**（即便已打包），便于对一个打包后的应用临时指向自定义解释器联调。
 * 服务端目录默认取 `AGENTCORE_SERVER_DIR`，否则按 app 路径推 `../server`（dev 下 appPath =
 * apps/desktop）。
 *
 * @internal 导出供单测；生产路径经 SidecarManager → spawnFn。
 */
export function resolveSpawnConfig(): SpawnConfig {
  const serverDir =
    process.env.AGENTCORE_SERVER_DIR ?? join(app.getAppPath(), "..", "server");

  const cmdOverride = process.env.AGENTCORE_SIDECAR_CMD;
  if (cmdOverride) {
    const args = (process.env.AGENTCORE_SIDECAR_ARGS ?? "-m agentcore.sidecar")
      .split(" ")
      .filter(Boolean);
    return { cmd: cmdOverride, args, cwd: serverDir };
  }

  // 打包态：内置 Python 运行时（方案 B）。
  if (app.isPackaged) {
    const base = join(process.resourcesPath, "sidecar");
    // unix：优先版本化二进制（与 bundle-sidecar.mjs 的 PYTHON_VERSION=3.13 对齐），
    // 避免依赖可能仍是坏绝对 symlink 的 python3（历史包曾指向 CI 的 uv 缓存路径）。
    const python =
      process.platform === "win32"
        ? join(base, "python", "python.exe")
        : (() => {
            const versioned = join(base, "python", "bin", "python3.13");
            if (existsSync(versioned)) return versioned;
            return join(base, "python", "bin", "python3");
          })();
    return {
      cmd: python,
      args: ["-m", "agentcore.sidecar"],
      cwd: base,
      env: {
        PYTHONPATH: join(base, "site-packages"),
        AGENTCORE_RG_PATH: join(
          process.resourcesPath,
          "rg",
          process.platform === "win32" ? "rg.exe" : "rg",
        ),
      },
    };
  }

  // dev：服务端 venv 的 python（最稳，免 uv 的 PATH 问题）。
  const venvPython =
    process.platform === "win32"
      ? join(serverDir, ".venv", "Scripts", "python.exe")
      : join(serverDir, ".venv", "bin", "python");
  const rgDev = join(
    serverDir,
    "bin",
    process.platform === "win32" ? "rg.exe" : "rg",
  );
  const rgEnv = existsSync(rgDev) ? { AGENTCORE_RG_PATH: rgDev } : undefined;
  if (existsSync(venvPython)) {
    return {
      cmd: venvPython,
      args: ["-m", "agentcore.sidecar"],
      cwd: serverDir,
      env: rgEnv,
    };
  }
  // 回退：让 uv 解析环境（需 uv 在 PATH）。
  return {
    cmd: "uv",
    args: ["run", "python", "-m", "agentcore.sidecar"],
    cwd: serverDir,
    env: rgEnv,
  };
}

/** 真实传输：spawn 子进程，把 stdout 按行切分，stderr 透传到主进程控制台（dev 可见）。 */

/** 从累积的 stderr 提取用户可见的失败原因（优先 Python ImportError / 末行异常）。 */
export function formatSidecarExitError(
  code: number | null,
  stderr: string,
): Error {
  const trimmed = stderr.trim();
  if (trimmed) {
    const importErr = trimmed.match(/^ImportError:\s*(.+)$/m);
    if (importErr) {
      return new Error(`sidecar 启动失败：${importErr[1].trim()}`);
    }
    const lines = trimmed
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i];
      if (!line) continue;
      if (/^(?:\w+Error|\w+Exception):\s*.+/.test(line)) {
        return new Error(`sidecar 启动失败：${line}`);
      }
    }
  }
  if (code) {
    return new Error(`sidecar 进程退出（code ${code}）`);
  }
  return new Error("sidecar 进程已退出");
}

/** Strip SOCKS proxy env so sidecar httpx does not require optional ``socksio``.
 *
 * Desktop inherits the user shell env (Clash/V2Ray often set ``ALL_PROXY=socks5://…``).
 * Product egress uses ``trust_env=False``; scrubbing here is defense-in-depth for any
 * library that still reads proxy env. HTTP(S) proxies are left intact.
 */
export function scrubSocksProxyEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  const out: NodeJS.ProcessEnv = { ...env };
  const keys = [
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
  ] as const;
  for (const key of keys) {
    const raw = out[key];
    if (typeof raw === "string" && /^socks5h?:\/\//i.test(raw.trim())) {
      delete out[key];
    }
  }
  return out;
}

function spawnTransport(config: SpawnConfig): Transport {
  const child = spawn(config.cmd, config.args, {
    cwd: config.cwd,
    env: scrubSocksProxyEnv({
      ...process.env,
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
      ...config.env,
      // Bridge creds are per-turn via RPC (currentBrowserBridge), not spawn env.
    }),
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stdin.setDefaultEncoding("utf-8");
  child.stdout.setEncoding("utf-8");
  child.stderr.setEncoding("utf-8");

  let lineCb: ((line: string) => void) | null = null;
  let closeCb: ((err?: Error) => void) | null = null;
  let buffer = "";
  let stderrBuf = "";

  child.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    let idx = buffer.indexOf("\n");
    while (idx >= 0) {
      const line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line.trim()) lineCb?.(line);
      idx = buffer.indexOf("\n");
    }
  });
  // sidecar 的日志（structlog）走 stderr——透传到主进程控制台，便于 dev 排查。
  child.stderr.on("data", (chunk: string) => {
    stderrBuf += chunk;
    for (const l of chunk.split("\n")) {
      if (l.trim()) console.error(`[sidecar] ${l}`);
    }
  });
  child.on("error", (err) => closeCb?.(err));
  child.on("close", (code) =>
    closeCb?.(code ? formatSidecarExitError(code, stderrBuf) : undefined),
  );

  return {
    send: (line) => {
      child.stdin.write(line);
    },
    onLine: (cb) => {
      lineCb = cb;
    },
    onClose: (cb) => {
      closeCb = cb;
    },
    close: () => {
      child.kill();
    },
  };
}

// --- JSON-RPC 客户端 ---

/** 一个 JSON-RPC 错误响应（携带服务端的 code/message）。 */
export class SidecarRpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
    this.name = "SidecarRpcError";
  }
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
}

/**
 * stdio JSON-RPC 客户端（行分帧）。与 Python 端 `agentcore/sidecar/protocol.py` 对齐：
 * 一行一个 JSON，紧凑序列化 + `\n` 结尾。请求按 id 配对；服务端只回响应与通知
 * （无服务端→客户端请求），故通知统一交给 `onNotification`。
 */
export class SidecarClient {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private notify: (method: string, params: Record<string, unknown>) => void =
    () => {};
  private closed = false;
  private closeErr: Error | null = null;
  private onClosedCb: ((err: Error) => void) | null = null;

  constructor(private readonly transport: Transport) {
    transport.onLine((line) => this.onLine(line));
    transport.onClose((err) => this.onClose(err));
  }

  /** 注册通知处理器（如 `turn/event`）。 */
  onNotification(
    cb: (method: string, params: Record<string, unknown>) => void,
  ): void {
    this.notify = cb;
  }

  /** 注册「连接关闭」回调（进程退出 / 出错）；用于上层逐出缓存并提示。 */
  onClosed(cb: (err: Error) => void): void {
    this.onClosedCb = cb;
  }

  /** 发一个请求，Promise 在收到对应响应时 settle（错误响应 → reject `SidecarRpcError`）。 */
  request(method: string, params: Record<string, unknown>): Promise<unknown> {
    if (this.closed) {
      return Promise.reject(this.closeErr ?? new Error("sidecar 已关闭"));
    }
    const id = this.nextId++;
    const line = `${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`;
    return new Promise<unknown>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.transport.send(line);
      } catch (e) {
        this.pending.delete(id);
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
  }

  dispose(): void {
    this.transport.close();
  }

  private onLine(line: string): void {
    let msg: Record<string, unknown>;
    try {
      const parsed = JSON.parse(line);
      if (typeof parsed !== "object" || parsed === null) return;
      msg = parsed as Record<string, unknown>;
    } catch {
      return; // 非法行——丢弃（日志走 stderr，不会混进这条通道）
    }

    const id = msg.id;
    if (typeof id === "number" && ("result" in msg || "error" in msg)) {
      const p = this.pending.get(id);
      if (!p) return;
      this.pending.delete(id);
      if ("error" in msg) {
        const err = msg.error as
          | { code?: number; message?: string }
          | undefined;
        p.reject(
          new SidecarRpcError(err?.code ?? -1, err?.message ?? "sidecar 错误"),
        );
      } else {
        p.resolve(msg.result);
      }
      return;
    }

    if (typeof msg.method === "string") {
      this.notify(msg.method, (msg.params as Record<string, unknown>) ?? {});
    }
  }

  private onClose(err?: Error): void {
    this.closed = true;
    this.closeErr = err ?? new Error("sidecar 进程已退出");
    for (const [, p] of this.pending) p.reject(this.closeErr);
    this.pending.clear();
    this.onClosedCb?.(this.closeErr);
  }
}

// --- 管理器 ---

interface SidecarEntry {
  client: SidecarClient;
  /** initialize 的就绪 Promise（失败则该 entry 已被逐出，需重拉）。 */
  ready: Promise<void>;
}

interface ActiveTurn {
  wc: WebContents;
  conversationId: string;
  rootId: string;
  subpath: string;
  kind: "start" | "resume";
  traceId: string;
  /** startTurn：用户行 id；resume：挂起时落库的 user 行 id（可缺省）。 */
  userMessageId?: string;
  userMessage?: string;
  /** resume 登记键 = assistant message_id；startTurn 亦可在 finalize 前未知。 */
  messageId?: string;
  buffer: SidecarEventBuffer;
  /** 本回合是否曾被 attach 重绑过（合成终止事件的门闩）。 */
  hasAttached: boolean;
  /** attach 零 await 段内为 true：只入缓冲、不转发（互斥不重不漏）。 */
  attaching: boolean;
}

/**
 * sidecar 进程的缓存键：`容器根 id + 工作区子路径`（工作区对称化 D1a）。
 *
 * 同一容器根下的多个子路径工作区**各起一个** sidecar（各自 `workspaceRoot = 容器根/子路径`），
 * 故不能只按 rootId 复用——否则会撞进同一进程、跑在错误目录。空 subpath（显式添加的本地项目）
 * 退化为 `${rootId}::`，与历史只按 rootId 起的行为等价（仅多个固定后缀）。
 */
function entryKey(rootId: string, subpath = ""): string {
  return `${rootId}::${subpath}`;
}

/**
 * 把容器根绝对路径与工作区子路径（工作区对称化 D1a）拼成 sidecar 的 `workspaceRoot`。
 *
 * 子路径非空时返回 `容器根/子路径` 并**确保该目录存在**（懒建工作区首次产文件通常已建出，但
 * 防御性 mkdir 兜底极端早到的 sidecar 回合，避免引擎绑定到不存在的目录）。空子路径 = 容器根
 * 自身（恒存在），不触盘，与历史行为逐字节一致。
 */
async function resolveWorkspaceRoot(
  absPath: string,
  subpath?: string,
): Promise<string> {
  const sub = (subpath ?? "").replace(/^\/+|\/+$/g, "");
  if (!sub) return absPath;
  const workspaceRoot = join(absPath, sub);
  await mkdir(workspaceRoot, { recursive: true });
  return workspaceRoot;
}

/**
 * 管理每个授权根的 sidecar：懒拉起 + 初始化、回合事件路由、cancel/respond、退出清理。
 *
 * `spawnFn` 可注入（默认真实 `spawnTransport`），便于单测用假传输驱动整条链路。
 */
export class SidecarManager {
  private readonly entries = new Map<string, SidecarEntry>();
  private readonly turns = new Map<string, ActiveTurn>();

  constructor(
    private readonly spawnFn: (
      config: SpawnConfig,
    ) => Transport = spawnTransport,
  ) {}

  /**
   * 拉起（或复用）某 `root + subpath` 的 sidecar，并完成一次性 initialize。
   *
   * `workspaceRoot` 已是绑定根目录（容器根 absPath 拼上子路径，由 IPC handler 算好），即引擎本
   * 回合的工作区；缓存键含 subpath，故同容器根下的不同子路径工作区互不串台。状态推送仍按容器
   * `rootId`（与 renderer 的 sidecarStatus / `takeRecentSidecarFailure(rootId)` 对齐——诊断按根聚合）。
   */
  private ensure(
    rootId: string,
    subpath: string,
    workspaceRoot: string,
    inference: SidecarInference | undefined,
  ): SidecarEntry {
    const key = entryKey(rootId, subpath);
    const existing = this.entries.get(key);
    if (existing) return existing;

    const transport = this.spawnFn(resolveSpawnConfig());
    const client = new SidecarClient(transport);
    client.onNotification((method, params) =>
      this.onNotification(method, params),
    );
    client.onClosed((err) => {
      this.entries.delete(key);
      this.pushStatus({ rootId, phase: "exited", detail: err.message });
    });

    const ready = client
      .request("initialize", {
        userId: "local",
        workspaceRoot,
        approvalsEnabled: SIDECAR_APPROVALS_ENABLED,
        // The app-private data dir for durable pause frames (双模式工作区 §一.1):
        // its presence flips the engine's local paused-turn store on.
        dataDir: sidecarDataDir(),
        ...(inference ? { inference } : {}),
        // Always send key (null when Bridge not Ready) so sidecar clears sticky env.
        browserBridge: currentBrowserBridge(),
      })
      .then(() => {
        this.pushStatus({ rootId, phase: "spawned" });
      })
      .catch((err: unknown) => {
        // 初始化失败（uv/venv 找不到、引擎导入失败等）——逐出，下次重拉；上抛给 startTurn。
        this.entries.delete(key);
        const detail = err instanceof Error ? err.message : String(err);
        this.pushStatus({ rootId, phase: "error", detail });
        client.dispose();
        throw err instanceof Error ? err : new Error(detail);
      });

    const entry: SidecarEntry = { client, ready };
    this.entries.set(key, entry);
    return entry;
  }

  /**
   * 在某根的 sidecar 上跑一个回合；Promise 在回合结束时 resolve（携带最终结果），
   * 过程事件经 `sidecar:event` 推给 `wc`。
   */
  async startTurn(
    wc: WebContents,
    req: SidecarStartTurnRequest,
    workspaceRoot: string,
  ): Promise<SidecarTurnResult> {
    const entry = this.ensure(
      req.rootId,
      req.subpath ?? "",
      workspaceRoot,
      req.inference,
    );
    await entry.ready; // 初始化失败则在此抛出 → renderer 据此降级

    this.turns.set(req.turnId, {
      wc,
      conversationId: req.conversationId,
      rootId: req.rootId,
      subpath: req.subpath ?? "",
      kind: "start",
      traceId: req.traceId,
      userMessageId: req.userMessageId,
      userMessage: req.userMessage,
      buffer: new SidecarEventBuffer(),
      hasAttached: false,
      attaching: false,
    });
    try {
      const sessionRoots = listSessionRoots(req.conversationId);
      const externalMounts = sessionRoots
        .filter((r) => r.alias && r.absPath)
        .map((r) => ({
          alias: r.alias as string,
          rootId: r.id,
          label: r.name,
          absPath: r.absPath,
          mode: r.mode ?? (r.readonly ? "readonly" : "readonly"),
        }));
      const result = await entry.client.request("startTurn", {
        turnId: req.turnId,
        conversationId: req.conversationId,
        traceId: req.traceId,
        userMessage: req.userMessage,
        // Outbox idempotency anchor (as-built: 双模式工作区 §10.3).
        userMessageId: req.userMessageId,
        history: req.history ?? [],
        // W3: session read-only mounts (abs paths stay in main → sidecar only).
        ...(externalMounts.length > 0 ? { externalMounts } : {}),
        // Re-send the current cloud-proxy token every turn: the sidecar is long-lived
        // but the token rotates (12h TTL), so the engine adopts the fresh one per turn
        // (initialize-time creds would otherwise 401 after expiry).
        ...(req.inference ? { inference: req.inference } : {}),
        // Same for DesktopBrowserBridge (B-Arch): refresh every turn; null = 未装配.
        browserBridge: currentBrowserBridge(),
        // 会话权限轴按回合随送：中途切换后下一回合即生效。
        ...(req.permissionAxes
          ? { permissionAxes: req.permissionAxes }
          : req.permissionPreset
            ? { permissionPreset: req.permissionPreset }
            : {}),
      });
      this.emitSyntheticTerminalIfNeeded(req.turnId, "message_end");
      return result as SidecarTurnResult;
    } catch (err) {
      this.emitSyntheticTerminalIfNeeded(req.turnId, "error", err);
      throw err;
    } finally {
      this.turns.delete(req.turnId);
    }
  }

  /**
   * 探活某 `root + subpath` 的 sidecar：拉起（或复用）进程并完成 initialize 握手即返回，不跑
   * 任何回合。用于在首次真正走 sidecar 前提前验证本机环境（Python / venv / 引擎导入 / 工作区
   * 绑定）能起得来；握手成功留存的进程正好被随后的首个回合复用（`ensure` 命中缓存、零额外拉
   * 起）。失败时 `ensure` 的 `ready` 已 pushStatus(error) + 逐出该 entry，错误上抛给调用方。
   */
  async probe(
    rootId: string,
    subpath: string,
    workspaceRoot: string,
  ): Promise<void> {
    // 不传 inference：探活只验证环境能起；真实回合的 startTurn 会按回合重发云代理凭据。
    const entry = this.ensure(rootId, subpath, workspaceRoot, undefined);
    await entry.ready;
  }

  /** A1+ 本机真 diff：ensure sidecar → `turnFilesDiff` RPC（相对本地基线 zip）。 */
  async turnFilesDiff(
    req: SidecarTurnFilesDiffRequest,
    workspaceRoot: string,
  ): Promise<SidecarTurnFilesDiffResult> {
    const entry = this.ensure(
      req.rootId,
      req.subpath ?? "",
      workspaceRoot,
      undefined,
    );
    await entry.ready;
    const params: Record<string, unknown> = { messageId: req.messageId };
    if (req.baselineSnapshotId) {
      params.baselineSnapshotId = req.baselineSnapshotId;
    }
    return entry.client.request(
      "turnFilesDiff",
      params,
    ) as Promise<SidecarTurnFilesDiffResult>;
  }

  /** A2′ 本机回退：ensure sidecar → `restoreTurnBaseline`（unzip，不经云）。 */
  async restoreTurnBaseline(
    req: SidecarRestoreTurnBaselineRequest,
    workspaceRoot: string,
  ): Promise<void> {
    const entry = this.ensure(
      req.rootId,
      req.subpath ?? "",
      workspaceRoot,
      undefined,
    );
    await entry.ready;
    await entry.client.request("restoreTurnBaseline", {
      snapshotId: req.snapshotId,
    });
  }

  /** Local hydrate: ensure sidecar → `listBrowserSessions`（同进程 Registry）。 */
  async listBrowserSessions(
    req: SidecarListBrowserSessionsRequest,
    workspaceRoot: string,
  ): Promise<SidecarListBrowserSessionsResult> {
    const entry = this.ensure(
      req.rootId,
      req.subpath ?? "",
      workspaceRoot,
      undefined,
    );
    await entry.ready;
    return entry.client.request("listBrowserSessions", {
      conversationId: req.conversationId,
    }) as Promise<SidecarListBrowserSessionsResult>;
  }

  /**
   * 续跑一个持久挂起的本地回合（结构化挂起 2b）。
   *
   * 与 `startTurn` 同构：拉起 / 复用该根 sidecar，claim 本机帧并跑 `resume_chat_pipeline`，
   * Promise 在续跑结束时携最终结果 resolve（供 renderer 回写云端），过程事件经 `sidecar:event`
   * 推回。事件路由键用 message_id（一回合至多一个持久挂起）。
   */
  async resume(
    wc: WebContents,
    req: SidecarResumeRequest,
    workspaceRoot: string,
    inference: SidecarInference | undefined,
  ): Promise<SidecarTurnResult> {
    const entry = this.ensure(
      req.rootId,
      req.subpath ?? "",
      workspaceRoot,
      inference,
    );
    await entry.ready;

    this.turns.set(req.messageId, {
      wc,
      conversationId: req.conversationId,
      rootId: req.rootId,
      subpath: req.subpath ?? "",
      kind: "resume",
      traceId: req.traceId,
      userMessageId: req.userMessageId,
      messageId: req.messageId,
      buffer: new SidecarEventBuffer(),
      hasAttached: false,
      attaching: false,
    });
    try {
      const sessionRoots = listSessionRoots(req.conversationId);
      const externalMounts = sessionRoots
        .filter((r) => r.alias && r.absPath)
        .map((r) => ({
          alias: r.alias as string,
          rootId: r.id,
          label: r.name,
          absPath: r.absPath,
          mode: r.mode ?? (r.readonly ? "readonly" : "readonly"),
        }));
      const result = await entry.client.request("resume", {
        ...buildSidecarResumeRpcParams(req, inference, currentBrowserBridge()),
        ...(externalMounts.length > 0 ? { externalMounts } : {}),
      });
      this.emitSyntheticTerminalIfNeeded(req.messageId, "message_end");
      return result as SidecarTurnResult;
    } catch (err) {
      this.emitSyntheticTerminalIfNeeded(req.messageId, "error", err);
      throw err;
    } finally {
      this.turns.delete(req.messageId);
    }
  }

  /**
   * Local recovery query: live turn + outbox unsynced + paused frames. Zero spawn.
   */
  async recovery(
    req: SidecarRecoveryRequest,
  ): Promise<SidecarRecoveryResponse> {
    const live = this.findLiveTurn(req.conversationId);
    const [unsynced, paused] = await Promise.all([
      listUnsyncedSummaries(req.conversationId),
      readLocalPausedSummaries(req.conversationId),
    ]);
    // Exclude the live turn's open row — D5 projects ready + dead-open only;
    // live content comes from attach replay.
    const filtered = live
      ? unsynced.filter((u) => {
          if (live.turn.kind === "start" && live.turn.userMessageId) {
            return u.user_message_id !== live.turn.userMessageId;
          }
          if (live.turn.kind === "resume" && live.turn.messageId) {
            return u.message_id !== live.turn.messageId;
          }
          return true;
        })
      : unsynced;
    logDesktop({
      level: "info",
      event: "sidecar.recovery",
      fields: {
        conversation_id: req.conversationId,
        live_running: live !== null,
        unsynced_count: filtered.length,
        paused_count: paused.length,
      },
    });
    return {
      liveRunning: live !== null,
      ...(live ? { turnId: live.turnId } : {}),
      unsynced: filtered,
      paused,
    };
  }

  /**
   * Rebind the live turn's WebContents and snapshot the event buffer (D4).
   *
   * **Zero-await hard constraint** between rebind and snapshot: every event is
   * either in the returned snapshot or forwarded to the new wc — never both,
   * never lost. Callers must not insert awaits in this method.
   */
  attach(wc: WebContents, req: SidecarAttachRequest): SidecarAttachResponse {
    const live = this.findLiveTurn(req.conversationId);
    if (!live) {
      logDesktop({
        level: "info",
        event: "sidecar.attach",
        fields: {
          conversation_id: req.conversationId,
          attached: false,
          buffer_length: 0,
        },
      });
      return { attached: false };
    }
    // --- zero-await section (do not await) ---
    live.turn.attaching = true;
    live.turn.wc = wc;
    live.turn.hasAttached = true;
    const events = live.turn.buffer.snapshot();
    live.turn.attaching = false;
    // --- end zero-await section ---
    logDesktop({
      level: "info",
      event: "sidecar.attach",
      fields: {
        conversation_id: req.conversationId,
        attached: true,
        turn_id: live.turnId,
        buffer_length: events.length,
      },
    });
    return {
      attached: true,
      turnId: live.turnId,
      rootId: live.turn.rootId,
      subpath: live.turn.subpath,
      userMessageId: live.turn.userMessageId,
      userMessage: live.turn.userMessage,
      traceId: live.turn.traceId,
      messageId: live.turn.messageId,
      kind: live.turn.kind,
      events,
    };
  }

  /**
   * 取消一个在跑的回合。无对应 sidecar / RPC 失败时抛错，供 FE 可见提示与重试
   * （勿静默吞——停止未确认时用户需要知道信号没发出去）。
   */
  async cancel(req: SidecarCancelRequest): Promise<void> {
    const entry = this.entries.get(entryKey(req.rootId, req.subpath));
    if (!entry) {
      throw new Error("本地引擎未运行，无法停止");
    }
    await entry.client.request("cancel", {
      turnId: req.turnId,
      ...(req.conversationId ? { conversationId: req.conversationId } : {}),
      ...(req.reason ? { reason: req.reason } : {}),
    });
  }

  /** 用户中途改某个 worker 的方向（队列入队；Step 2 由 scheduler 消费）。 */
  async runRedirect(req: SidecarRunRedirectRequest): Promise<void> {
    const entry = this.entries.get(entryKey(req.rootId, req.subpath));
    if (!entry) return;
    try {
      await entry.client.request("runRedirect", {
        conversationId: req.conversationId,
        executionId: req.executionId,
        runId: req.runId,
        feedback: req.feedback,
      });
    } catch {
      // sidecar 不可达时静默——与 cancel 一致。
    }
  }

  /** 辩论 ambient 掌舵（fire-and-forget，下一轮边界生效）。 */
  async debateSteer(req: SidecarDebateSteerRequest): Promise<void> {
    const entry = this.entries.get(entryKey(req.rootId, req.subpath));
    if (!entry) return;
    try {
      await entry.client.request("debateSteer", {
        conversationId: req.conversationId,
        executionId: req.executionId,
        decision: req.decision,
        focus: req.focus ?? "",
        ask: req.ask ?? "",
        askTarget: req.askTarget ?? "",
      });
    } catch {
      // sidecar 不可达时静默——与 runRedirect 一致。
    }
  }

  /** 结算一个被挂起的交互（审批 / ask_user / 本地工具）。 */
  async respond(req: SidecarRespondRequest): Promise<{ resolved: boolean }> {
    const entry = this.entries.get(entryKey(req.rootId, req.subpath));
    if (!entry) {
      throw new Error(
        `本地引擎未就绪（root=${req.rootId} subpath=${req.subpath ?? ""}），无法结算交互`,
      );
    }
    const reply = (await entry.client.request("respond", {
      requestId: req.requestId,
      conversationId: req.conversationId,
      result: req.result,
    })) as { resolved?: boolean } | null;
    return { resolved: Boolean(reply?.resolved) };
  }

  /** 退出时清理所有 sidecar（尽力发 shutdown 再终止进程）。 */
  disposeAll(): void {
    for (const [, entry] of this.entries) {
      void entry.client.request("shutdown", {}).catch(() => {});
      entry.client.dispose();
    }
    this.entries.clear();
    this.turns.clear();
  }

  private onNotification(
    method: string,
    params: Record<string, unknown>,
  ): void {
    if (method !== "turn/event") return;
    const turnId = String(params.turnId ?? "");
    const turn = this.turns.get(turnId);
    if (!turn) return;

    const raw = params.event;
    const event =
      raw && typeof raw === "object"
        ? (raw as {
            type?: string;
            timestamp?: string;
            payload?: unknown;
          })
        : null;
    if (!event?.type) return;

    const buffered = {
      type: String(event.type),
      timestamp:
        typeof event.timestamp === "string"
          ? event.timestamp
          : new Date().toISOString(),
      payload: event.payload,
    };
    // Buffer first (even when wc is destroyed) so refresh attach can replay.
    turn.buffer.record(buffered);

    // During attach's zero-await window: buffer only — snapshot owns those events.
    if (turn.attaching || turn.wc.isDestroyed()) return;
    turn.wc.send(SIDECAR_CHANNELS.event, {
      conversationId: turn.conversationId,
      turnId,
      event: buffered,
    });
  }

  /**
   * Before `turns.delete`: if an attached window never saw a terminal event,
   * synthesize one so the bubble cannot hang on「生成中」(D4 收尾必达).
   */
  private emitSyntheticTerminalIfNeeded(
    turnId: string,
    kind: "message_end" | "error",
    err?: unknown,
  ): void {
    const turn = this.turns.get(turnId);
    if (!turn || !turn.hasAttached) return;
    if (turn.buffer.hasTerminal()) return;

    const event = {
      type: kind,
      timestamp: new Date().toISOString(),
      payload:
        kind === "error"
          ? {
              code: "sidecar_turn_ended",
              message:
                err instanceof Error
                  ? err.message
                  : err
                    ? String(err)
                    : "本地回合异常结束",
            }
          : {},
    };
    turn.buffer.record(event);
    if (!turn.wc.isDestroyed()) {
      turn.wc.send(SIDECAR_CHANNELS.event, {
        conversationId: turn.conversationId,
        turnId,
        event,
      });
    }
  }

  private findLiveTurn(
    conversationId: string,
  ): { turnId: string; turn: ActiveTurn } | null {
    for (const [turnId, turn] of this.turns) {
      if (turn.conversationId === conversationId) {
        return { turnId, turn };
      }
    }
    return null;
  }

  private pushStatus(push: SidecarStatusPush): void {
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.webContents.isDestroyed()) {
        win.webContents.send(SIDECAR_CHANNELS.status, push);
      }
    }
  }
}

/**
 * sidecar IPC 边界校验：失败时先落 `sidecar.ipc_invalid_args`（desktop.jsonl +
 * dev stdout），再原样抛出——renderer 横幅可展示字段级原因，排查不再只靠 stderr。
 */
function assertSidecarShape(
  channel: string,
  payload: unknown,
  required: readonly string[],
  optionalStrings: readonly string[] = [],
): void {
  try {
    assertShape(channel, payload, required, optionalStrings);
  } catch (err) {
    if (err instanceof IpcInvalidArgsError) {
      logDesktop({
        level: "error",
        event: "sidecar.ipc_invalid_args",
        fields: ipcInvalidArgsLogFields(err, payload),
      });
    }
    throw err;
  }
}

/** 注册全部 sidecar IPC handler。须在 app ready 后调用。 */
export function registerSidecarIpc(): void {
  const manager = new SidecarManager();

  // IPC-004（第五轮 IPC 权限面审计）：每个句柄进入业务前在边界结构校验寻址 / 标识类 string
  // 字段（rootId / turnId / …）+ 可选 subpath。畸形入参（仅来自被攻破的 renderer）抛
  // `IpcInvalidArgsError` → invoke reject，与本组句柄「拉不起 / 引擎异常即 reject 让 renderer
  // 降级」的契约一致。数据载荷（history / inference / result）仍由下游 / 引擎宽容消费。
  // 校验失败另落 `sidecar.ipc_invalid_args`（见 {@link assertSidecarShape}）。
  ipcMain.handle(
    SIDECAR_CHANNELS.startTurn,
    async (e, req: SidecarStartTurnRequest): Promise<SidecarTurnResult> => {
      // permissionAxes 是对象载荷，勿列入 optionalStrings（否则合法请求被拒）。
      assertSidecarShape(
        SIDECAR_CHANNELS.startTurn,
        req,
        [
          "rootId",
          "conversationId",
          "turnId",
          "traceId",
          "userMessage",
          "userMessageId",
        ],
        ["subpath", "permissionPreset"],
      );
      const root = await getStoredRoot(req.rootId);
      if (!root) throw new Error("本地目录未授权或已移除");
      const workspaceRoot = await resolveWorkspaceRoot(
        root.absPath,
        req.subpath,
      );
      return manager.startTurn(e.sender, req, workspaceRoot);
    },
  );

  ipcMain.handle(SIDECAR_CHANNELS.cancel, (_e, req: SidecarCancelRequest) => {
    assertSidecarShape(
      SIDECAR_CHANNELS.cancel,
      req,
      ["rootId", "turnId"],
      ["subpath", "conversationId", "reason"],
    );
    return manager.cancel(req);
  });

  ipcMain.handle(SIDECAR_CHANNELS.respond, (_e, req: SidecarRespondRequest) => {
    assertSidecarShape(
      SIDECAR_CHANNELS.respond,
      req,
      ["rootId", "requestId", "conversationId"],
      ["subpath"],
    );
    return manager.respond(req);
  });

  ipcMain.handle(
    SIDECAR_CHANNELS.runRedirect,
    (_e, req: SidecarRunRedirectRequest) => {
      assertSidecarShape(
        SIDECAR_CHANNELS.runRedirect,
        req,
        ["rootId", "conversationId", "executionId", "runId", "feedback"],
        ["subpath"],
      );
      return manager.runRedirect(req);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.debateSteer,
    (_e, req: SidecarDebateSteerRequest) => {
      assertSidecarShape(
        SIDECAR_CHANNELS.debateSteer,
        req,
        ["rootId", "conversationId", "executionId", "decision"],
        ["subpath", "focus", "ask", "askTarget"],
      );
      return manager.debateSteer(req);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.resume,
    async (e, req: SidecarResumeRequest): Promise<SidecarTurnResult> => {
      // permissionAxes 是对象载荷，勿列入 optionalStrings（与 startTurn 同）。
      assertSidecarShape(
        SIDECAR_CHANNELS.resume,
        req,
        [
          "rootId",
          "conversationId",
          "messageId",
          "traceId",
          "decision",
          "note",
        ],
        ["subpath", "userMessageId", "permissionPreset"],
      );
      const root = await getStoredRoot(req.rootId);
      if (!root) throw new Error("本地目录未授权或已移除");
      const workspaceRoot = await resolveWorkspaceRoot(
        root.absPath,
        req.subpath,
      );
      return manager.resume(e.sender, req, workspaceRoot, req.inference);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.probe,
    async (_e, req: SidecarProbeRequest): Promise<void> => {
      assertSidecarShape(SIDECAR_CHANNELS.probe, req, ["rootId"], ["subpath"]);
      const root = await getStoredRoot(req.rootId);
      if (!root) throw new Error("本地目录未授权或已移除");
      const workspaceRoot = await resolveWorkspaceRoot(
        root.absPath,
        req.subpath,
      );
      await manager.probe(req.rootId, req.subpath ?? "", workspaceRoot);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.recovery,
    (_e, req: SidecarRecoveryRequest): Promise<SidecarRecoveryResponse> => {
      assertSidecarShape(SIDECAR_CHANNELS.recovery, req, ["conversationId"]);
      return manager.recovery(req);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.attach,
    (e, req: SidecarAttachRequest): SidecarAttachResponse => {
      assertSidecarShape(SIDECAR_CHANNELS.attach, req, ["conversationId"]);
      return manager.attach(e.sender, req);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.turnFilesDiff,
    async (
      _e,
      req: SidecarTurnFilesDiffRequest,
    ): Promise<SidecarTurnFilesDiffResult> => {
      assertSidecarShape(
        SIDECAR_CHANNELS.turnFilesDiff,
        req,
        ["rootId", "messageId"],
        ["subpath"],
      );
      const root = await getStoredRoot(req.rootId);
      if (!root) throw new Error("本地目录未授权或已移除");
      const workspaceRoot = await resolveWorkspaceRoot(
        root.absPath,
        req.subpath,
      );
      return manager.turnFilesDiff(req, workspaceRoot);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.restoreTurnBaseline,
    async (_e, req: SidecarRestoreTurnBaselineRequest): Promise<void> => {
      assertSidecarShape(
        SIDECAR_CHANNELS.restoreTurnBaseline,
        req,
        ["rootId", "snapshotId"],
        ["subpath"],
      );
      const root = await getStoredRoot(req.rootId);
      if (!root) throw new Error("本地目录未授权或已移除");
      const workspaceRoot = await resolveWorkspaceRoot(
        root.absPath,
        req.subpath,
      );
      await manager.restoreTurnBaseline(req, workspaceRoot);
    },
  );

  ipcMain.handle(
    SIDECAR_CHANNELS.listBrowserSessions,
    async (
      _e,
      req: SidecarListBrowserSessionsRequest,
    ): Promise<SidecarListBrowserSessionsResult> => {
      assertSidecarShape(
        SIDECAR_CHANNELS.listBrowserSessions,
        req,
        ["rootId", "conversationId"],
        ["subpath"],
      );
      const root = await getStoredRoot(req.rootId);
      if (!root) throw new Error("本地目录未授权或已移除");
      const workspaceRoot = await resolveWorkspaceRoot(
        root.absPath,
        req.subpath,
      );
      return manager.listBrowserSessions(req, workspaceRoot);
    },
  );

  app.on("before-quit", () => manager.disposeAll());
}
