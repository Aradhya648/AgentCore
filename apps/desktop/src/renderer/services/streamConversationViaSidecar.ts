import { patchConversationCache } from "@/hooks/useConversations";
import { StreamError } from "@/lib/errors";
import { notifyWarning } from "@/lib/toast";
import { resolveSidecarInference } from "@/services/inferenceToken";
import { resolveConversationPermissionPreset } from "@/services/permissionPreset";
import {
  clearActiveSidecarTurn,
  setActiveSidecarTurn,
} from "@/services/sidecarRouting";
import { takeRecentSidecarFailure } from "@/services/sidecarStatus";
import {
  dispatchSSEEvent,
  flushPendingContent,
  flushPendingFrames,
} from "@/services/streamConversation";
import {
  claimPrimaryStream,
  releasePrimaryStream,
} from "@/services/turns/streamOwnership";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import {
  enterTurnStreaming,
  getTurnPhase,
  throwIfCannotOpenStream,
} from "@/stores/conversation/turnPhaseActions";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import { useTurnModelStore } from "@/stores/turnModel";
import type { SSEEvent } from "@/types/events";
import type {
  SidecarHistoryEntry,
  SidecarTurnResult,
} from "@shared/sidecar-contract";

/**
 * 本地引擎（sidecar）对话流 —— 与 `streamConversation`（云 SSE）对偶的另一条链路。
 *
 * 双模式工作区 / 远期规划 §一.1：当一个会话绑定了本地授权根、且走 sidecar 时，回合由
 * 用户机器上的 `python -m agentcore.sidecar` 跑。本函数把那条 stdio JSON-RPC 链路在
 * renderer 这端「伪装成」一次普通流式回合：
 *
 * - 过程事件经主进程 `sidecar:event` 推来，**与服务端 SSE 同形状**，故原样喂给同一个
 *   `dispatchSSEEvent`——会话切片 / 执行图 / 工具时间线全部复用，零额外分支。
 * - `window.sidecarApi.startTurn` 的 Promise 在回合结束时 resolve（携带最终结果；流式
 *   细节已由事件给过）。主进程按 FIFO 先推完事件再回响应，故 resolve 时 `message_end`
 *   已派发、气泡已收尾。
 *
 * 持久化（as-built: 双模式工作区 §10.3；前端 UX §一B）：sidecar 渐进写入本机 outbox；主进程 Bearer
 * 回写器投递 `POST .../local-turns`。Renderer 只标记 `synced_pending`、冲刷该 turn、
 * 并对账乐观气泡——不再做 HTTP 重试 / toast 手动重试。
 */

export interface StreamViaSidecarOptions {
  conversationId: string;
  /** 绑定的本地授权根 id（主进程据此解析绝对路径并复用 / 拉起该根的 sidecar）。 */
  rootId: string;
  /** 工作区子路径（工作区对称化 D1a）：非空时主进程把 sidecar 绑定到 `容器根/子路径`，
   *  使懒建的 per 对话本地工作区各跑在自己目录里。空 = 该根自身（现行为）。 */
  subpath?: string;
  content: string;
  /** 先前对话历史（sidecar 无库，需由调用方从本地会话切片喂入）。 */
  history?: SidecarHistoryEntry[];
  /** 本轮用户气泡的乐观 id：回写落库后据此把它换成云端权威 id（仅当它仍是末条 user
   *  消息时——防用户在回写返回前又发了一条而误改）。 */
  optimisticUserId: string;
  signal?: AbortSignal;
}

export interface ResumeViaSidecarOptions {
  conversationId: string;
  rootId: string;
  /** 工作区子路径（同 {@link StreamViaSidecarOptions.subpath}）：寻址按 root+subpath 起的
   *  sidecar 进程，使子路径工作区的续跑也落在自己目录里。空 = 该根自身。 */
  subpath?: string;
  /** 挂起回合的 assistant message_id（续跑键；也是事件路由 / cancel 的寻址键）。 */
  messageId: string;
  decision: "continue" | "per_call" | "adjust" | "stop" | "research_first";
  note: string;
  selected?: string[];
  /** Structured website style pick (s0/s1/…). */
  styleId?: string;
  /** 挂起回合的原始用户消息（来自帧）——续跑完成后随回写落库。 */
  userMessage: string;
  /** 挂起时已落库的原始 user 气泡 id（初始发送时的 optimisticUserId）——回写据此对账，
   *  续跑不再注入新气泡。 */
  userMessageId: string;
  signal?: AbortSignal;
}

