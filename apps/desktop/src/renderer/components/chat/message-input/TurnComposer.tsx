import { DraftWorkspaceAssignPrompt } from "@/components/chat/DraftWorkspaceAssignPrompt";
import { MentionMenu } from "@/components/chat/MentionMenu";
import { IconButton } from "@/components/ui";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useConversations } from "@/hooks/useConversations";
import { useFolders } from "@/hooks/useFolders";
import { useLlmProviders } from "@/hooks/useLlmProviders";
import { useModels } from "@/hooks/useModels";
import {
  COMPOSER_CONTINUE_PLACEHOLDER,
  COMPOSER_EMPTY_INTERRUPTED_HINT,
  isContinuableAssistant,
  isEmptyInterruptedAssistant,
} from "@/lib/composerContinueHint";
import { TOOLS_GATE_HINT, needsToolsGateHint } from "@/lib/llmToolsGate";
import { defaultChatSupportsTools } from "@/services/llmProviders";
import { useBackgroundTasksStore } from "@/stores/backgroundTasks";
import { draftKeyFor, useComposerDraftStore } from "@/stores/composer";
import {
  useActiveGenerating,
  useConversationStore,
} from "@/stores/conversation";
import { useFoldersStore } from "@/stores/folders";
import {
  usePendingApprovals,
  usePendingDelegations,
} from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";
import { useServerHealthStore } from "@/stores/serverHealth";
import {
  Cloud,
  CloudUpload,
  Loader2,
  Paperclip,
  Plus,
  Send,
  Square,
  X,
} from "lucide-react";
import type { SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AttachmentChips } from "./AttachmentChips";
import { ComposerContextCompactedHint } from "./ComposerContextCompactedHint";
import { ComposerNoLocalChip } from "./ComposerNoLocalChip";
import { ComposerPendingHintNotice } from "./ComposerPendingHintNotice";
import { ComposerWorkspaceChip } from "./ComposerWorkspaceChip";
import { ModelPicker } from "./ModelPicker";
import { PermissionAxesBadge } from "./PermissionPresetBadge";
import { RecordingBar } from "./RecordingBar";
import {
  ComposerConnectionNotice,
  ServerStatusIndicator,
} from "./ServerStatusIndicator";
import { VoiceButton } from "./VoiceButton";
import type { PendingAttachment } from "./composerAttachments";
import { useComposerDrop } from "./useComposerDrop";
import { useComposerSend } from "./useComposerSend";
import type { AttachmentProjectHint } from "./useMentionMenu";
import { useMentionMenu } from "./useMentionMenu";
import { useVoiceInput } from "./useVoiceInput";

const EMPTY_ATTACHMENTS: PendingAttachment[] = [];

// 输入框自增高边界：card 空/单行草稿保底 ~2 行（text-sm 20px 行高 + pt-3/pb-1 = 56px）；
// bar 默认一行高（20px 行高 + py-2 = 36px）。上限 200px 后转内部滚动。
const MIN_COMPOSER_HEIGHT_CARD = 56;
const MIN_COMPOSER_HEIGHT_BAR = 36;
const MAX_COMPOSER_HEIGHT = 200;

/** Align with backend `MessageCreate.content` max_length. */
const MESSAGE_CHAR_LIMIT = 32_000;
/** Show the counter only when the draft is near the limit (bar mode). */
const CHAR_COUNT_NEAR_LIMIT = 28_000;

export type TurnComposerVariant = "card" | "bar";

