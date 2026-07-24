/**
 * 交接结果评审的纯逻辑（双模式工作区 P2e / e3）—— PR 评审卡的客户端预判。
 *
 * 后端 `classify_three_way` 是冲突判定的**唯一权威**（base/result 哈希取自快照、
 * 本地哈希由桌面上报）；本模块在前端镜像同一套判定，仅为「应用前」给每个文件标出
 * 干净 / 已应用 / 冲突，并定缺省决策，让用户先看清再选。真正写回时服务端会用同样的
 * 哈希复核一遍（见 `workspace/handoff_apply.py`）。
 *
 * 全部为无副作用的纯函数（哈希除外：`sha256HexFromBase64` 是确定性变换，依赖运行时的
 * Web Crypto），故可脱离 React / 文件系统单测。
 */

/** 文件变更种类，对齐后端 `HandoffFileChange.change_type`。 */
export type ChangeType = "added" | "modified" | "deleted";

/** 三方比对判定，对齐后端 `classify_three_way` 的返回。 */
export type ThreeWayVerdict = "clean" | "applied" | "conflict";

/** 单文件的应用取向：取云端团队的版本，或保留本地。 */
export type RowDecision = "cloud" | "local";

/**
 * 一个文件的 base→result 增量（双模式工作区 P2e / e3，camelCase 域模型）。
 *
 * `baseSha` / `resultSha` 为各侧 sha256 hex（缺侧为 null：新增无 base、删除无
 * result）。`content` 是 result 的 UTF-8 文本（新增/修改时有；删除或二进制为 null，
 * 后者由 `isBinary` 标记，需经快照下载取回）。
 */
export interface HandoffFileChange {
  path: string;
  changeType: ChangeType;
  baseSha: string | null;
  resultSha: string | null;
  isBinary: boolean;
  content: string | null;
  sizeBytes: number;
}

/**
 * 单文件的应用决策，对齐后端 `HandoffApplySelection`。`localSha` 是桌面当前看到的
 * 本地哈希（第三方输入，文件本地不存在为 null）；`force` 在服务端判定为冲突时仍覆盖
 * 写入——由「在冲突行上选了云端」隐含推出，不是独立开关。
 */
export interface HandoffApplySelection {
  path: string;
  decision: RowDecision;
  localSha: string | null;
  force: boolean;
}

/** 评审卡的一行：变更 + 本地哈希 + 判定 + 当前决策。 */
export interface ReviewRow {
  change: HandoffFileChange;
  /** 本地当前文件的 sha256 hex；本地不存在或不可读为 null。 */
  localSha: string | null;
  verdict: ThreeWayVerdict;
  decision: RowDecision;
}

/**
 * 三方判定：把一个 result 变更应用到「活的」本地文件上的取向（镜像后端权威逻辑）。
 *
 * - `applied`：本地已等于 result —— 无需动作（重复应用幂等）。
 * - `clean`：本地仍等于云端起跑的 base —— 变更可干净应用。
 * - `conflict`：本地与两侧都不同 —— 用户在云端跑期间改过它，需逐文件手选。
 *
 * 两次相等比较即收敛全部增/改/删情形：例如删除（resultSha 为 null）在本地已不存在
 * （localSha 为 null）时为 `applied`，本地仍等于 base 时为 `clean`，否则 `conflict`。
 */
export function classifyThreeWay(
  baseSha: string | null,
  resultSha: string | null,
  localSha: string | null,
): ThreeWayVerdict {
  if (localSha === resultSha) return "applied";
  if (localSha === baseSha) return "clean";
  return "conflict";
}

/**
 * 一个判定的缺省决策：
 * - `clean` → 取云端（应用变更，这正是交接的目的）。
 * - `applied` → 取云端（服务端会判为已应用并跳过，无害的 no-op）。
 * - `conflict` → 保留本地（安全缺省；用户显式改选云端即为强制覆盖）。
 */
export function defaultDecision(verdict: ThreeWayVerdict): RowDecision {
  return verdict === "conflict" ? "local" : "cloud";
}

/**
 * 把变更集与「逐文件本地哈希」合成评审行：对每个变更三方判定并赋缺省决策。
 * `localShas` 缺项视为本地不存在（null）。
 */
export function buildReviewRows(
  changes: HandoffFileChange[],
  localShas: Map<string, string | null>,
): ReviewRow[] {
  return changes.map((change) => {
    const localSha = localShas.get(change.path) ?? null;
    const verdict = classifyThreeWay(
      change.baseSha,
      change.resultSha,
      localSha,
    );
    return { change, localSha, verdict, decision: defaultDecision(verdict) };
  });
}

/**
 * 把评审行折成发往应用端点的选择集。`force` 由「在冲突行上选云端」推出——
 * 这是覆盖本地改动的显式动作；干净/已应用行选云端不需要 force。
 */
export function buildSelections(rows: ReviewRow[]): HandoffApplySelection[] {
  return rows.map((r) => ({
    path: r.change.path,
    decision: r.decision,
    localSha: r.localSha,
    force: r.verdict === "conflict" && r.decision === "cloud",
  }));
}

/** 变更集按种类计数，供评审卡表头展示。 */
export function countChanges(changes: HandoffFileChange[]): {
  added: number;
  modified: number;
  deleted: number;
} {
  let added = 0;
  let modified = 0;
  let deleted = 0;
  for (const c of changes) {
    if (c.changeType === "added") added += 1;
    else if (c.changeType === "modified") modified += 1;
    else deleted += 1;
  }
  return { added, modified, deleted };
}

/** base64 → 原始字节 → sha256 hex；必须与服务端 `hashlib.sha256(bytes).hexdigest()` 一致。 */
export async function sha256HexFromBase64(base64: string): Promise<string> {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