/** 一个轻量 turnId（cancel 的寻址键）。crypto.randomUUID 在 Electron renderer 可用。 */
function newTurnId(): string {
  return `t_${crypto.randomUUID()}`;
}

/**
 * 本回合 trace_id：32-hex（去掉 UUID 连字符），与服务端 `core/log_context.new_trace_id`
 * （`uuid4().hex`）同形、契合 `Message.trace_id` 的 `String(32)` 列。随云代理 LLM 调用上报
 * 并随回写落库，使一次本地回合的推理日志↔气泡归并为同一条可 grep 的 trace（打通气泡↔日志）。
 */
function newTraceId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

/** 剥 Electron IPC / SidecarRpcError 包装，露出引擎真因原文；提不出则 `null`。 */
function unwrapSidecarRejectMessage(err: unknown): string | null {
  if (!(err instanceof Error)) return null;
  const unwrapped = err.message
    .replace(/^Error invoking remote method '[^']*':\s*/, "")
    .replace(/^(?:Error|SidecarRpcError):\s*/, "")
    .trim();
  return unwrapped || null;
}

/**
 * 从一次失败的回合 RPC（`startTurn` / `resume`）拒绝里提取本地引擎真因（onStatus 没记到时的兜底）。
 *
 * 回合中途引擎报错时进程仍健康（无 `error`/`exited` 推送），真因落在 RPC 错误的 message 里；
 * 而 Electron 会把主进程 handler 抛出的错误包成
 * `Error invoking remote method 'sidecar:startTurn': Error: <真因>`——剥掉这层包装与 `Error:`
 * 前缀，露出可读真因。提不出则返回 `null`，由调用方退到通用兜底文案。
 */
function describeSidecarTurnError(err: unknown): string | null {
  const unwrapped = unwrapSidecarRejectMessage(err);
  return unwrapped ? `本地引擎出错：${unwrapped}` : null;
}

/**
 * 诚实停止（`stopGeneration` 不 abort AbortSignal）下，sidecar `startTurn`/`resume`
 * 仍会以 `TURN_CANCELLED` / `"turn cancelled"` reject。须识别为用户停止并抛
 * `AbortError`，否则会误打「本地引擎出错」横幅。
 *
 * 判定：拒绝文案是引擎取消约定（IPC 后通常只剩 message，无 -32001 code）；
 * 或 turnPhase 仍为 `stopping`（message_end 尚未定格时的竞态）。
 * 不用 `stopped` 单独放行——避免 invoke 已成功后的 writeBack 失败被误吞。
 */
function isSidecarUserCancel(conversationId: string, err: unknown): boolean {
  const msg = unwrapSidecarRejectMessage(err)?.toLowerCase() ?? "";
  if (msg.includes("turn cancelled") || msg.includes("turn_cancelled")) {
    return true;
  }
  return getTurnPhase(conversationId) === "stopping";
}

/**
 * 发送一条用户消息，经本地 sidecar 跑完整回合并消费其事件流。
 *
 * 失败语义对齐云链路：用户停止（诚实停止 → cancel → RPC reject，或 AbortSignal）
 * 抛 `AbortError`；其余（拉不起 sidecar / 引擎异常）包成带本地引擎诊断的
 * `StreamError("sidecar")`（优先 onStatus 记下的生命周期诊断，见下），由
 * `services/turns.ts` 统一出**针对性**横幅 + 重试。
 */
export async function streamConversationViaSidecar({
  conversationId,
  rootId,
  subpath,
  content,
  history,
  optimisticUserId,
  signal,
}: StreamViaSidecarOptions): Promise<SidecarTurnResult> {
  const turnId = newTurnId();
  // 本回合 trace_id：贯穿云代理推理调用 + 回写落库，使推理日志↔气泡同 trace（打通气泡↔日志）。
  const traceId = newTraceId();
  // 云推理凭据（平台 key 不下放本机，走云端代理鉴权——Slice 4a）。取不到则带 undefined：
  // dev 下 sidecar 回退其自身配置，生产则以可重试的引擎错误失败（胜过静默跑成无计费回合）。
  const inference = (await resolveSidecarInference()) ?? undefined;
  // 本会话权限模式随回合送达本地引擎；取不到则 sidecar 沿用其当前值。
  const permissionPreset =
    await resolveConversationPermissionPreset(conversationId);
  throwIfCannotOpenStream(conversationId, signal);
  return runSidecarTurn({
    conversationId,
    rootId,
    subpath,
    turnId,
    signal,
    // 无令牌 = 本回合会落到 sidecar 的本机平台模型回退（非账号模型）——据此在回合跑完后提示。
    usedFallback: inference === undefined,
    failMessage: "本地引擎未能完成回合，请重试",
    invoke: () =>
      window.sidecarApi.startTurn({
        conversationId,
        rootId,
        subpath,
        turnId,
        traceId,
        userMessage: content,
        userMessageId: optimisticUserId,
        history,
        inference,
        permissionPreset,
      }),
    writeBack: () => persistAndReconcile(conversationId, optimisticUserId),
  });
}

