import { registerConversationUiClearer, uiGet, uiSet } from "@/lib/uiStorage";
import { create } from "zustand";

const DIAGNOSTIC_MODE_KEY = "diagnostic-mode";
const THEME_KEY = "theme";
const SIDECAR_KEY = "sidecar-enabled";
const CONVERSATION_VIEWS_KEY = "conversation-views";

type Theme = "light" | "dark" | "system";

// 开发者 / 诊断模式 (前端UX设计.md §十): off by default.
function loadDiagnosticMode(): boolean {
  return uiGet<boolean>(DIAGNOSTIC_MODE_KEY) === true;
}

function persistDiagnosticMode(v: boolean): void {
  uiSet(DIAGNOSTIC_MODE_KEY, v);
}

// 每对话的视图偏好（聊天 ⇄ 画布，前端UX设计.md §六）。只存「切到画布」的对话——聊天是
// 默认、不落键，故这张表恒收敛在用户偏好画布的那批对话上（守原「不无限增长」约束）。
function loadConversationViews(): Record<string, "chat" | "canvas"> {
  const parsed = uiGet<Record<string, unknown>>(CONVERSATION_VIEWS_KEY);
  if (!parsed || typeof parsed !== "object") return {};
  const out: Record<string, "chat" | "canvas"> = {};
  for (const [id, mode] of Object.entries(parsed)) {
    if (mode === "canvas") out[id] = "canvas";
  }
  return out;
}

function persistConversationViews(
  views: Record<string, "chat" | "canvas">,
): void {
  if (Object.keys(views).length === 0) uiSet(CONVERSATION_VIEWS_KEY, undefined);
  else uiSet(CONVERSATION_VIEWS_KEY, views);
}

