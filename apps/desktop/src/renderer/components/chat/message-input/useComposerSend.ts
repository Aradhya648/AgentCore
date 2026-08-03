import {
  patchConversationCache,
  upsertConversationFront,
} from "@/hooks/useConversations";
import {
  type MessageDelivery,
  resolveDefaultDelivery,
} from "@/lib/composerDelivery";
import { confirmSendDespitePendingIfNeeded } from "@/lib/composerPendingHint";
import { isReadOnlyOffline } from "@/lib/offlineMode";
import { notifyError } from "@/lib/toast";
import { api } from "@/services/api";
import {
  provisionalConversationTitle,
  requestAutoTitle,
  setConversationModelProfile,
} from "@/services/conversations";
import { ensureDefaultContainerRoot } from "@/services/defaultWorkspace";
import { loadLatestWindow } from "@/services/messages";
import { getLastUsedProfileId } from "@/services/models";
import {
  type PermissionAxes,
  resolveDefaultPermissionAxes,
  setComposerDraftAxes,
} from "@/services/permissionAxes";
import type { OutgoingAttachment } from "@/services/streamConversation";
import { sendTurn } from "@/services/turns";
import { sendMidFlightMessage } from "@/services/turns/midFlight";
import { useComposerDraftStore } from "@/stores/composer";
import { getActiveRuntime, useConversationStore } from "@/stores/conversation";
import { useFoldersStore } from "@/stores/folders";
import { type Dispatch, type SetStateAction, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type { PendingAttachment } from "./composerAttachments";
import { dispatchBackgroundTask } from "./dispatchBackgroundTask";
import { ensureAttachmentResident } from "./resideAttachment";

export function useComposerSend({
  value,
  setValue,
  attachments,
  setAttachments,
  isGenerating,
  backgroundMode,
  isLocal,
  closeMenu,
  onDispatch,
}: {
  value: string;
  setValue: Dispatch<SetStateAction<string>>;
  attachments: PendingAttachment[];
  setAttachments: Dispatch<SetStateAction<PendingAttachment[]>>;
  isGenerating: boolean;
  backgroundMode: boolean;
  isLocal: boolean;
  closeMenu: () => void;
  /** Fires when a FOREGROUND turn is dispatched (not for 后台云端 handoffs) — the
   * canvas host uses it to start auto-following the new round. */
  onDispatch?: () => void;
}) {
  const addMessage = useConversationStore((s) => s.addMessage);
  const navigate = useNavigate();

  const handleSend = useCallback(
    async (opts?: { delivery?: MessageDelivery }) => {
      const trimmed = value.trim();
      if (!trimmed) return;

      // N4-A：只读离线硬禁用（按钮已 disabled；此处兜底防键盘/程序化触发）。
      if (isReadOnlyOffline()) {
        notifyError("离线时无法发送，请恢复连接后再试");
        return;
      }

      const activeConvId =
        useConversationStore.getState().currentConversationId;

      // 挂起弱提示：有待确认卡时先二次确认（同会话确认一次后不再弹）；正规续跑/
      // 提交卡不受影响。生成中再发走 mid-flight，不套本确认。
      if (!confirmSendDespitePendingIfNeeded(activeConvId, isGenerating)) {
        return;
      }

      const delivery: MessageDelivery =
        opts?.delivery ?? resolveDefaultDelivery(isGenerating, activeConvId);

      // Mid-flight：生成中发送走独立 POST SSE（steer 插话 / queue 排队）。
      // 排队立即插用户气泡；协调插话不经 addMessage——主时间线由 InterjectionTimeline
      // 投影 execution.userInterjections（user_interjection SSE）。
      if (isGenerating && activeConvId) {
        const pending = attachments;
        const outgoing: OutgoingAttachment[] = [];
        for (const a of pending) {
          if (
            a.kind === "file" &&
            (a.stagingId || a.workspacePath || a.binary || a.fileBlob)
          ) {
            const resided = await ensureAttachmentResident(activeConvId, a);
            if (!resided.ok) {
              notifyError(new Error(resided.reason), "附件驻留失败");
              if (resided.reason.includes("暂存已失效") && a.stagingId) {
                setAttachments((prev) => prev.filter((x) => x.id !== a.id));
              }
              return;
            }
            outgoing.push({
              name: resided.name,
              path: resided.workspacePath || a.path,
              text: resided.binary ? "" : resided.text,
              truncated: resided.truncated,
              kind: "file",
              binary: resided.binary,
              workspace_path: resided.workspacePath || undefined,
            });
          } else {
            outgoing.push({
              name: a.name,
              path: a.path,
              text: a.text,
              truncated: a.truncated,
              kind: a.kind,
              conversation_id: a.conversationId,
              binary: a.binary,
              workspace_path: a.workspacePath,
            });
          }
        }

        const result = await sendMidFlightMessage(
          activeConvId,
          trimmed,
          outgoing.length > 0 ? outgoing : undefined,
          delivery,
        );
        if (
          result.kind === "received" ||
          result.kind === "steered" ||
          result.kind === "queued"
        ) {
          setValue("");
          setAttachments([]);
          closeMenu();
          // queued toast / 气泡由 turn_queued → dispatch + midFlight；
          // steered toast 由 turn_steer_accepted → messageStream；
          // received 主时间线走 SSE 投影。
        }
        return;
      }

      if (isGenerating) return;

      if (backgroundMode && isLocal && activeConvId) {
        dispatchBackgroundTask(activeConvId, trimmed);
        setValue("");
        setAttachments([]);
        closeMenu();
        return;
      }

      const pending = attachments;
      const store = useConversationStore.getState();
      const isFirstMessage = getActiveRuntime().messages.length === 0;

      let conversationId = store.currentConversationId;
      let createdNew = false;
      if (!conversationId) {
        const intent = useFoldersStore.getState().draftWorkspaceIntent;
        const targetFolderId =
          intent.kind === "project" ? intent.folderId : null;
        // Project chats inherit workspace — never write session-level local_*.
        // Quick cloud (default) → null container. Quick local → default container root.
        let localContainerRootId: string | null = null;
        if (intent.kind === "quick_local") {
          localContainerRootId = await ensureDefaultContainerRoot();
        }
        // 新会话继承上次在聊天里选的组合 id（会话级组合引用）：last_profile_id 作默认建议。
        const inheritedProfileId = getLastUsedProfileId();
        try {
          const permissionAxes = await resolveDefaultPermissionAxes();
          const conv = await api.post<{
            id: string;
            permission_axes?: PermissionAxes;
          }>("/v1/conversations", {
            title: null,
            folder_id: targetFolderId,
            local_container_root_id: localContainerRootId,
            permission_axes: permissionAxes,
          });
          conversationId = conv.id;
          setComposerDraftAxes(null);
          upsertConversationFront({
            id: conv.id,
            title: provisionalConversationTitle(trimmed),
            updatedAt: new Date().toISOString(),
            messageCount: 0,
            lastMessagePreview: null,
            folderId: targetFolderId,
            localContainerRootId,
            permissionAxes: conv.permission_axes ?? permissionAxes,
            modelProfileId: inheritedProfileId,
          });
          // Persist the inherited profile onto the new conversation BEFORE the first
          // turn so it actually runs on it. Best-effort: stale id 422s → clear and
          // follow account default; never block the send.
          if (inheritedProfileId) {
            try {
              const updated = await setConversationModelProfile(
                conv.id,
                inheritedProfileId,
              );
              patchConversationCache(conv.id, {
                modelProfileId: updated.modelProfileId ?? null,
              });
            } catch {
              patchConversationCache(conv.id, { modelProfileId: null });
            }
          }
          // 首发落地动画：仅在草稿 promote 成新对话时武装 dock-flip（中间→底栏）。切换到
          // 已有对话不走这里，故不会误触发动画——这正是修掉「输入框跳动」的关键。必须在
          // switchConversation 前武装，让 conversationId 翻转的那一帧就带上信号。
          useComposerDraftStore.getState().armDockFlip();
          useConversationStore.getState().switchConversation(conv.id);
          createdNew = true;
          useFoldersStore.getState().resetDraftWorkspaceIntent();
        } catch (err) {
          notifyError(err, "新建对话失败");
          return;
        }
      }

      if (!isFirstMessage && getActiveRuntime().hasMoreAfter) {
        try {
          await loadLatestWindow(conversationId);
        } catch {
          /* best-effort */
        }
      }

      // 引用即驻留：在乐观气泡之前完成落盘/上传，失败则保留草稿附件。
      const outgoing: OutgoingAttachment[] = [];
      for (const a of pending) {
        if (
          a.kind === "file" &&
          (a.stagingId || a.workspacePath || a.binary || a.fileBlob)
        ) {
          const resided = await ensureAttachmentResident(conversationId, a);
          if (!resided.ok) {
            notifyError(new Error(resided.reason), "附件驻留失败");
            if (resided.reason.includes("暂存已失效") && a.stagingId) {
              setAttachments((prev) => prev.filter((x) => x.id !== a.id));
            }
            return;
          }
          outgoing.push({
            name: resided.name,
            path: resided.workspacePath || a.path,
            text: resided.binary ? "" : resided.text,
            truncated: resided.truncated,
            kind: "file",
            binary: resided.binary,
            workspace_path: resided.workspacePath || undefined,
          });
        } else {
          outgoing.push({
            name: a.name,
            path: a.path,
            text: a.text,
            truncated: a.truncated,
            kind: a.kind,
            conversation_id: a.conversationId,
            binary: a.binary,
            workspace_path: a.workspacePath,
          });
        }
      }

      const userMsgId = crypto.randomUUID();
      addMessage({
        id: userMsgId,
        role: "user",
        content: trimmed,
        createdAt: new Date().toISOString(),
        executionId: null,
        isStreaming: false,
        attachments: pending.length
          ? pending.map((a, i) => ({
              id: a.id,
              name: outgoing[i]?.name ?? a.name,
              path: outgoing[i]?.path ?? a.path,
              truncated: a.truncated,
              kind: a.kind,
              conversationId: a.conversationId,
              workspacePath: outgoing[i]?.workspace_path,
            }))
          : undefined,
      });
      setValue("");
      setAttachments([]);
      closeMenu();

      if (isFirstMessage) {
        patchConversationCache(conversationId, {
          title: provisionalConversationTitle(trimmed),
        });
      }

      // Local sidecar has no cloud SSE title_generated — mint in parallel with the
      // turn (same core as cloud schedule_title_generation). Failure keeps the
      // provisional truncation; local-turns write-back may still fall back.
      if (isLocal && isFirstMessage) {
        void requestAutoTitle(conversationId, trimmed).then((title) => {
          if (title) patchConversationCache(conversationId, { title });
        });
      }

      if (createdNew) {
        navigate(`/conversations/${conversationId}`);
      }

      // Same React batch as the optimistic bubble above, so a canvas follow effect
      // armed here sees the new turn land.
      onDispatch?.();

      await sendTurn({
        conversationId,
        content: trimmed,
        attachments: outgoing,
        optimisticUserId: userMsgId,
        delivery: "steer",
      });
    },
    [
      value,
      attachments,
      isGenerating,
      addMessage,
      navigate,
      closeMenu,
      backgroundMode,
      isLocal,
      setValue,
      setAttachments,
      onDispatch,
    ],
  );

  return { handleSend };
}