/**
 * 续跑一个持久挂起的本地回合（结构化挂起 2b resume）—— `streamConversationViaSidecar` 的对偶。
 *
 * sidecar 回合暂停后应用关闭、帧落本机文件；重开会话经 recovery.paused 重现续跑卡，用户的决定经
 * 此函数下发到 sidecar 的 `resume`（claim 帧并跑 `resume_chat_pipeline`），过程事件与最终结果
 * 形态与一次普通本地回合完全一致，故复用同一套事件分发与回写。事件路由 / cancel 键用
 * message_id（一回合至多一个持久挂起）。
 */
export async function resumeConversationViaSidecar({
  conversationId,
  rootId,
  subpath,
  messageId,
  decision,
  note,
  selected,
  styleId,
  userMessageId,
  signal,
}: ResumeViaSidecarOptions): Promise<SidecarTurnResult> {
  console.warn(
    `[Resume] resumeConversationViaSidecar start conversationId=${conversationId} messageId=${messageId} decision=${decision} rootId=${rootId} subpath=${subpath}`,
  );
  // 续跑同样要跑 LLM（重启后会新拉起引擎），故随带当前云推理凭据（同 startTurn）。
  const inference = (await resolveSidecarInference()) ?? undefined;
  // 本会话权限模式（同 startTurn）：续跑期间的能力授权按会话当前模式。
  const permissionPreset =
    await resolveConversationPermissionPreset(conversationId);
  // 本次续跑的 trace_id（同 startTurn）：贯穿续跑的推理调用 + 回写落库。
  const traceId = newTraceId();
  throwIfCannotOpenStream(conversationId, signal);
  try {
    const result = await runSidecarTurn({
      conversationId,
      rootId,
      subpath,
      turnId: messageId,
      signal,
      // 同 startTurn：无令牌 = 续跑落到本机平台模型回退，回合跑完后提示。
      usedFallback: inference === undefined,
      failMessage: "本地引擎未能完成续跑，请重试",
      invoke: () =>
        window.sidecarApi.resume({
          rootId,
          subpath,
          conversationId,
          messageId,
          traceId,
          userMessageId,
          decision,
          note,
          selected,
          styleId,
          inference,
          permissionPreset,
        }),
      writeBack: () => persistAndReconcile(conversationId, userMessageId),
    });
    console.warn(
      `[Resume] resumeConversationViaSidecar completed conversationId=${conversationId} messageId=${messageId} decision=${decision}`,
    );
    return result;
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.warn(
      `[Resume] resumeConversationViaSidecar failed conversationId=${conversationId} messageId=${messageId} decision=${decision} err=${errMsg}`,
    );
    throw err;
  }
}

interface RunSidecarTurnOptions {
  conversationId: string;
  rootId: string;
  /** 工作区子路径（D1a）：cancel / respond 据 root+subpath 寻址到正确的 sidecar 进程。 */
  subpath?: string;
  /** 事件路由 + cancel 的寻址键：新回合用 turnId，续跑用 message_id。 */
  turnId: string;
  signal?: AbortSignal;
  /** 本回合是否取不到云推理令牌（→ sidecar 落本机平台模型回退）：据此在回合成功跑完后弹一条
   *  非阻断提示，告知这轮用了本机平台模型而非账号模型。 */
  usedFallback: boolean;
  /** 兜底错误文案（onStatus / RPC 真因都取不到时）。 */
  failMessage: string;
  /** 实际的 RPC 调用（startTurn / resume），Promise 在回合结束时携最终结果 resolve。 */
  invoke: () => Promise<SidecarTurnResult>;
  /** 回合结束后冲刷 outbox 并对账（主进程回写；renderer 只反映同步态）。 */
  writeBack: (result: SidecarTurnResult) => Promise<void>;
}