/**
 * The ONE turn composer (统一 AI 输入框): the full-featured card — auto-growing
 * textarea, @ 文件引用 + 回形针浏览, drag-drop attachments, 后台云端 toggle, 停止生成,
 * char count, 回填 channel — shared by BOTH surfaces that give the team an order:
 * the chat view's {@link import("../MessageInput").MessageInput} and the canvas
 * 命令栏 {@link import("../../graph/CanvasCommandBar").CanvasCommandBar}. 下达指令 is
 * the same act in both views, so it is the same component; hosts only pick chrome
 * (placeholder, canvas follow hook, whether 后台云端 applies).
 *
 * `variant="bar"` is the compact single-row chrome used only by the chat bottom dock;
 * default `card` keeps the full toolbar layout (center draft + canvas command bar).
 *
 * Draft state (text + attachments) lives in {@link useComposerDraftStore} keyed by
 * conversation, NOT in component state — switching 聊天 ⇄ 画布 swaps the mounted skin
 * but keeps the half-typed order, and 回填 (ask card / 下一步推荐 chips) lands in the
 * draft even across that swap. The textarea stays typable while a turn is generating
 * (queue up the next order); only sending is gated, with 停止 in the send slot.
 *
 * Draft-conversation-only concerns (workspace picker, attachment→project hint) are
 * self-gated on `!conversationId`, so they never render on the canvas (which always
 * has a conversation).
 */
