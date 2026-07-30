import { ConversationRoute } from "@/components/chat/ConversationRoute";
import { AppShell } from "@/components/layout/AppShell";
import { RouteError } from "@/components/layout/RouteError";
import { AskCommencePreviewPage } from "@/pages/AskCommencePreviewPage";
import { CapabilityPacksPreviewPage } from "@/pages/CapabilityPacksPreviewPage";
import { ConversationsPage } from "@/pages/ConversationsPage";
import { ConversationsPreviewPage } from "@/pages/ConversationsPreviewPage";
import { FilesPage } from "@/pages/FilesPage";
import { MessagesPage } from "@/pages/MessagesPage";
import { MorePage } from "@/pages/MorePage";
import { OnboardingPreviewPage } from "@/pages/OnboardingPreviewPage";
import { PreviewPage } from "@/pages/PreviewPage";
import { ToolboxPage } from "@/pages/ToolboxPage";
import { TurnDetailPage } from "@/pages/TurnDetailPage";
import { WhiteboardCanvasPage } from "@/pages/WhiteboardCanvasPage";
import { WhiteboardPage } from "@/pages/WhiteboardPage";
import { WhiteboardPreviewPage } from "@/pages/WhiteboardPreviewPage";
import { LegalSettingsPage } from "@/pages/legal/LegalSettingsPage";
import { AboutSettings } from "@/pages/more/AboutSettings";
import { AccountSettings } from "@/pages/more/AccountSettings";
import { AppearanceSettings } from "@/pages/more/AppearanceSettings";
import { FeedbackSettings } from "@/pages/more/FeedbackSettings";
import { ImPrivacySettings } from "@/pages/more/ImPrivacySettings";
import { ModelSettings } from "@/pages/more/ModelSettings";
import { MoreIndexRedirect } from "@/pages/more/MoreIndexRedirect";
import { ProviderSettings } from "@/pages/more/ProviderSettings";
import { RedirectToOfficialChat } from "@/pages/more/RedirectToOfficialChat";
import { ShortcutsSettings } from "@/pages/more/ShortcutsSettings";
import { UsageSettings } from "@/pages/more/UsageSettings";
import { TownLauncherPage } from "@/pages/simulation/TownLauncherPage";
import { GuidelinesPage } from "@/pages/toolbox/GuidelinesPage";
import { ToolsPage } from "@/pages/toolbox/ToolsPage";
import {
  AutomationsPage,
  InboxPanel,
  StandingTasksPanel,
} from "@/pages/toolbox/automations";
import {
  ManualCollaboration,
  ManualIntro,
  ManualMechanism,
  ManualReference,
  ManualShell,
} from "@/pages/toolbox/manual";
import { APP_PATHS } from "@/pages/toolbox/manual/paths";
import { Navigate, createHashRouter } from "react-router-dom";

export const router = createHashRouter([
  {
    path: "/",
    element: <AppShell />,
    // Catches both an unmatched path (404) and any error thrown while rendering a
    // child route, so the user lands on an app-styled page instead of React
    // Router's bare default. Errors bubble to this nearest boundary.
    errorElement: <RouteError />,
    children: [
      {
        element: <ConversationRoute />,
        children: [{ index: true }, { path: "conversations/:id" }],
      },
      {
        path: "conversations/:id/turn/:turnId",
        element: <TurnDetailPage />,
      },
      { path: "conversations", element: <ConversationsPage /> },
      { path: "files", element: <FilesPage /> },
      { path: "whiteboard", element: <WhiteboardPage /> },
      { path: "whiteboard/:boardId", element: <WhiteboardCanvasPage /> },
      { path: "messages", element: <MessagesPage /> },
      { path: "messages/:chatId", element: <MessagesPage /> },
      { path: "toolbox", element: <ToolboxPage /> },
      { path: "toolbox/tools", element: <ToolsPage /> },
      { path: "toolbox/guidelines", element: <GuidelinesPage /> },
      {
        path: "toolbox/automations",
        element: <AutomationsPage />,
        children: [
          { index: true, element: <StandingTasksPanel /> },
          { path: "inbox", element: <InboxPanel /> },
        ],
      },
      {
        path: "toolbox/manual",
        element: <ManualShell />,
        children: [
          { index: true, element: <Navigate to="intro" replace /> },
          { path: "intro", element: <ManualIntro /> },
          { path: "collaboration", element: <ManualCollaboration /> },
          { path: "mechanism", element: <ManualMechanism /> },
          { path: "reference", element: <ManualReference /> },
        ],
      },
      // Day2 公共市场未落地：旧书签 #/explore 收向工具箱，避免「即将上线」空壳。
      { path: "explore", element: <Navigate to="/toolbox" replace /> },
      // 设置侧「自动化」已迁到工具箱；旧书签深链重定向。
      {
        path: "more/automations",
        element: <Navigate to={APP_PATHS.toolbox.automations.root} replace />,
      },
      {
        path: "more/inbox",
        element: <Navigate to={APP_PATHS.toolbox.automations.inbox} replace />,
      },
      // 产品公告 inbox 已迁 IM 官方号；旧书签 / 手册路径收向消息页。
      { path: "more/notices", element: <RedirectToOfficialChat /> },
      // Hidden dev route — not in the nav; reach it by typing #/preview. Replays
      // committed conformance vectors through the real dispatch to eyeball every AI
      // state offline (no backend / LLM). See preview/replay.ts.
      { path: "preview", element: <PreviewPage /> },
      // Companion offline preview for the self-built whiteboard canvas (a scene surface, not an
      // SSE vector — see preview/whiteboardScenes.ts + scripts/shoot-whiteboard.mjs).
      { path: "preview/whiteboard", element: <WhiteboardPreviewPage /> },
      // Preview 开工提案 layout A/B (V2 = production kickoff default).
      { path: "preview/ask-commence", element: <AskCommencePreviewPage /> },
      // Preview 首启体验（草稿空态两态 + composer 生成中插话态）.
      { path: "preview/onboarding", element: <OnboardingPreviewPage /> },
      // Preview 全部对话管理页（时间线列表 · mock 数据离线自检）.
      { path: "preview/conversations", element: <ConversationsPreviewPage /> },
      // Preview 能力包两态（工具箱 AI 提示词 · mock 数据离线自检）.
      {
        path: "preview/capability-packs",
        element: <CapabilityPacksPreviewPage />,
      },
      // DT-01: Desktop launcher only (spawn AgentTown.exe + session.json).
      { path: "simulation/town", element: <TownLauncherPage /> },
      {
        path: "more",
        element: <MorePage />,
        children: [
          // Opening 设置：platform / 已有平台或服务商 → 模型；byok 空接 → 服务商。
          { index: true, element: <MoreIndexRedirect /> },
          { path: "model", element: <ModelSettings /> },
          { path: "providers", element: <ProviderSettings /> },
          { path: "account", element: <AccountSettings /> },
          { path: "messages", element: <ImPrivacySettings /> },
          { path: "usage", element: <UsageSettings /> },
          { path: "appearance", element: <AppearanceSettings /> },
          { path: "shortcuts", element: <ShortcutsSettings /> },
          { path: "feedback", element: <FeedbackSettings /> },
          { path: "about", element: <AboutSettings /> },
          { path: "legal/:docId", element: <LegalSettingsPage /> },
        ],
      },
    ],
  },
]);
