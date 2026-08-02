import { SurfaceRowButton } from "@/components/ui";
import { useConversations } from "@/hooks/useConversations";
import { useWorkspaceGroups } from "@/hooks/useWorkspaceGroups";
import { deriveGroupWorkspaceIsLocal } from "@/lib/conversationWorkspaceMode";
import { useConversationStore } from "@/stores/conversation";
import { useSidebarStore } from "@/stores/sidebar";
import { MoreHorizontal } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { ConversationItem } from "./ConversationItem";
import { WorkspaceGroupHeader } from "./WorkspaceGroupHeader";

/** Conversations shown inside an expanded group before its「更多」overflow row. */
const MAX_PER_GROUP = 5;

/**
 * The sidebar's「项目」zone (前端UX §一 方案C): collapsible per-folder groups
 * between「置顶」and「快速对话」, fed by {@link useWorkspaceGroups}. Foldered
 * chats live ONLY here when unpinned (pinned lift to the rail 置顶区; 裸聊 stay
 * in「快速对话」). Empty folders are hidden; a folder whose every chat is pinned
 * still renders its header so「+」/ 归档全部 remain reachable. The zone renders
 * nothing when no group exists.
 *
 * Expand state persists per folder (`useSidebarStore.expandedSections`, keyed by
 * folderId): an explicit user toggle always wins; with no stored choice a group
 * defaults collapsed, except the one holding the **unpinned** active conversation
 * (pinned actives already sit in the 置顶区). Each group reuses
 * {@link ConversationItem} so rows keep the same status dot / rename / move /
 * archive behavior. Group headers expose project actions via
 * {@link WorkspaceGroupHeader} (header receives full folder members incl. pinned).
 */
export function WorkspaceGroups() {
  const groups = useWorkspaceGroups();
  const conversations = useConversations();
  const hasPinned = conversations.some((c) => c.pinned);
  const currentId = useConversationStore((s) => s.currentConversationId);
  const expandedSections = useSidebarStore((s) => s.expandedSections);
  const setSection = useSidebarStore((s) => s.setSection);
  const navigate = useNavigate();

  const activeFolderId = useMemo(() => {
    const active = conversations.find((c) => c.id === currentId);
    if (!active || active.pinned) return null;
    return active.folderId ?? null;
  }, [conversations, currentId]);

  if (groups.length === 0) return null;

  return (
    <>
      {hasPinned && <div className="mx-3 border-t border-sidebar-border" />}
      <div className="space-y-0.5 px-2 pb-1 pt-2">
        {groups.map(({ folder, convs }) => {
          const stored = expandedSections[folder.id];
          const expanded =
            stored !== undefined ? stored : folder.id === activeFolderId;
          const visible = convs.filter((c) => !c.pinned);
          const overflow = visible.length - MAX_PER_GROUP;
          const groupIsLocal = deriveGroupWorkspaceIsLocal(folder);
          return (
            <div key={folder.id}>
              <WorkspaceGroupHeader
                folder={folder}
                convs={convs}
                expanded={expanded}
                onToggleExpanded={() => setSection(folder.id, !expanded)}
              />
              {expanded && (
                // Same icon column as group header / 裸聊 / top nav — no nested
                // indent (status dots & cloud icons must share that axis).
                <div className="space-y-0.5">
                  {visible.slice(0, MAX_PER_GROUP).map((c) => (
                    <ConversationItem
                      key={c.id}
                      conversation={c}
                      groupIsLocal={groupIsLocal}
                      className="px-2"
                    />
                  ))}
                  {overflow > 0 && (
                    <SurfaceRowButton
                      onClick={() =>
                        navigate("/conversations", {
                          state: { focusFolderId: folder.id },
                        })
                      }
                      className="h-8 px-2 text-xs text-sidebar-foreground/50 hover:text-sidebar-foreground"
                    >
                      <MoreHorizontal size={13} className="shrink-0" />
                      更多（{overflow}）
                    </SurfaceRowButton>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
