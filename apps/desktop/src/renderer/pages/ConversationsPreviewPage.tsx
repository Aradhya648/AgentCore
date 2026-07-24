import { queryClient } from "@/lib/queryClient";
import { conversationKeys } from "@/lib/queryKeys";
import { ConversationsPage } from "@/pages/conversations/ConversationsPage";
import {
  CONVERSATIONS_PREVIEW_SCENES,
  buildCollaborationTimelineMock,
  buildConversationsPreviewArchived,
  buildConversationsPreviewGrouped,
} from "@/preview/conversationsScenes";
import { FlaskConical } from "lucide-react";
import { useLayoutEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

const PREVIEW_FOLDER_ID = "folder-product";

function seedPreviewCaches() {
  queryClient.setQueryData(
    conversationKeys.grouped,
    buildConversationsPreviewGrouped(),
  );
  queryClient.setQueryData(
    conversationKeys.archived,
    buildConversationsPreviewArchived(),
  );
  queryClient.setQueryData(
    conversationKeys.collaborationTimeline(PREVIEW_FOLDER_ID),
    buildCollaborationTimelineMock(PREVIEW_FOLDER_ID),
  );
  queryClient.setQueryData(["folder-dossier-snapshot", PREVIEW_FOLDER_ID], {
    research: ["research/法律透镜报告.md", "research/汇总与命题卡.md"],
    debate: ["debate/brief.md"],
  });
}

/**
 * Offline UI preview for the conversations management page (`#/preview/conversations`).
 * Seeds React Query caches with mock folders/conversations — no backend.
 */
export function ConversationsPreviewPage() {
  // Warm cache during render so ConversationsPage's useQuery never hits the network.
  seedPreviewCaches();

  const [searchParams, setSearchParams] = useSearchParams();
  const scenes = CONVERSATIONS_PREVIEW_SCENES;
  const requested = searchParams.get("s");
  const current = scenes.find((s) => s.id === requested) ?? scenes[0] ?? null;
  const selected = current?.id ?? null;

  const select = (id: string) => setSearchParams({ s: id }, { replace: true });

  return (
    <div
      className="flex h-full min-h-0 w-full"
      data-preview-conversations={selected ?? ""}
    >
      <aside className="flex w-64 shrink-0 flex-col border-r border-border">
        <div className="flex items-center gap-2 border-b border-border px-4 py-3">
          <FlaskConical size={18} className="shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-base font-semibold text-foreground">
              全部对话 · 预览
            </h1>
            <p className="text-xs text-muted-foreground">
              {scenes.length} 个场景 · 离线自检
            </p>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <ul className="space-y-0.5">
            {scenes.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => select(s.id)}
                  className={`w-full rounded-lg px-3 py-2.5 text-left ${
                    selected === s.id
                      ? "bg-accent text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                  }`}
                >
                  <span className="block truncate text-sm font-medium">
                    {s.title}
                  </span>
                  <span className="mt-0.5 block truncate text-xs opacity-70">
                    {s.description}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <div className="min-h-0 min-w-0 flex-1 bg-background">
        {selected && (
          <ConversationsPreviewBody
            key={selected}
            focusArchived={selected === "conversations-archived"}
            focusFolderId={
              selected === "conversations-collaboration"
                ? PREVIEW_FOLDER_ID
                : null
            }
          />
        )}
      </div>
    </div>
  );
}

function ConversationsPreviewBody({
  focusArchived,
  focusFolderId,
}: {
  focusArchived: boolean;
  focusFolderId?: string | null;
}) {
  const navigate = useNavigate();

  useLayoutEffect(() => {
    seedPreviewCaches();
    navigate(".", {
      replace: true,
      state: focusArchived
        ? { focusArchived: true }
        : focusFolderId
          ? { focusFolderId }
          : {},
    });
  }, [focusArchived, focusFolderId, navigate]);

  return <ConversationsPage />;
}
