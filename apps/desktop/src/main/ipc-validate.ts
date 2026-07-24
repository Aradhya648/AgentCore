/**
 * IPC 入参的薄运行时校验层（IPC-004 · 第五轮「preload IPC 权限面」审计闭环）。
 *
 * 背景：主进程 `ipcMain` 句柄过去把 renderer 入参**直接 TS 断言**为目标形状、运行时不校验，
 * 安全完全靠**下游守卫**（路径守卫 / dispatch `default` 分支 / log `sanitize`）兜底。下游守卫
 * 今日成立，但「边界是否被校验」是**下游的偶然**而非**边界的结构**——某个句柄一旦漏接下游
 * 守卫，就会在被攻破的 renderer 面前裸奔（见审计 IPC-004）。
 *
 * 本模块把这层校验**前移到 IPC 边界**：每个句柄进入业务前先核验 payload 形状，畸形入参（仅
 * 可能来自被攻破的 renderer——正常 renderer 由共享 TS 契约保证形状）在边界即被拒。
 *
 * 刻意**不引第三方 schema 库**（zod/valibot）：IPC 形状简单、手写守卫零依赖、与契约类型同源。
 * 失败处置因句柄契约而异——返回判别式结果（`FsResult` 等）的句柄回 `{ok:false}`、契约即
 * reject 的句柄（sidecar）抛 {@link IpcInvalidArgsError}，故本模块同时提供「返回式」与
 * 「抛出式」两个入口。校验只覆盖**寻址 / 标识类字符串字段**（rootId / relPath / op 等——它们
 * 决定碰哪个根、哪条路径、哪种操作）；数据载荷（content / args / history 等）的语义仍由各自
 * 下游负责，本层不深校验，保持「薄」。
 */

/** 是否为非 null 对象（数组也算对象，留给后续键校验筛除）。 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * 校验 payload 为对象且 `keys` 全部为 string，返回窄化后的对象；任一不满足返回 null。
 * 「返回式」入口——给以判别式结果（如 `FsResult`）回应失败的句柄。
 */
export function requireStringFields<K extends string>(
  payload: unknown,
  keys: readonly K[],
): Record<K, string> | null {
  if (!isRecord(payload)) return null;
  const out = {} as Record<K, string>;
  for (const key of keys) {
    const value = payload[key];
    if (typeof value !== "string") return null;
    out[key] = value;
  }
  return out;
}

/** IPC 边界结构校验失败（仅被攻破的 renderer 才会触发——正常 renderer 由 TS 契约保证形状）。 */
export class IpcInvalidArgsError extends Error {
  constructor(channel: string) {
    super(`无效的 IPC 入参：${channel}`);
    this.name = "IpcInvalidArgsError";
  }
}

/**
 * 校验 payload 含全部 `required` string 字段、且 `optionalStrings`（若出现）也为 string；
 * 不满足即抛 {@link IpcInvalidArgsError}。「抛出式」入口——给「契约即失败=reject」的句柄
 * （sidecar：startTurn/resume 等本就以 reject 让 renderer 降级，边界抛出语义与之一致）。
 */
export function assertShape(
  channel: string,
  payload: unknown,
  required: readonly string[],
  optionalStrings: readonly string[] = [],
): void {
  if (!isRecord(payload)) throw new IpcInvalidArgsError(channel);
  for (const key of required) {
    if (typeof payload[key] !== "string")
      throw new IpcInvalidArgsError(channel);
  }
  for (const key of optionalStrings) {
    const value = payload[key];
    if (value !== undefined && typeof value !== "string") {
      throw new IpcInvalidArgsError(channel);
    }
  }
}