// Theme is persisted so the choice survives a reload; it is *applied* to the DOM
// by lib/theme.ts (the store only holds the value). Falls back to 跟随系统.
function loadTheme(): Theme {
  const v = uiGet<string>(THEME_KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "system";
}

function persistTheme(v: Theme): void {
  uiSet(THEME_KEY, v);
}

// 本地引擎（sidecar）开关——三态偏好（双模式工作区 §一.1 / 本地引擎毕业方案 · 阶段三）。
//
// 为「毕业到默认开」铺路：必须区分「用户从未设过」与「用户显式关过」，否则把默认翻成开时会误
// 开那些主动关掉的人。故持久化的是**偏好**而非有效值：
//   - "unset"（无 key）→ 跟随 `SIDECAR_DEFAULT_ENABLED`（用户没表态，由产品默认决定）；
//   - "on" / "off" → 用户显式选择，恒被尊重，不受默认值变化影响。
// 有效开关 = `resolveSidecarEnabled(偏好)`，消费方（sidecarRouting）只读那个 boolean。
type SidecarPreference = "unset" | "on" | "off";

/** 本地引擎默认是否开启（用户未表态时）。已毕业到**默认开**：绑定本机本地文件夹的对话默认走
 * 本地引擎（启动失败会自动降级回云端，故默认开是安全的，见 `turns.sendTurn`）；"unset" 用户
 * 跟随此默认，显式 "on"/"off" 用户不受影响。需回退为 opt-in 时改回 false 即可。 */
const SIDECAR_DEFAULT_ENABLED = true;

function loadSidecarPreference(): SidecarPreference {
  const v = uiGet<string>(SIDECAR_KEY);
  if (v === "on") return "on";
  if (v === "off") return "off";
  return "unset";
}

function persistSidecarPreference(p: "on" | "off"): void {
  uiSet(SIDECAR_KEY, p);
}

/** 有效开关值：未表态时取产品默认，否则取用户显式选择。 */
function resolveSidecarEnabled(pref: SidecarPreference): boolean {
  return pref === "unset" ? SIDECAR_DEFAULT_ENABLED : pref === "on";
}

function loadSidecarEnabled(): boolean {
  return resolveSidecarEnabled(loadSidecarPreference());
}

interface UIState {
  searchOpen: boolean;
  /** Prefill for the next palette open; consumed on open. */
  searchInitialQuery: string;
  /** Open directly in the bookmarks facet (命令面板「已收藏」); consumed on open. */
  searchInitialBookmarks: boolean;
  theme: Theme;
  /** 开发者 / 诊断模式 (前端UX设计.md §十). When true, low-level execution
   * diagnostics (run / trace ids、调度埋点等) surface in run detail — dev-only
   * noise kept off the 大众 path. 「复制排查包」(错误卡 / 气泡更多) 不依赖本开关。
   * Persisted via uiStorage (`agentcore:diagnostic-mode`). */
  diagnosticMode: boolean;
  /** 每对话的视图模式（聊天 ⇄ 画布双视图，前端UX设计.md §六）。默认聊天（`"chat"`），
   * 用户可在对话顶栏切到画布（`"canvas"`）。画布已毕业（无实验开关），入口恒显示。
   * **持久化**到 `agentcore:conversation-views`，但只落「切到画布」的对话（切回聊天
   * 即删键）→ 表恒收敛、不无限增长；未表态 / 草稿（无 id）恒为聊天。 */
  conversationViews: Record<string, "chat" | "canvas">;
  /** 本地引擎（sidecar）**有效**开关（双模式工作区 §一.1）：= `resolveSidecarEnabled(偏好)`，
   * 消费方（路由）只读这个 boolean。开启后，绑定本机本地文件夹的对话由用户机器上的
   * `python -m agentcore.sidecar` 跑（直连本地盘），而非云端引擎遥控桌面；裸聊 / 云端项目 /
   * 带附件的回合仍走云。**默认开**、可关闭——启动失败自动降级回云端（故默认开安全）；但 sidecar
   * 暂非真离线（LLM 仍经云推理代理），断网时不可用。 */
  sidecarEnabled: boolean;
  /** 本地引擎开关的**持久化偏好**（三态）：`unset` 跟随 `SIDECAR_DEFAULT_ENABLED`、`on`/`off` 为
   * 用户显式选择——为「毕业到默认开」铺路（翻默认时不误开显式关过的人）。持久化到
   * `agentcore:sidecar-enabled`；设置开关只关心 {@link sidecarEnabled}。 */
  sidecarPreference: SidecarPreference;

  openSearch: (initialQuery?: string, opts?: { bookmarks?: boolean }) => void;
  closeSearch: () => void;
  toggleSearch: () => void;
  setTheme: (theme: UIState["theme"]) => void;
  setDiagnosticMode: (v: boolean) => void;
  toggleDiagnosticMode: () => void;
  setConversationView: (
    conversationId: string,
    mode: "chat" | "canvas",
  ) => void;
  setSidecarEnabled: (v: boolean) => void;
}

/** Full-screen turn detail view (`#/conversations/:id/turn/:turnId?view=`). */
export type TurnDetailView = "graph" | "debate" | "compare";

/** Build the hash-route path for a turn's full-screen detail page. */
export function turnDetailPath(
  conversationId: string,
  turnId: string,
  view?: TurnDetailView,
  comparePair?: [string, string],
  opts?: { autoplay?: boolean },
): string {
  const path = `/conversations/${conversationId}/turn/${turnId}`;
  const params = new URLSearchParams();
  if (view) params.set("view", view);
  if (comparePair) {
    params.set("a", comparePair[0]);
    params.set("b", comparePair[1]);
  }
  if (opts?.autoplay) params.set("autoplay", "1");
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export const useUIStore = create<UIState>((set) => ({
  searchOpen: false,
  searchInitialQuery: "",
  searchInitialBookmarks: false,
  theme: loadTheme(),
  diagnosticMode: loadDiagnosticMode(),
  conversationViews: loadConversationViews(),
  sidecarPreference: loadSidecarPreference(),
  sidecarEnabled: loadSidecarEnabled(),

  // Default "" is required: Sidebar/TitleBar call openSearch() with no args.
  // Without it, searchInitialQuery becomes undefined and CommandPalette crashes
  // on query.trim() (regressed in 1ee81cee when the default was dropped).
  openSearch: (initialQuery, opts) =>
    set({
      searchOpen: true,
      searchInitialQuery: initialQuery ?? "",
      searchInitialBookmarks: opts?.bookmarks ?? false,
    }),
  closeSearch: () =>
    set({
      searchOpen: false,
      searchInitialQuery: "",
      searchInitialBookmarks: false,
    }),
  toggleSearch: () => set((s) => ({ searchOpen: !s.searchOpen })),
  setTheme: (theme) => {
    persistTheme(theme);
    set({ theme });
  },
  setDiagnosticMode: (diagnosticMode) => {
    persistDiagnosticMode(diagnosticMode);
    set({ diagnosticMode });
  },
  toggleDiagnosticMode: () =>
    set((s) => {
      const diagnosticMode = !s.diagnosticMode;
      persistDiagnosticMode(diagnosticMode);
      return { diagnosticMode };
    }),
  setConversationView: (conversationId, mode) =>
    set((s) => {
      const conversationViews = { ...s.conversationViews };
      // Chat is the default → store only canvas overrides so the persisted map
      // stays bounded (switching back to chat drops the key).
      if (mode === "canvas") conversationViews[conversationId] = "canvas";
      else delete conversationViews[conversationId];
      persistConversationViews(conversationViews);
      return { conversationViews };
    }),
  setSidecarEnabled: (sidecarEnabled) => {
    const sidecarPreference: SidecarPreference = sidecarEnabled ? "on" : "off";
    persistSidecarPreference(sidecarPreference);
    set({ sidecarEnabled, sidecarPreference });
  },
}));

registerConversationUiClearer((conversationId) => {
  const views = useUIStore.getState().conversationViews;
  if (!(conversationId in views)) return;
  const conversationViews = { ...views };
  delete conversationViews[conversationId];
  persistConversationViews(conversationViews);
  useUIStore.setState({ conversationViews });
});
