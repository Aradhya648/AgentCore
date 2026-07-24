import {
  type BrowserLiveConnection,
  type BrowserLiveState,
  startBrowserLive,
} from "@/services/browserLive";
import {
  type InputBatcher,
  createInputBatcher,
  endBrowserTakeover,
  modifiersOf,
  sendBrowserInput,
  startBrowserTakeover,
  takeoverStartErrorMessage,
  toFrameSpace,
} from "@/services/browserTakeover";
import { useBrowserTakeoverStore } from "@/stores/browserTakeover";
import {
  Hand,
  Loader2,
  type LucideIcon,
  MonitorOff,
  Radio,
  WifiOff,
} from "lucide-react";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

/**
 * L3「团队浏览器」M1 直播 + M2 用户接管 tab body (提案 D15/D16)——桌面首个「按帧刷新」组件。
 *
 * 附着一条 `…/browser/live` SSE 直播流（{@link startBrowserLive}），把 base64 jpeg 帧转成
 * objectURL **逐帧换图**：每来一帧换 `<img src>`、并回收上一帧的 objectURL（防内存泄漏）。覆盖
 * 连接中 / 无直播(no_session) / 会话已结束(session_closed) / 断线重连各态。挂载即附着（开播）、
 * 卸载即收口（停播）——由 SidePanel 仅在直播 tab 激活时挂载本组件，实现「无人看零开销」。
 *
 * M2 接管（D16）：有活直播（started 且有帧）时显「接管」；接管中画面变可交互面——捕获点击/键盘/
 * 滚轮，把展示坐标 {@link toFrameSpace} 换算到帧像素空间，经 {@link createInputBatcher} 攒批
 * POST（避免事件洪泛）；显著「接管中」状态条 + 「归还控制」。start 失败（turn_running 等）、会话
 * 结束(session_closed)、面板卸载都收口（卸载时尽力 end）。接管起止乐观并入接管 store 供时间线
 * 标记卡即时可见。密码等键入不回显不留存（缓冲仅在飞、不落任何持久缓存，守 D7）。
 */

/** base64（不含 data: 前缀）→ Blob，供 `URL.createObjectURL` 逐帧换图。 */
function base64ToBlob(b64: string, mime: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

interface Placeholder {
  Icon: LucideIcon;
  spin?: boolean;
  tone: "muted" | "warning";
  title: string;
  hint?: string;
}

/** No-frame body: choose the icon + copy for the current transport / session state. */
function placeholderFor(
  connection: BrowserLiveConnection,
  status: BrowserLiveState | null,
): Placeholder {
  if (status === "no_session") {
    return {
      Icon: MonitorOff,
      tone: "muted",
      title: "当前没有进行中的直播",
      hint: "AI 开始使用浏览器后，画面会实时出现在这里",
    };
  }
  if (status === "session_closed") {
    return {
      Icon: MonitorOff,
      tone: "muted",
      title: "直播已结束",
      hint: "浏览器会话已关闭",
    };
  }
  if (connection === "reconnecting") {
    return { Icon: WifiOff, tone: "warning", title: "连接已断开，正在重连…" };
  }
  if (status === "started") {
    return { Icon: Loader2, spin: true, tone: "muted", title: "等待画面…" };
  }
  return { Icon: Loader2, spin: true, tone: "muted", title: "连接中…" };
}

function LivePlaceholder({
  connection,
  status,
}: {
  connection: BrowserLiveConnection;
  status: BrowserLiveState | null;
}) {
  const { Icon, spin, tone, title, hint } = placeholderFor(connection, status);
  const toneClass =
    tone === "warning" ? "text-warning" : "text-muted-foreground";
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 text-center">
      <Icon
        size={26}
        className={`${toneClass} ${spin ? "animate-spin" : ""}`}
      />
      <p className={`text-sm ${toneClass}`}>{title}</p>
      {hint && <p className="text-xs text-muted-foreground/70">{hint}</p>}
    </div>
  );
}

/** 接管生命周期（本地态，区别于服务端 live 三态；接管态**不走 live 通道**）。 */
type TakeoverPhase = "idle" | "starting" | "active" | "ending";