/**
 * 在 renderer 这端把一次 sidecar RPC（startTurn / resume）「伪装成」普通流式回合：订阅事件流
 * 并原样喂 `dispatchSSEEvent`、桥接停止按钮到 `cancel`、收尾后冲刷 outbox、把本地引擎失败统一
 * 包成带诊断的 `StreamError("sidecar")`。新回合与续跑共用这套脚手架，仅 `invoke` / `writeBack`
 * 不同（避免两条链路各写一份事件/中止/错误处理）。
 */
async function runSidecarTurn({
  conversationId,
  rootId,
  subpath,
  turnId,
  signal,
  usedFallback,
  failMessage,
  invoke,
  writeBack,
}: RunSidecarTurnOptions): Promise<SidecarTurnResult> {
  // 回合从干净的审批门开始（与云链路一致）。
  clearInteractionPrompts(conversationId);

  // 登记「本会话此刻是 sidecar 回合」（连同 root+subpath），使本回合内挂起的审批 / 交互结算
  // （统一入口 `resolveInteraction`）改走 `window.sidecarApi.respond` 回这条 stdio 链路（寻址到
  // 按 root+subpath 起的同一进程），而非云端 HTTP。
  setActiveSidecarTurn(conversationId, rootId, subpath, turnId);

  // 只消费本会话的事件；主进程已按 turnId 路由到本窗口，这里再按 conversationId 过滤，
  // 防一个 sidecar 服务多个会话时串台。
  // 本回合是否派发过任何 sidecar 事件——一个都没有 = 引擎没跑起来（启动期失败，无输出 /
  // 副作用），失败时据此标 `recoverable` 让 turns.sendTurn 安全降级回云端（阶段二）。
  let sawAnyEvent = false;
  const unsubscribe = window.sidecarApi.onEvent((push) => {
    if (push.conversationId !== conversationId) return;
    sawAnyEvent = true;
    dispatchSSEEvent(push.event as SSEEvent, {
      conversationId,
      source: "sidecar",
    });
  });

  const onAbort = (): void => {
    // Abort 不是停止权威（stopGeneration 走 stopConversation → cancel）；此处仅在
    // 其它 abort 路径（如切会话）尽力通知引擎，失败不吞进 UI（fire-and-forget）。
    void window.sidecarApi
      .cancel({ rootId, subpath, turnId, conversationId })
      .catch(() => {});
  };

  const primaryToken = claimPrimaryStream(conversationId);
  try {
    // 开流门禁：已 abort / stopping|terminal → 不 invoke（H1）。Abort 只负责断流；权威是 phase。
    throwIfCannotOpenStream(conversationId, signal);
    enterTurnStreaming(conversationId);
    if (signal) {
      signal.addEventListener("abort", onAbort, { once: true });
    }

    const result = await invoke();
    // 记下本回合真正跑的模型（引擎侧 resolve_turn_model），供输入框徽章如实展示；纯云会话
    // 无此信号、徽章回退账号配置。回退回合（无令牌）额外弹一条非阻断提示，点破「用了本机平台
    // 模型而非账号模型」——两个信号同源（result.model 即回退时的平台模型），避免再查一次配置。
    useTurnModelStore.getState().setLastModel(conversationId, result.model);
    if (usedFallback) {
      warnPlatformModelFallback(result.model);
    }
    // 本机已出结果 → 标 synced_pending，冲刷主进程 outbox 并对账。
    await writeBack(result);
    return result;
  } catch (err) {
    // 用户停止：与云链路一致地抛 AbortError（调用方据此不出错误横幅）。
    // 诚实停止不 abort signal，靠 phase / TURN_CANCELLED 文案识别（见 isSidecarUserCancel）。
    if (signal?.aborted || isSidecarUserCancel(conversationId, err)) {
      throw new DOMException("Aborted", "AbortError");
    }
    // 开流门禁抛出的 AbortError（phase 阻断、尚未 invoke）直接上抛。
    if (err instanceof DOMException && err.name === "AbortError") {
      throw err;
    }
    // 这条链路的失败**全部来自本地引擎**（拉不起 / 初始化失败 / 引擎异常 / 进程退出），从不是
    // 真正的「网络」。优先用 onStatus 记下的生命周期诊断（uv/venv 找不到、退出码…）换出针对性
    // 横幅；没有（如回合中途引擎报错，进程仍健康）则退回从该次拒绝里提取真因，最后兜底。
    const detail =
      takeRecentSidecarFailure(rootId) ??
      describeSidecarTurnError(err) ??
      failMessage;
    // 启动期失败（一个事件都没派发）= 无任何输出 / 副作用，可安全改道云端重跑（阶段二降级）；
    // 中途失败（已开始流式 / 已调工具）则否，照常走「本地引擎出错」横幅 + 重试。
    throw new StreamError("sidecar", undefined, {
      serverMessage: detail,
      recoverable: !sawAnyEvent,
    });
  } finally {
    // Abort / engine failure skips message_end (and thus its flush); drain any
    // rAF-buffered content + worker frames so a partial answer keeps its last tokens.
    flushPendingContent(conversationId);
    flushPendingFrames(conversationId);
    clearActiveSidecarTurn(conversationId, turnId);
    unsubscribe();
    signal?.removeEventListener("abort", onAbort);
    releasePrimaryStream(conversationId, primaryToken);
  }
}

