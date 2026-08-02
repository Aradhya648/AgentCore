import { SurfaceRowButton } from "@/components/ui";
import { useConversations } from "@/hooks/useConversations";
import { useWorkspaceGroups } from "@/hooks/useWorkspaceGroups";
import { type Conversation, useConversationStore } from "@/stores/conversation";
import { ChevronRight, MessageSquare } from "lucide-react";
import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { ConversationItem } from "./ConversationItem";

/** How many 裸聊 the「快速对话」zone shows before deferring to /conversations.
 * Adaptive: with no「项目」groups the zone owns more of the rail ({@link BARE_LIMIT_SOLO});
 * once groups sit above it the cap relaxes to {@link BARE_LIMIT_WITH_GROUPS}.
 * Overflow exits via「查看全部对话」. Pinned chats live in {@link PinnedConversations}. */
const BARE_LIMIT_SOLO = 15;
const BARE_LIMIT_WITH_GROUPS = 10;

function byRecency(a: Conversation, b: Conversation): number {
  return (Date.parse(b.updatedAt) || 0) - (Date.parse(a.updatedAt) || 0);
}

/**
 * The rail's bare-chat zone (前端UX §一 方案C): **unpinned 裸聊** below the
 * workspace groups. Foldered chats live in their {@link useWorkspaceGroups} group
 * (or the pin zone if pinned). The currently-open bare chat is always kept even
 * when older than the cut-off.
 *
 * No section title. A hairline separates this zone from whatever sits above
 * (置顶 and/or 项目). When every chat is foldered or pinned this zone renders nothing.
 */
export function RecentConversations() {
  const conversations = useConversations();
  const hasGroups = useWorkspaceGroups().length > 0;
  const hasPinned = conversations.some((c) => c.pinned);
  const currentId = useConversationStore((s) => s.currentConversationId);

  const recent = useMemo(() => {
    const limit = hasGroups ? BARE_LIMIT_WITH_GROUPS : BARE_LIMIT_SOLO;
    const bare = conversations
      .filter((c) => !c.folderId && !c.pinned)
      .sort(byRecency);
    const top = bare.slice(0, limit);
    if (currentId && !top.some((c) => c.id === currentId)) {
      const active = bare.find((c) => c.id === currentId);
      if (active) top.push(active); // keep an out-of-window active bare chat visible
    }
    return top;
  }, [conversations, currentId, hasGroups]);

  if (conversations.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
        <MessageSquare size={24} className="text-sidebar-foreground/30" />
        <p className="text-sm text-sidebar-foreground/50">暂无对话</p>
        <p className="text-xs text-sidebar-foreground/40">开始第一次对话 →</p>
      </div>
    );
  }

  // Every chat is foldered / pinned → no unpinned 裸聊; upper zones carry the rail.
  if (recent.length === 0) return null;

  return (
    <>
      {/* Hairline above 裸聊 when 置顶 and/or 项目 sit above (Sidebar nav divider
          uses the same mx-3 sibling pattern). */}
      {(hasGroups || hasPinned) && (
        <div className="mx-3 border-t border-sidebar-border" />
      )}
      <div className={`space-y-0.5 px-2 py-1 ${hasGroups || hasPinned ? "pt-2" : ""}`}>
        {recent.map((conv) => (
          <ConversationItem key={conv.id} conversation={conv} />
        ))}
      </div>
    </>
  );
}

/**
 * The「查看全部对话」entry into the full management page (/conversations). Lives at the
 * very bottom of the rail's conversation area — after「置顶」+「项目」+「快速对话」— so it's
 * the single overflow exit for everything (older 裸聊, extra workspaces, per-group
 * overflow). Hidden when there are no conversations at all.
 */
export function ViewAllConversations() {
  const count = useConversations().length;
  const navigate = useNavigate();
  if (count === 0) return null;
  return (
    <div className="px-2 pb-2">
      <SurfaceRowButton
        onClick={() => navigate("/conversations")}
        className="h-8 justify-between text-sidebar-foreground/55 hover:text-sidebar-foreground"
      >
        <span>查看全部对话</span>
        <ChevronRight size={14} className="shrink-0" />
      </SurfaceRowButton>
    </div>
  );
}
