import type { SidecarEventPush } from "@shared/sidecar-contract";

/**
 * Sidecar live 事件单例泵（每 turn 单事件泵）。
 *
 * 根因：`sidecarApi.onEvent` 每次调用都 `ipcRenderer.on`，`runSidecarTurn` 与
 * `attachSidecarTurn` 可叠多个 listener → 同一 `content_delta` 进 fold 两次（叠字）。
 *
 * 契约：App 生命周期对 `sidecar:event` **只订一次**；回合方只 **claim**
 * `(conversationId, turnId)` 的 sink，同一会话同时最多一个 owner。新 claim 注销旧 owner。
 * 禁止在 fold/contentBuffer 对相同 delta 去重。
 */

export type SidecarTurnSink = (push: SidecarEventPush) => void;

export interface SidecarTurnClaim {
  readonly token: string;
  readonly conversationId: string;
  /** `null` = 尚未收窄（attach 在 IPC 返回前接受该会话任意 turn）。 */
  readonly turnId: string | null;
  /** Attach 拿到 `turnId` 后收窄过滤；非 owner 时 no-op。 */
  setTurnId(turnId: string): void;
  /** 释放本 claim；仅当仍是当前 owner 时清除登记。 */
  release(): void;
  /** 是否仍占有该会话的 sink。 */
  isOwner(): boolean;
}

type Owner = {
  token: string;
  conversationId: string;
  turnId: string | null;
  sink: SidecarTurnSink;
  onRevoked?: () => void;
};

/** conversationId → 当前唯一 owner。 */
const owners = new Map<string, Owner>();

let installed = false;
let unsubscribeIpc: (() => void) | null = null;

/**
 * 订阅 `sidecar:event`（幂等）；在 renderer 启动时调一次。
 * 非桌面 / 未注入 `sidecarApi` 时 no-op。
 */
export function installSidecarEventPump(): void {
  if (installed) return;
  if (typeof window === "undefined" || !window.sidecarApi?.onEvent) return;
  installed = true;
  unsubscribeIpc = window.sidecarApi.onEvent(routePush);
}

function routePush(push: SidecarEventPush): void {
  const owner = owners.get(push.conversationId);
  if (!owner) return;
  if (owner.turnId !== null && owner.turnId !== push.turnId) return;
  owner.sink(push);
}

/**
 * Claim 某会话 sidecar live 的唯一 sink。
 *
 * @param turnId 已知则按 turn 过滤；`null` 表示 attach 预热（该会话任意 turn）。
 * @param onRevoked 被更新的 claim 顶替时回调（旧泵应停 fold / resolve）。
 */
export function claimSidecarTurnSink(
  conversationId: string,
  turnId: string | null,
  sink: SidecarTurnSink,
  opts?: { onRevoked?: () => void },
): SidecarTurnClaim {
  // 单测 / 未走 main.tsx 时惰性安装，保证 claim 路径仍只有一条 IPC 订阅。
  installSidecarEventPump();

  const prev = owners.get(conversationId);
  if (prev) {
    owners.delete(conversationId);
    prev.onRevoked?.();
  }

  const token = crypto.randomUUID();
  const owner: Owner = {
    token,
    conversationId,
    turnId,
    sink,
    onRevoked: opts?.onRevoked,
  };
  owners.set(conversationId, owner);

  return {
    get token() {
      return token;
    },
    get conversationId() {
      return conversationId;
    },
    get turnId() {
      return owner.turnId;
    },
    setTurnId(next: string) {
      if (owners.get(conversationId)?.token !== token) return;
      owner.turnId = next;
    },
    release() {
      const cur = owners.get(conversationId);
      if (cur?.token !== token) return;
      owners.delete(conversationId);
    },
    isOwner() {
      return owners.get(conversationId)?.token === token;
    },
  };
}

/** 测试隔离：清空 owner 并卸掉 IPC 订阅。 */
export function resetSidecarEventPumpForTests(): void {
  owners.clear();
  unsubscribeIpc?.();
  unsubscribeIpc = null;
  installed = false;
}