/**
 * 冲刷本机 outbox 并对账乐观气泡（as-built: 双模式工作区 §10.3；前端 UX §一B）。
 *
 * Sidecar 已把 finalize 渐进写入 outbox；主进程 Bearer 回写器投递云端。
 * Renderer 只反映同步态——失败保留 `synced_pending`，由主进程轮询续传（无 toast / 无
 * renderer HTTP 双写）。
 */
async function persistAndReconcile(
  conversationId: string,
  optimisticUserId: string,
): Promise<void> {
  const store = useConversationStore.getState();
  store.setTurnSyncStatus(optimisticUserId, "synced_pending", conversationId);

  if (!window.outboxApi?.flushTurn) {
    // Sidecar only runs in Electron where outboxApi is injected; keep pending hint.
    console.error(
      "[sidecar] outboxApi missing — sync left to main-process drain",
    );
    return;
  }

  try {
    const flushed = await window.outboxApi.flushTurn({
      userMessageId: optimisticUserId,
    });
    if (flushed.ok && flushed.synced) {
      applyReconcile(conversationId, optimisticUserId, {
        user_message_id: flushed.synced.cloudUserMessageId || optimisticUserId,
        assistant_message_id: flushed.synced.assistantMessageId,
        title: flushed.synced.title,
        followups: flushed.synced.followups,
      });
      // onSynced from main also flips the hint; set here for snappy UI if push races.
      const anchor = flushed.synced.cloudUserMessageId || optimisticUserId;
      store.setTurnSyncStatus(anchor, "synced", conversationId);
      setTimeout(() => {
        store.setTurnSyncStatus(anchor, undefined, conversationId);
      }, 2500);
      return;
    }
    // Auth/network — file stays; polling + synced_pending UI cover the rest.
    console.error("[sidecar] outbox writeback pending", flushed.error);
  } catch (err) {
    console.error("[sidecar] outbox flushTurn failed", err);
  }
}

/**
 * 对账乐观气泡（等价云链路 turn_saved + title_generated）。user id 现已是客户端权威，故换 id
 * 通常是 X→X 无害交换；仍按「末条 user 仍是本轮乐观气泡」守卫——防用户在回写返回前又发了
 * 一条而改错对象。本会话首次产出的标题刷进侧栏缓存。
 */
function applyReconcile(
  conversationId: string,
  optimisticUserId: string,
  saved: {
    user_message_id: string;
    assistant_message_id?: string | null;
    title?: string | null;
    followups?: string[] | null;
  },
): void {
  const messages = getRuntime(conversationId).messages;
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  if (lastUser?.id === optimisticUserId) {
    useConversationStore
      .getState()
      .reconcileLastTurn(saved.user_message_id, conversationId);
  }
  if (saved.title) {
    patchConversationCache(conversationId, { title: saved.title });
  }
  // Local twin of followups_generated: stamp chips on the assistant row by id.
  if (saved.followups?.length && saved.assistant_message_id) {
    useConversationStore
      .getState()
      .attachFollowups(
        saved.followups,
        saved.assistant_message_id,
        conversationId,
      );
  }
}

/**
 * 本机平台模型回退的可见提示（非阻断）。
 *
 * 取不到云推理令牌（如后端重启中 → inference-token 兑换失败）时，sidecar 会静默用本机 `.env`
 * 平台模型跑完这一回合，而非用户配置的账号模型。回合本身成功了（故非错误横幅、不重跑），只是
 * 用了「另一个模型」——这条 heads-up 点破它，并报出真跑的模型名（`result.model`）。
 */
function warnPlatformModelFallback(model: string): void {
  const named = model.trim();
  notifyWarning("本回合用了本机平台模型", {
    description: named
      ? `未取到云端推理令牌，这轮用本机 ${named} 跑完，而非你配置的账号模型。`
      : "未取到云端推理令牌，这轮用本机平台模型跑完，而非你配置的账号模型。",
  });
}