export function BrowserLivePanel({
  conversationId,
}: {
  conversationId: string;
}) {
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<BrowserLiveState | null>(null);
  const [connection, setConnection] =
    useState<BrowserLiveConnection>("connecting");
  const [takeover, setTakeover] = useState<TakeoverPhase>("idle");
  const [takeoverError, setTakeoverError] = useState<string | null>(null);
  // Track the live object URL outside React state so the cleanup / next-frame swap can
  // revoke the previous one synchronously (state is async, and a stale closure would leak).
  const frameUrlRef = useRef<string | null>(null);
  // Latest frame's pixel dimensions — the coordinate space input events must map into.
  const frameDimRef = useRef<{ width: number; height: number } | null>(null);

  // Takeover-only refs (read at DOM-event time, so kept out of React state).
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const batcherRef = useRef<InputBatcher | null>(null);
  const draggingRef = useRef(false);
  const composingRef = useRef(false);
  const takeoverActiveRef = useRef(false);
  const takeoverStartRef = useRef<string | null>(null);

  useEffect(() => {
    const client = startBrowserLive(conversationId, {
      onFrame: (frame) => {
        frameDimRef.current = { width: frame.width, height: frame.height };
        const next = URL.createObjectURL(
          base64ToBlob(frame.frame_b64, "image/jpeg"),
        );
        const prev = frameUrlRef.current;
        frameUrlRef.current = next;
        setFrameUrl(next);
        // 换帧即回收上一帧：旧帧已绘制、<img> 已切到新 src，旧 objectURL 无人再引用 → revoke 防泄漏。
        if (prev) URL.revokeObjectURL(prev);
      },
      onStatus: setStatus,
      onConnection: setConnection,
    });
    return () => {
      client.stop();
      if (frameUrlRef.current) {
        URL.revokeObjectURL(frameUrlRef.current);
        frameUrlRef.current = null;
      }
    };
  }, [conversationId]);

  // Core收口：停批处理 + 尽力 end（幂等）+ 把本场接管乐观并入 store（时间线标记卡即时可见）。
  // 不碰 React state，故可安全用于卸载/会话结束/按钮各路径。仅在确实持有控制时执行一次。
  const endTakeoverCore = useCallback(() => {
    if (!takeoverActiveRef.current) return;
    const startedAt = takeoverStartRef.current;
    takeoverActiveRef.current = false;
    takeoverStartRef.current = null;
    draggingRef.current = false;
    batcherRef.current?.stop();
    batcherRef.current = null;
    void endBrowserTakeover(conversationId).catch(() => {});
    if (startedAt) {
      useBrowserTakeoverStore
        .getState()
        .addLocal(conversationId, startedAt, new Date().toISOString());
    }
  }, [conversationId]);

  // 归还控制（按钮 / 会话结束自动）：收口 + 复位可见态。
  const returnControl = useCallback(() => {
    if (!takeoverActiveRef.current) return;
    setTakeover("ending");
    endTakeoverCore();
    setTakeover("idle");
    setTakeoverError(null);
  }, [endTakeoverCore]);

  const beginTakeover = useCallback(async () => {
    setTakeoverError(null);
    setTakeover("starting");
    try {
      await startBrowserTakeover(conversationId);
      takeoverStartRef.current = new Date().toISOString();
      takeoverActiveRef.current = true;
      batcherRef.current = createInputBatcher((events) =>
        sendBrowserInput(conversationId, events),
      );
      setTakeover("active");
    } catch (err) {
      // start 失败（turn_running / no_session / already_active …）→ 复位 + 显因。
      setTakeover("idle");
      setTakeoverError(takeoverStartErrorMessage(err));
    }
  }, [conversationId]);

  // 会话结束时若仍在接管 → 自动归还（服务端会话已亡，end 幂等无副作用）。
  useEffect(() => {
    if (status === "session_closed" && takeoverActiveRef.current) {
      returnControl();
    }
  }, [status, returnControl]);

  // 接管激活即把焦点落到交互面，键盘事件才有归属。
  useEffect(() => {
    if (takeover === "active") surfaceRef.current?.focus();
  }, [takeover]);

  // 卸载时尽力 end（D16）——面板被切走 / 换会话（key 重建）都会触发。
  useEffect(() => {
    return () => endTakeoverCore();
  }, [endTakeoverCore]);

  // ---- 输入捕获（仅接管激活时挂到交互面）→ 换算帧空间 → 攒批 ----------------
  const pushMouse = (
    type: "down" | "up" | "move" | "wheel",
    e: { clientX: number; clientY: number },
    extra?: {
      button?: number;
      delta_x?: number;
      delta_y?: number;
      click_count?: number;
    },
  ): void => {
    const batcher = batcherRef.current;
    const dim = frameDimRef.current;
    const el = surfaceRef.current;
    if (!batcher || !dim || !el) return;
    const rect = el.getBoundingClientRect();
    const { x, y } = toFrameSpace(
      e.clientX,
      e.clientY,
      rect,
      dim.width,
      dim.height,
    );
    batcher.push({ kind: "mouse", type, x, y, ...extra });
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>): void => {
    e.preventDefault();
    surfaceRef.current?.focus();
    draggingRef.current = true;
    try {
      surfaceRef.current?.setPointerCapture(e.pointerId);
    } catch {
      /* capture unsupported — dragging still tracked via ref */
    }
    pushMouse("down", e, { button: e.button, click_count: 1 });
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>): void => {
    // 仅拖拽时发送 move（避免悬停洪泛，D16）；批处理器再就地合并连续 move。
    if (!draggingRef.current) return;
    pushMouse("move", e);
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>): void => {
    draggingRef.current = false;
    try {
      surfaceRef.current?.releasePointerCapture(e.pointerId);
    } catch {
      /* nothing captured */
    }
    pushMouse("up", e, { button: e.button });
  };

  const onPointerCancel = (): void => {
    draggingRef.current = false;
  };

  const onWheel = (e: ReactWheelEvent<HTMLDivElement>): void => {
    pushMouse("wheel", e, { delta_x: e.deltaX, delta_y: e.deltaY });
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (composingRef.current) return; // IME 组合中 → 交给 compositionend 兜底
    e.preventDefault();
    batcherRef.current?.push({
      kind: "key",
      type: "down",
      key: e.key,
      code: e.code,
      modifiers: modifiersOf(e),
    });
  };

  const onKeyUp = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (composingRef.current) return;
    e.preventDefault();
    batcherRef.current?.push({
      kind: "key",
      type: "up",
      key: e.key,
      code: e.code,
      modifiers: modifiersOf(e),
    });
  };

  const onCompositionStart = (): void => {
    composingRef.current = true;
  };

  const onCompositionEnd = (
    e: React.CompositionEvent<HTMLDivElement>,
  ): void => {
    composingRef.current = false;
    // IME/组合输入兜底：只灌最终合成文本，不逐键上报（不缓存键入内容，守 D7）。
    if (e.data) batcherRef.current?.push({ kind: "text", text: e.data });
  };

  // 有帧且非「无直播」→ 放画面（会话结束时保留最后一帧、叠加结束提示；重连时保留最后一帧、叠加重连提示）。
  const showFrame = frameUrl !== null && status !== "no_session";
  const isLive =
    showFrame && status !== "session_closed" && connection === "open";
  // 可接管：有活直播（started 且有帧、传输在线）（D16）。
  const canTakeover =
    showFrame && status === "started" && connection === "open";
  const isTakingOver = takeover === "active" || takeover === "ending";

  return (
    <div className="flex h-full flex-col bg-muted/20">
      {isTakingOver ? (
        // 显著「接管中」状态条（D16）：品牌蓝，含「归还控制」。
        <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-primary/30 bg-primary/10 px-3 text-xs">
          <Hand size={13} className="shrink-0 text-primary" />
          <span className="font-medium text-primary">
            接管中 · 你正在操作浏览器
          </span>
          <button
            type="button"
            onClick={returnControl}
            className="ml-auto shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            归还控制
          </button>
        </div>
      ) : (
        <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border px-3 text-xs">
          <Radio
            size={13}
            className={`shrink-0 ${isLive ? "text-primary" : "text-muted-foreground/50"}`}
          />
          <span
            className={isLive ? "text-foreground" : "text-muted-foreground"}
          >
            {isLive ? "直播中" : "浏览器直播"}
          </span>
          {takeover === "starting" ? (
            <span className="ml-auto flex shrink-0 items-center gap-1 text-muted-foreground">
              <Loader2 size={12} className="animate-spin" /> 正在接管…
            </span>
          ) : (
            canTakeover && (
              <button
                type="button"
                onClick={() => void beginTakeover()}
                className="ml-auto flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/15"
              >
                <Hand size={12} className="shrink-0" />
                接管
              </button>
            )
          )}
        </div>
      )}

      {takeoverError && (
        <div className="flex shrink-0 items-center gap-1.5 border-b border-destructive/30 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
          <MonitorOff size={13} className="shrink-0" />
          {takeoverError}
        </div>
      )}

      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden p-2">
        {showFrame && frameUrl ? (
          isTakingOver ? (
            <div
              ref={surfaceRef}
              // biome-ignore lint/a11y/noNoninteractiveTabindex: a remote-control surface must be focusable to capture keyboard input injected into the sandbox browser; there is no semantic element for "proxy the user's device input to another screen".
              tabIndex={0}
              aria-label="接管中的浏览器画面（点击 / 键入 / 滚动即操作远端）"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerCancel}
              onWheel={onWheel}
              onKeyDown={onKeyDown}
              onKeyUp={onKeyUp}
              onCompositionStart={onCompositionStart}
              onCompositionEnd={onCompositionEnd}
              className="flex h-full w-full cursor-crosshair items-center justify-center outline-none ring-2 ring-primary/40 ring-inset"
            >
              <img
                src={frameUrl}
                alt="浏览器直播画面"
                draggable={false}
                className="pointer-events-none max-h-full max-w-full select-none object-contain"
              />
            </div>
          ) : (
            <>
              <img
                src={frameUrl}
                alt="浏览器直播画面"
                className={`max-h-full max-w-full object-contain ${
                  status === "session_closed" ? "opacity-60" : ""
                }`}
              />
              {status === "session_closed" && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-center gap-1.5 bg-background/80 py-1.5 text-xs text-muted-foreground">
                  <MonitorOff size={13} /> 直播已结束
                </div>
              )}
              {status !== "session_closed" && connection === "reconnecting" && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-center gap-1.5 bg-background/80 py-1.5 text-xs text-warning">
                  <WifiOff size={13} /> 连接已断开，正在重连…
                </div>
              )}
            </>
          )
        ) : (
          <LivePlaceholder connection={connection} status={status} />
        )}
      </div>
    </div>
  );
}
