import { ChatView } from "@/components/chat/ChatView";
import { ConversationCanvas } from "@/components/graph/ConversationCanvas";
import { SidePanel } from "@/components/layout/SidePanel";
import { ScenarioList } from "@/components/preview/ScenarioList";
import { Button } from "@/components/ui";
import { applyTheme } from "@/lib/theme";
import { useIsDark } from "@/lib/useIsDark";
import { PREVIEW_FIXTURES } from "@/preview/fixtures";
import {
  replayFixtureNow,
  replayFixturePrefix,
  replayFixtureStreamed,
} from "@/preview/replay";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { useUIStore } from "@/stores/ui";
import { MessageSquare, Moon, Network, Play, Radio, Sun } from "lucide-react";
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

const convIdFor = (name: string) => `preview-${name}`;

/**
 * Hidden dev route (`#/preview`) for eyeballing every AI state offline. Each entry
 * is a committed conformance vector replayed through the real SSE dispatch into the
 * real ChatView — no backend, no LLM, no tokens. Reachable by typing the URL; not
 * in the nav.
 */
export function PreviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const cancelRef = useRef<(() => void) | null>(null);

  // Scenario selection is URL-driven (`#/preview?s=<name>`) so the screenshot
  // harness (scripts/shoot.mjs) can deep-link each scenario deterministically and
  // humans can bookmark one. Fall back to the first fixture so the pane is never
  // empty.
  const scenarios = PREVIEW_FIXTURES;

  const requested = searchParams.get("s");
  const current =
    scenarios.find((s) => s.name === requested) ?? scenarios[0] ?? null;
  const selected = current?.name ?? null;

  // Mid-stream frame index (`#/preview?s=…&k=<n>`): replay only the first n events
  // instead of the terminal state. Drives the harness's streaming frame scrubber;
  // null = full/terminal. Invalid / ≤0 → treated as full.
  const frameRaw = searchParams.get("k");
  const parsedFrame =
    frameRaw === null ? Number.NaN : Number.parseInt(frameRaw, 10);
  const frame =
    Number.isFinite(parsedFrame) && parsedFrame > 0 ? parsedFrame : null;

  // Total replayable events in the current scenario → the scrubber's right end
  // (terminal state). The slider spans 1…total; landing on total drops `k` so the
  // URL collapses back to the canonical terminal form the harness screenshots.
  const total = current?.events.length ?? 0;

  // Render surface (`#/preview?s=…&view=canvas`): chat (default) replays into
  // `ChatView`; canvas mounts the real canvas layout (`ConversationCanvas` +
  // `SidePanel`) so the canvas-only chrome — the team graph and the 指挥台
  // fixed tab in the side panel (前端UX设计.md §6.2) — is eyeball-able
  // and shoot-gated too, not just the chat surface. URL-driven so the harness can
  // deep-link it and a human can bookmark it.
  const view = searchParams.get("view") === "canvas" ? "canvas" : "chat";

  // Deep-link into a canvas 放大态 view (`#/preview?s=…&view=canvas&zoom=<view>`): after
  // the fixture replays, request canvas focus on the team turn so a zoomed view that is
  // otherwise only reachable by clicking (e.g. 对比) is deep-linkable + shoot-gatable.
  // `zoom=compare` (旧别名 `revisions`) → 统一「对比」view; any other truthy value → the
  // turn's default view.
  const zoom = searchParams.get("zoom");

  // Render theme (`#/preview?s=…&theme=light|dark`): an ephemeral light/dark
  // override for the preview surface so a component can be eyeballed in both modes
  // without flipping (or persisting) the whole app's theme. URL-driven like
  // `s` / `k` / `view` so it's deep-linkable and survives selection / scrubbing.
  // Absent → follow the app's real theme (`useApplyTheme` keeps owning it).
  const themeParam =
    searchParams.get("theme") === "dark"
      ? "dark"
      : searchParams.get("theme") === "light"
        ? "light"
        : null;
  const appIsDark = useIsDark();
  const isDark = themeParam ? themeParam === "dark" : appIsDark;

  // Preserve the current view + theme across selection / scrubbing so flipping a
  // scenario or dragging the frame slider doesn't kick canvas back to chat or drop
  // the chosen preview theme.
  const withChrome = (params: Record<string, string>) => {
    const next: Record<string, string> = { ...params };
    if (view === "canvas") next.view = view;
    if (themeParam) next.theme = themeParam;
    return next;
  };

  const stopStreamed = () => {
    cancelRef.current?.();
    cancelRef.current = null;
  };

  const select = (name: string) => {
    setSearchParams(withChrome({ s: name }), { replace: true });
  };

  const setView = (next: "chat" | "canvas") => {
    const params: Record<string, string> = {};
    if (selected) params.s = selected;
    if (frame !== null) params.k = String(frame);
    if (next === "canvas") params.view = next;
    if (themeParam) params.theme = themeParam;
    setSearchParams(params, { replace: true });
  };

  // Flip the preview surface light/dark via the URL. Ephemeral: it overrides the
  // root `.dark` class while previewing but never writes the persisted app theme,
  // and preserves the current scenario / frame / view.
  const setTheme = (next: "light" | "dark") => {
    const params: Record<string, string> = {};
    if (selected) params.s = selected;
    if (frame !== null) params.k = String(frame);
    if (view === "canvas") params.view = view;
    params.theme = next;
    setSearchParams(params, { replace: true });
  };

  // Drag the scrubber → rewrite `?k=`. At/over the right end we drop `k` entirely
  // (terminal). The URL stays the single source of truth: the effect below re-replays
  // the prefix and data-preview-frame updates, so the screenshot harness and a human
  // scrubbing land on the exact same frame.
  const setFrame = (value: number) => {
    if (!selected) return;
    if (value >= total) {
      setSearchParams(withChrome({ s: selected }), { replace: true });
    } else {
      setSearchParams(
        withChrome({ s: selected, k: String(Math.max(1, value)) }),
        { replace: true },
      );
    }
  };

  const replayNow = () => {
    if (!current) return;
    stopStreamed();
    replayFixtureNow(
      convIdFor(current.name),
      current.events,
      current.description,
    );
  };

  const playStreamed = () => {
    if (!current) return;
    stopStreamed();
    cancelRef.current = replayFixtureStreamed(
      convIdFor(current.name),
      current.events,
      current.description,
    );
  };

  // Replay on selection / frame change (driven by the URL `?s=` + `?k=` params):
  // a frame index replays only the first k events (mid-stream), otherwise the full
  // terminal state. Kept free of component-scope closures — it talks to the cancel
  // ref directly and re-looks up the fixture — so the dep array is honestly exhaustive.
  useEffect(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    const sc = scenarios.find((s) => s.name === selected);
    if (sc) {
      const cid = convIdFor(sc.name);
      if (frame !== null) {
        replayFixturePrefix(cid, sc.events, frame, sc.description);
      } else {
        replayFixtureNow(cid, sc.events, sc.description);
      }
    }
    return () => {
      cancelRef.current?.();
      cancelRef.current = null;
    };
  }, [selected, frame, scenarios]);

  // Drop the synthetic slice when leaving so it never lingers as the active
  // conversation.
  useEffect(() => {
    return () => {
      useConversationStore.getState().switchConversation(null);
    };
  }, []);

  // After replay lands, honor `?zoom=` — production uses turn-detail route;
  // preview still calls the UI-store stub until preview is rewired.
  // biome-ignore lint/correctness/useExhaustiveDependencies: frame is an intentional re-run key — re-focus after each replay frame lands.
  useEffect(() => {
    if (view !== "canvas" || !zoom || !selected) return;
    const focusView =
      zoom === "compare" || zoom === "revisions" ? "compare" : undefined;
    const t = setTimeout(() => {
      const msgs = getRuntime(convIdFor(selected)).messages;
      const turn =
        [...msgs].reverse().find((m) => m.executionId != null) ??
        [...msgs].reverse().find((m) => m.role === "assistant");
      if (turn) {
        useUIStore.getState().requestCanvasFocus(turn.id, false, focusView);
      }
    }, 120);
    return () => clearTimeout(t);
  }, [view, zoom, selected, frame]);

  // Apply the URL-selected preview theme by toggling the root `.dark` class (the
  // same mechanism as the app's `applyTheme`), so the replayed surface — and
  // theme-sensitive renderers like mermaid that read `.dark` off the root — flip
  // exactly as in a real dark-mode session. Only overrides while `?theme=` is set;
  // restores the app's persisted theme on change / unmount so the user's saved
  // preference is never clobbered.
  useEffect(() => {
    if (!themeParam) return;
    applyTheme(themeParam);
    return () => {
      applyTheme(useUIStore.getState().theme);
    };
  }, [themeParam]);

  return (
    <div
      className="flex h-full min-h-0"
      data-preview-scenario={selected ?? ""}
      data-preview-frame={frame !== null ? String(frame) : "full"}
    >
      <ScenarioList
        fixtures={PREVIEW_FIXTURES}
        selected={selected}
        onSelect={select}
      />

      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-3 border-b border-border px-4 py-2">
          <div className="min-w-0 shrink">
            <p className="truncate text-sm font-medium text-foreground">
              {current?.name ?? "选择一个场景"}
            </p>
            {current && (
              <p className="truncate text-xs text-muted-foreground">
                {current.description}
              </p>
            )}
          </div>
          {/* Frame scrubber pulled inline so a single control bar carries title +
              scrubbing + actions; falls back to a spacer (keeps the actions
              right-aligned) when the scenario has no mid-stream frames to scrub. */}
          {current && total > 1 ? (
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span className="shrink-0 text-xs font-medium text-muted-foreground">
                帧
              </span>
              <input
                type="range"
                min={1}
                max={total}
                step={1}
                value={frame ?? total}
                onChange={(e) => setFrame(Number(e.target.value))}
                className="h-1 min-w-16 flex-1 cursor-pointer accent-primary"
                aria-label="流式中间帧 scrubber"
              />
              <span className="shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                {frame !== null
                  ? `第 ${frame} / ${total} 事件`
                  : `终态 · ${total} 事件`}
              </span>
              {frame !== null && (
                <button
                  type="button"
                  onClick={() => setFrame(total)}
                  className="shrink-0 text-xs font-medium text-primary hover:underline"
                >
                  回终态
                </button>
              )}
            </div>
          ) : (
            <div className="flex-1" />
          )}
          {current && (
            <div className="flex shrink-0 items-center gap-1.5">
              {/* Merged segmented control: 聊天⇄画布 (render surface) + 浅⇄深
                  (ephemeral preview theme) share one divider-split container so the
                  chrome reads as a single compact control. Both flip the SAME
                  replayed slice — the canvas-only state (team graph + 指挥台) and
                  either theme — without spinning up a real run or touching the
                  app's persisted theme. */}
              <div className="mr-1 flex items-center gap-0.5 rounded-lg border border-border p-0.5">
                <Button
                  variant="ghost"
                  onClick={() => setView("chat")}
                  aria-pressed={view === "chat"}
                  icon={<MessageSquare size={14} />}
                  className={
                    view === "chat"
                      ? "bg-accent text-foreground hover:bg-accent"
                      : undefined
                  }
                >
                  聊天
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => setView("canvas")}
                  aria-pressed={view === "canvas"}
                  icon={<Network size={14} />}
                  className={
                    view === "canvas"
                      ? "bg-accent text-foreground hover:bg-accent"
                      : undefined
                  }
                >
                  画布
                </Button>
                <span className="mx-0.5 h-5 w-px shrink-0 bg-border" />
                <Button
                  variant="ghost"
                  onClick={() => setTheme("light")}
                  aria-pressed={!isDark}
                  aria-label="浅色预览"
                  icon={<Sun size={14} />}
                  className={
                    !isDark
                      ? "bg-accent text-foreground hover:bg-accent"
                      : undefined
                  }
                />
                <Button
                  variant="ghost"
                  onClick={() => setTheme("dark")}
                  aria-pressed={isDark}
                  aria-label="深色预览"
                  icon={<Moon size={14} />}
                  className={
                    isDark
                      ? "bg-accent text-foreground hover:bg-accent"
                      : undefined
                  }
                />
              </div>
              <Button
                variant="neutral"
                onClick={replayNow}
                icon={<Play size={14} />}
              >
                重放
              </Button>
              <Button
                variant="neutral"
                onClick={playStreamed}
                icon={<Radio size={14} />}
              >
                流式重放
              </Button>
            </div>
          )}
        </div>
        {view === "canvas" ? (
          // Mirror ConversationPage's canvas layout: the canvas takes the main
          // column and the unified SidePanel docks on the right (where the 指挥台
          // is a fixed second tab; auto-surface = openPanel + badge, no tab steal).
          <div className="relative flex min-h-0 flex-1">
            <ConversationCanvas />
            <SidePanel />
          </div>
        ) : (
          <div className="relative flex min-h-0 flex-1 flex-col">
            <ChatView />
          </div>
        )}
      </div>
    </div>
  );
}