export function TurnComposer({
  placeholder = "输入消息，@ 引用文件…",
  allowBackground = true,
  onDispatch,
  variant = "card",
  attachedBelowApproval = false,
}: {
  placeholder?: string;
  /** Offer the 后台云端 toggle (still requires a local-mode conversation). */
  allowBackground?: boolean;
  /** Called when a foreground turn is dispatched (canvas uses it to auto-follow). */
  onDispatch?: () => void;
  /**
   * `card` = full toolbar under the textarea (default; center draft + canvas).
   * `bar` = compact single-row input (chat bottom dock only).
   */
  variant?: TurnComposerVariant;
  /** Visually fuse with ApprovalPrompt stacked above (工具审批 A · Composer 一体). */
  attachedBelowApproval?: boolean;
}) {
  const isBar = variant === "bar";
  const minComposerHeight = isBar
    ? MIN_COMPOSER_HEIGHT_BAR
    : MIN_COMPOSER_HEIGHT_CARD;
  const isGenerating = useActiveGenerating();
  const { data: llmProviders } = useLlmProviders();
  const { data: modelCatalog } = useModels();
  const toolsGateHint = needsToolsGateHint(
    defaultChatSupportsTools(llmProviders, modelCatalog?.current?.provider_id),
  );
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const conversations = useConversations();
  const contextCompacted = Boolean(
    conversationId &&
      conversations.find((c) => c.id === conversationId)?.contextCompacted,
  );
  const hasPausedDecision = usePausedTurnStore((s) =>
    conversationId
      ? s.pending.some((p) => p.conversationId === conversationId)
      : false,
  );
  const pendingApprovals = usePendingApprovals(conversationId);
  const pendingDelegations = usePendingDelegations(conversationId);
  const lastMessage = useConversationStore((s) => {
    const id = s.currentConversationId;
    if (!id) return null;
    return s.byId[id]?.messages.at(-1) ?? null;
  });
  const showPendingHint =
    !!conversationId &&
    !isGenerating &&
    (hasPausedDecision ||
      pendingApprovals.length > 0 ||
      pendingDelegations.length > 0);
  // 空中断层 1：轻提示、无按钮；有挂起卡时优先挂起弱提示。
  const showEmptyInterruptedHint =
    !isGenerating &&
    !showPendingHint &&
    isEmptyInterruptedAssistant(lastMessage);
  const serverStatus = useServerHealthStore((s) => s.status);
  const serverUnhealthy = serverStatus === "offline";
  const resolvedPlaceholder = useMemo(() => {
    if (!isGenerating && isContinuableAssistant(lastMessage)) {
      return COMPOSER_CONTINUE_PLACEHOLDER;
    }
    return placeholder;
  }, [isGenerating, lastMessage, placeholder]);
  const draftKey = draftKeyFor(conversationId);
  const value = useComposerDraftStore((s) => s.drafts[draftKey]?.value ?? "");
  const attachments = useComposerDraftStore(
    (s) => s.drafts[draftKey]?.attachments ?? EMPTY_ATTACHMENTS,
  );
  const setValue = useCallback(
    (action: SetStateAction<string>) =>
      useComposerDraftStore.getState().setValue(draftKey, action),
    [draftKey],
  );
  const setAttachments = useCallback(
    (action: SetStateAction<PendingAttachment[]>) =>
      useComposerDraftStore.getState().setAttachments(draftKey, action),
    [draftKey],
  );

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [isLocal, setIsLocal] = useState(false);
  const [backgroundMode, setBackgroundMode] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const folders = useFolders();
  const draftIntent = useFoldersStore((s) => s.draftWorkspaceIntent);
  const pendingFolderId =
    draftIntent.kind === "project" ? draftIntent.folderId : null;
  const dismissedAssignRef = useRef<Set<string>>(new Set());
  const [assignHint, setAssignHint] = useState<AttachmentProjectHint | null>(
    null,
  );

  const handleAttachmentProjectHint = useCallback(
    (hint: AttachmentProjectHint) => {
      const store = useFoldersStore.getState();
      const intent = store.draftWorkspaceIntent;
      if (intent.kind === "project" && intent.folderId === hint.folderId) {
        return;
      }
      if (
        intent.kind !== "project" &&
        dismissedAssignRef.current.has(hint.folderId)
      ) {
        return;
      }
      setAssignHint(hint);
    },
    [],
  );

  const mention = useMentionMenu({
    conversationId,
    value,
    setValue,
    attachments,
    setAttachments,
    textareaRef,
    onAttachmentProjectHint: conversationId
      ? undefined
      : handleAttachmentProjectHint,
  });

  const drop = useComposerDrop(
    isGenerating,
    attachments,
    setAttachments,
    conversationId,
  );

  const voice = useVoiceInput({
    onTranscript: useCallback(
      (text: string) => {
        setValue((prev) => prev + text);
      },
      [setValue],
    ),
  });

  const { handleSend } = useComposerSend({
    value,
    setValue,
    attachments,
    setAttachments,
    isGenerating,
    backgroundMode,
    isLocal,
    closeMenu: mention.closeMenu,
    onDispatch,
  });

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0";
    el.style.height = `${Math.min(
      Math.max(el.scrollHeight, minComposerHeight),
      MAX_COMPOSER_HEIGHT,
    )}px`;
  }, [minComposerHeight]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: value is an intentional re-run key
  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  // 回填 focus hint: the fill's text arrives through the store subscription; the token
  // only asks the mounted composer to refocus. Seeding the ref with the current token
  // makes a remount (view switch / navigation) ignore fills that happened before it.
  const fillToken = useComposerDraftStore((s) => s.fillToken);
  const seenFillRef = useRef(fillToken);
  useEffect(() => {
    if (fillToken === seenFillRef.current) return;
    seenFillRef.current = fillToken;
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [fillToken]);

  useEffect(() => {
    if (!conversationId) {
      dismissedAssignRef.current = new Set();
    }
    setAssignHint(null);
  }, [conversationId]);

  useEffect(() => {
    if (assignHint && pendingFolderId === assignHint.folderId) {
      setAssignHint(null);
    }
  }, [assignHint, pendingFolderId]);

  const currentProjectName = pendingFolderId
    ? (folders.find((f) => f.id === pendingFolderId)?.name ?? null)
    : null;

  const acceptAssignHint = useCallback(() => {
    if (!assignHint) return;
    useFoldersStore.getState().setDraftWorkspaceIntent({
      kind: "project",
      folderId: assignHint.folderId,
    });
    setAssignHint(null);
  }, [assignHint]);

  const dismissAssignHint = useCallback(() => {
    if (!assignHint) return;
    dismissedAssignRef.current.add(assignHint.folderId);
    setAssignHint(null);
  }, [assignHint]);

  // 后台云端 gate: only local-mode conversations can hand off to a cloud team, so
  // resolve the bound mode (shared store, deduped) and show the toggle only then.
  useEffect(() => {
    if (!allowBackground || !conversationId) {
      setIsLocal(false);
      setBackgroundMode(false);
      return;
    }
    let cancelled = false;
    void useBackgroundTasksStore
      .getState()
      .ensureMode(conversationId)
      .then((mode) => {
        if (cancelled) return;
        const local = mode === "local";
        setIsLocal(local);
        if (!local) setBackgroundMode(false);
      });
    return () => {
      cancelled = true;
    };
  }, [allowBackground, conversationId]);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const text = e.target.value;
      setValue(text);
      mention.syncMention(text, e.target.selectionStart ?? text.length);
      // Soft drop errors dismiss on next edit (industry: ephemeral, not form-sticky).
      if (drop.dropError) drop.clearDropError();
    },
    [drop, mention, setValue],
  );

  const removeAttachment = useCallback(
    (id: string) => {
      setAttachments((prev) => prev.filter((a) => a.id !== id));
    },
    [setAttachments],
  );

  const stopGeneration = useCallback(() => {
    useConversationStore.getState().stopGeneration();
  }, []);

  useEffect(() => {
    if (voice.isRecording) mention.closeMenu();
  }, [voice.isRecording, mention.closeMenu]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        !(e.ctrlKey || e.metaKey) ||
        !e.shiftKey ||
        e.key.toLowerCase() !== "v"
      )
        return;
      if (!voice.isSupported) return;
      e.preventDefault();
      voice.toggle();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [voice.isSupported, voice.toggle]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing) return;

    if (voice.isRecording) {
      if (e.key === "Escape") {
        e.preventDefault();
        voice.cancel();
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        voice.stop();
        return;
      }
    }

    if (mention.menuMode && mention.handleMenuNavKey(e)) return;

    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      // 生成中强制 queue；空闲与 Enter 同路径（默认 steer），勿伪装传 queue。
      if (serverUnhealthy) return;
      void handleSend(isGenerating ? { delivery: "queue" } : undefined);
      return;
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // N4-A：离线硬禁用（与发送按钮一致；handleSend 仍有兜底）。
      if (serverUnhealthy) return;
      // P1：空闲 / 生成中默认 steer（「插入」）；强制 queue 见 Ctrl/Cmd+Enter。
      void handleSend();
    }
  };

  const charCount = value.length;
  const menuOpen = mention.menuMode !== null;
  const showBackground = allowBackground && isLocal;
  const bg = showBackground && backgroundMode;
  const showCharCount = isBar
    ? charCount >= CHAR_COUNT_NEAR_LIMIT
    : charCount > 0;

  const backgroundToggle = showBackground ? (
    <SimpleTooltip
      label={
        toolsGateHint
          ? `${TOOLS_GATE_HINT}。${
              bg
                ? "已切到「后台云端」：发送会把任务交给云端团队后台跑"
                : "切到「后台云端」：把任务交给云端团队后台跑，结果回来再应用"
            }`
          : bg
            ? "已切到「后台云端」：发送会把任务交给云端团队后台跑"
            : "切到「后台云端」：把任务交给云端团队后台跑，结果回来再应用"
      }
    >
      <IconButton
        size="md"
        onClick={() => setBackgroundMode((v) => !v)}
        disabled={isGenerating}
        aria-label="切换后台云端任务"
        aria-pressed={bg}
        className={
          bg
            ? "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary"
            : undefined
        }
      >
        <Cloud size={14} />
      </IconButton>
    </SimpleTooltip>
  ) : null;

  // 生成中：主槽位只留停止（实心）；有草稿时次要弱发送 = 插入（steer）。
  // N4-A：只读离线硬禁用发送。
  const sendBlocked = serverUnhealthy;
  const hasDraft = Boolean(value.trim());
  const interjectDisabled = !hasDraft || sendBlocked;
  const midFlightLabel = "插入";
  const midFlightHint = "插入当前回合（Enter）；Ctrl/Cmd+Enter 强制排队";
  const sendControls = isGenerating ? (
    <>
      {hasDraft ? (
        <IconButton
          size="md"
          tone="default"
          onClick={() => void handleSend()}
          disabled={interjectDisabled}
          aria-label={midFlightLabel}
          title={sendBlocked ? "离线时无法发送" : midFlightHint}
        >
          <Send size={14} />
        </IconButton>
      ) : null}
      <IconButton
        size="md"
        tone="destructive"
        onClick={stopGeneration}
        aria-label="停止生成"
        title="停止生成"
      >
        <Square size={14} />
      </IconButton>
    </>
  ) : (
    <IconButton
      size="md"
      tone="primary"
      onClick={() => void handleSend()}
      disabled={!hasDraft || sendBlocked}
      aria-label={bg ? "派发到云端后台" : "发送"}
      title={sendBlocked ? "离线时无法发送" : undefined}
    >
      {bg ? <CloudUpload size={14} /> : <Send size={14} />}
    </IconButton>
  );

  const textareaBlock = (
    <div className="relative min-w-0 flex-1">
      {voice.isRecording && voice.interimText && (
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-0 overflow-hidden text-sm whitespace-pre-wrap break-words ${
            isBar ? "px-2 py-2" : "px-4 pt-3 pb-1"
          }`}
        >
          <span className="invisible">{value}</span>
          <span className="text-foreground/40">{voice.interimText}</span>
        </div>
      )}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onPaste={drop.handlePaste}
        onSelect={(e) =>
          mention.syncMention(
            e.currentTarget.value,
            e.currentTarget.selectionStart ?? 0,
          )
        }
        placeholder={
          bg ? "描述要交给云端团队后台完成的任务…" : resolvedPlaceholder
        }
        className={`block w-full resize-none bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none ${
          isBar ? "px-2 py-2" : "px-4 pt-3 pb-1"
        }`}
        rows={isBar ? 1 : 2}
        maxLength={MESSAGE_CHAR_LIMIT}
      />
    </div>
  );

  return (
    <div
      className={`relative border bg-card shadow-sm transition-colors ${
        attachedBelowApproval
          ? "rounded-b-xl rounded-t-none border-t-0"
          : "rounded-xl"
      } ${
        drop.dragOver
          ? "border-primary ring-2 ring-primary/40"
          : "border-border"
      }`}
      onDragOver={drop.handleDragOver}
      onDragLeave={drop.handleDragLeave}
      onDrop={drop.handleDrop}
      data-composer-variant={variant}
      data-composer-attached-approval={
        attachedBelowApproval ? "true" : undefined
      }
    >
      {drop.dragOver && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-card/80 text-sm font-medium text-primary">
          拖放文件以添加为附件
        </div>
      )}
      {drop.dropError && (
        <output
          aria-live="polite"
          className="flex items-start gap-2 px-3 pt-2 text-xs text-destructive"
        >
          <span className="min-w-0 flex-1">{drop.dropError}</span>
          <button
            type="button"
            className="shrink-0 rounded-lg p-0.5 text-destructive/70 hover:bg-destructive/10 hover:text-destructive focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="关闭提示"
            onClick={drop.clearDropError}
          >
            <X size={12} />
          </button>
        </output>
      )}
      {menuOpen && (
        <MentionMenu
          items={mention.items}
          activeIndex={mention.activeIndex}
          loading={mention.indexLoading}
          error={mention.menuError}
          query={mention.query}
          showSearch={mention.menuMode === "browse"}
          noRoots={mention.indexLoadedRef.current && mention.sourceCount === 0}
          onQueryChange={mention.setQuery}
          onKeyDown={(e) => {
            mention.handleMenuNavKey(e);
          }}
          onSelect={(entry) => void mention.attachEntry(entry)}
          onHover={mention.setActiveIndex}
          onAddRoot={mention.handleAddRoot}
          searchInputRef={mention.searchInputRef}
        />
      )}

      {!conversationId && assignHint && (
        <DraftWorkspaceAssignPrompt
          attachmentProjectName={assignHint.folderName}
          currentProjectName={currentProjectName}
          onAssign={acceptAssignHint}
          onKeep={dismissAssignHint}
        />
      )}

      <AttachmentChips attachments={attachments} onRemove={removeAttachment} />

      {/* 断连提示：仅在心跳判定服务器不可达时出现，主动告知「发送前」状态。 */}
      <ComposerConnectionNotice />

      {/* 会话字段徽章：较早对话已压缩（旗标 only，无摘要正文）。 */}
      <ComposerContextCompactedHint show={contextCompacted} />

      {/* 挂起弱提示：有待确认/续跑卡时常驻；不强拦发送（发送前二次确认见 useComposerSend）。 */}
      <ComposerPendingHintNotice show={showPendingHint} />

      {/* 空中断层 1：无救火按钮；发送下一条=新回合重试。 */}
      {showEmptyInterruptedHint && (
        <div
          aria-live="polite"
          data-testid="composer-empty-interrupted-hint"
          className="flex items-center gap-1.5 px-4 pt-2 text-xs text-muted-foreground"
        >
          {COMPOSER_EMPTY_INTERRUPTED_HINT}
        </div>
      )}

      {/* 生成中再发提示：有草稿时出现；主按钮仍是停止；P1 默认插入。 */}
      {isGenerating && hasDraft && !showPendingHint && (
        <div
          aria-live="polite"
          data-testid="composer-midflight-hint"
          className="flex items-center gap-1.5 px-4 pt-2 text-xs text-muted-foreground"
        >
          <Loader2 size={12} className="shrink-0 animate-spin" />
          Enter 或点发送将插入当前回合；Ctrl/Cmd+Enter 强制排队
        </div>
      )}

      {voice.isRecording && (
        <RecordingBar duration={voice.duration} onCancel={voice.cancel} />
      )}

      {isBar ? (
        <div className="flex items-end gap-1 px-2 py-1">
          <div className="flex shrink-0 items-center gap-0.5 pb-0.5">
            <Popover open={moreOpen} onOpenChange={setMoreOpen}>
              <PopoverTrigger asChild>
                <IconButton
                  size="md"
                  aria-label="更多选项"
                  aria-expanded={moreOpen}
                  title="更多"
                  className="relative"
                >
                  <Plus size={16} />
                  {serverUnhealthy && (
                    <span
                      aria-hidden
                      className="absolute top-1 right-1 size-1.5 rounded-full bg-destructive"
                    />
                  )}
                </IconButton>
              </PopoverTrigger>
              <PopoverContent
                align="start"
                side="top"
                className="w-64 overflow-visible p-2"
                onInteractOutside={(e) => {
                  const el = e.target as HTMLElement | null;
                  // Nested workspace / other portaled popovers live outside this
                  // content node — keep the more menu open while they are used.
                  if (el?.closest?.("[data-radix-popper-content-wrapper]")) {
                    e.preventDefault();
                  }
                }}
              >
                <div className="flex flex-col gap-1">
                  <ModelPicker disabled={isGenerating} />
                  <PermissionAxesBadge disabled={isGenerating} />
                  <ComposerWorkspaceChip conversationId={conversationId} />
                  <ComposerNoLocalChip />
                  {backgroundToggle}
                  {serverUnhealthy && <ServerStatusIndicator />}
                </div>
              </PopoverContent>
            </Popover>
            <IconButton
              size="md"
              onClick={() => void mention.pickLocalFile()}
              disabled={isGenerating}
              aria-label="附加本机文件"
            >
              <Paperclip size={16} />
            </IconButton>
          </div>
          {textareaBlock}
          <div className="flex shrink-0 items-center gap-1 pb-0.5">
            {voice.isSupported && (
              <VoiceButton state={voice.state} onClick={voice.toggle} />
            )}
            {showCharCount && (
              <span className="text-xs text-muted-foreground">
                {charCount}/{MESSAGE_CHAR_LIMIT}
              </span>
            )}
            {sendControls}
          </div>
        </div>
      ) : (
        <>
          {textareaBlock}
          <div className="flex items-center justify-between px-4 pb-3">
            <div className="flex min-w-0 flex-1 items-center gap-1">
              <ModelPicker disabled={isGenerating} />
              <PermissionAxesBadge disabled={isGenerating} />
              <ComposerWorkspaceChip conversationId={conversationId} />
              <ComposerNoLocalChip />
              <IconButton
                size="md"
                onClick={() => void mention.pickLocalFile()}
                disabled={isGenerating}
                aria-label="附加本机文件"
              >
                <Paperclip size={16} />
              </IconButton>
              {backgroundToggle}
              <ServerStatusIndicator />
            </div>
            <div className="flex items-center gap-3">
              {voice.isSupported && (
                <VoiceButton state={voice.state} onClick={voice.toggle} />
              )}
              {showCharCount && (
                <span className="text-xs text-muted-foreground">
                  {charCount}字
                </span>
              )}
              {sendControls}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
