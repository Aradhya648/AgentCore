import { Button } from "@/components/ui";
import { useConversations } from "@/hooks/useConversations";
import { STARTER_TASK_CHIPS, resolveDraftEmptyKind } from "@/lib/onboarding";
import { useComposerDraftStore } from "@/stores/composer";
import { BookOpen } from "lucide-react";
import { Link } from "react-router-dom";

/**
 * 草稿页空态两态：首启任务 chips / 老用户单句。平台代付、开箱即用——无「先接入模型」门。
 * 仅在 ChatView 无消息时渲染。
 */
export function DraftEmptyState({
  previewKind,
}: {
  /** Offline preview override. */
  previewKind?: ReturnType<typeof resolveDraftEmptyKind>;
}) {
  const conversations = useConversations();
  const kind =
    previewKind ??
    resolveDraftEmptyKind({
      conversationCount: conversations.length,
    });
  const fill = useComposerDraftStore((s) => s.fill);

  if (kind === "starter_chips") {
    return (
      <div
        className="mx-auto max-w-lg px-6 text-center"
        data-empty-kind="starter_chips"
      >
        <p className="text-2xl font-medium text-foreground">
          今天想解决什么问题？
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          试试这些会拉起多 Agent 协作的任务——点一下填入输入框，再按发送。
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {STARTER_TASK_CHIPS.map((text) => (
            <Button
              key={text}
              variant="neutral"
              className="h-auto max-w-full whitespace-normal border border-border bg-card px-3 py-2 text-left text-muted-foreground hover:border-primary/40 hover:text-foreground"
              onClick={() => fill(text)}
            >
              {text}
            </Button>
          ))}
        </div>
        <Link
          to="/toolbox/manual"
          className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <BookOpen size={12} />
          产品手册
        </Link>
      </div>
    );
  }

  return (
    <div className="text-center" data-empty-kind="returning">
      <p className="text-2xl font-medium text-foreground">
        今天想解决什么问题？
      </p>
    </div>
  );
}
