import { FileAuditTrail } from "@/components/audit/FileAuditTrail";
import { TurnFileChangesReview } from "@/components/chat/TurnFileChangesReview";
import { Button, IconButton } from "@/components/ui";
import {
  type StatusTone,
  statusAccentText,
  statusPillSoft,
} from "@/components/ui/tone-presets";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useConversationFileSource } from "@/hooks/useConversationFileSource";
import { useFileAudit } from "@/hooks/useFileAudit";
import {
  type FileArtifact,
  type FileOp,
  hasChangePreviews,
} from "@/lib/fileArtifacts";
import { isHtmlPath } from "@/lib/fileSource";
import { stageFileLabel } from "@/lib/stageDirs";
import { usePersistentDisclosure } from "@/stores/disclosure";
import { useSidePanelStore } from "@/stores/sidePanel";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Diff,
  FilePlus,
  FolderOpen,
  History,
  type LucideIcon,
  Pencil,
  Trash2,
} from "lucide-react";

/**
 * 「本回合产出文件」卡 —— 把一回合内成功的文件写/改/删/移聚合成一张回合级清单，挂在
 * 答复正文下方（前端UX设计.md §九「回合内文件呈现」）。点任一可预览行 → 经 {@link useSidePanelStore}
 * 的 `showFile` 把右侧工作区面板切到该文件预览，与文件树/详情共用同一套预览（不另起编辑器）。
 * 例外：HTML 产物在会话具备应用内「完整预览」能力时**直达**内置浏览器 tab（网页产物的
 * 首要出口就是看效果；能力判定与对话侧栏同一套 = {@link useConversationFileSource} 挂没挂
 * `openInAppPreview`，不另起判定），无能力则回落文件源码视图。
 *
 * 删除态无文件可看 → 该行不可点（仅留痕）。卡只读已折好的运行时状态；折叠偏好按对话持久化。
 * 工作区文件树仍是真相源；重载后由各回合 journal 重建 process/execution 时清单自然复现。
 */

const OP_META: Record<
  FileOp,
  {
    label: string;
    Icon: LucideIcon;
    tone: StatusTone;
    preview: boolean;
  }
> = {
  write: {
    label: "写入",
    Icon: FilePlus,
    tone: "success",
    preview: true,
  },
  edit: {
    label: "编辑",
    Icon: Pencil,
    tone: "primary",
    preview: true,
  },
  delete: {
    label: "删除",
    Icon: Trash2,
    tone: "destructive",
    preview: false,
  },
  move: {
    label: "移动",
    Icon: ArrowRight,
    tone: "muted",
    preview: true,
  },
};

function FileRow({
  artifact,
  conversationId,
  turnKey,
  onOpen,
  opensFullPreview = false,
}: {
  artifact: FileArtifact;
  conversationId: string | null;
  turnKey?: string;
  onOpen: () => void;
  /** 该行点击直达应用内「完整预览」（HTML + 会话具备能力）——仅影响提示文案。 */
  opensFullPreview?: boolean;
}) {
  const [auditOpen, setAuditOpen] = usePersistentDisclosure(
    turnKey ? `${turnKey}:file-audit:${artifact.path}` : null,
    false,
  );
  const auditState = useFileAudit(
    conversationId,
    artifact.path,
    auditOpen && artifact.op !== "delete",
  );
  const meta = OP_META[artifact.op];
  const dir = artifact.path.slice(
    0,
    artifact.path.length - artifact.name.length,
  );
  const stageLabel = stageFileLabel(artifact.path);
  const body = (
    <>
      <meta.Icon
        size={14}
        className={`shrink-0 ${statusAccentText[meta.tone]}`}
      />
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">
        {artifact.op === "move" && artifact.fromPath ? (
          <span className="text-muted-foreground/70">
            {artifact.fromPath} →{" "}
          </span>
        ) : dir ? (
          <span className="text-muted-foreground/60">{dir}</span>
        ) : null}
        <span className="font-medium">{artifact.name}</span>
      </span>
      {stageLabel && (
        <span
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-xs leading-none ${statusPillSoft.muted}`}
        >
          {stageLabel}
        </span>
      )}
      <span
        className={`shrink-0 rounded-full px-1.5 py-0.5 text-xs leading-none ${statusPillSoft[meta.tone]}`}
      >
        {meta.label}
      </span>
    </>
  );

  // 删除态无可预览的文件 → 仅留痕、不可点。
  if (!meta.preview) {
    return (
      <li className="flex items-center gap-2 px-3 py-2 opacity-70">{body}</li>
    );
  }
  return (
    <li>
      <div className="flex items-center">
        <Button
          variant="ghost"
          onClick={onOpen}
          title={
            opensFullPreview
              ? `打开完整预览 ${artifact.path}`
              : stageLabel
                ? `在文件页查看案卷 ${artifact.path}`
                : `在工作区预览 ${artifact.path}`
          }
          className="h-auto min-w-0 flex-1 justify-start gap-2 rounded-none px-3 py-2 hover:bg-accent"
        >
          <span className="flex w-full items-center gap-2 text-left">
            {body}
            <ChevronRight
              size={14}
              className="shrink-0 text-muted-foreground/50"
            />
          </span>
        </Button>
        {conversationId && (
          <SimpleTooltip label="查看写入归因">
            <IconButton
              className="mr-2 shrink-0"
              aria-label="查看写入归因"
              aria-expanded={auditOpen}
              onClick={() => setAuditOpen((v) => !v)}
            >
              <History size={14} />
            </IconButton>
          </SimpleTooltip>
        )}
      </div>
      {auditOpen && conversationId && (
        <div className="border-t border-border bg-muted/30 px-3 py-2">
          <FileAuditTrail state={auditState} compact />
        </div>
      )}
    </li>
  );
}

export function FileArtifactsCard({
  artifacts,
  conversationId = null,
  turnKey,
}: {
  artifacts: FileArtifact[];
  conversationId?: string | null;
  /** 回合作用域（= messageId）：给了才把整卡/审计行开合持久化。 */
  turnKey?: string;
}) {
  // 文件不多（≤4）默认展开一目了然；多了先收起，避免长清单淹没答复。
  const [expanded, setExpanded] = usePersistentDisclosure(
    turnKey ? `${turnKey}:files` : null,
    artifacts.length <= 4,
  );
  // A1 只读「查看改动」：默认收起，避免与清单抢视觉。
  const [reviewOpen, setReviewOpen] = usePersistentDisclosure(
    turnKey ? `${turnKey}:file-changes` : null,
    false,
  );
  const showFile = useSidePanelStore((s) => s.showFile);
  // 与对话侧栏同一套能力判定：hook 只对云端会话源且 hasInAppPreview 时挂 openInAppPreview。
  const openInAppPreview =
    useConversationFileSource(conversationId)?.openInAppPreview;

  if (artifacts.length === 0) return null;

  const canReview =
    hasChangePreviews(artifacts) || (!!conversationId && !!turnKey);

  const openArtifact = (a: FileArtifact) => {
    // HTML 直达完整预览（内置浏览器 tab）；其余/无能力回落工作区文件视图。
    if (openInAppPreview && isHtmlPath(a.path)) {
      void openInAppPreview(a.path);
      return;
    }
    showFile(a.path, a.name);
  };

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-stretch border-border">
        <Button
          variant="ghost"
          onClick={() => setExpanded((v) => !v)}
          className="h-auto min-w-0 flex-1 justify-start gap-2 rounded-none px-3 py-2.5 hover:bg-accent/50"
        >
          <span className="flex w-full items-center gap-2 text-left">
            <FolderOpen
              size={15}
              className={`shrink-0 ${statusAccentText.primary}`}
            />
            <span className="flex-1 text-sm font-medium text-foreground">
              本回合产出文件
            </span>
            <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs leading-none text-muted-foreground">
              {artifacts.length}
            </span>
            {expanded ? (
              <ChevronUp size={15} className="shrink-0 text-muted-foreground" />
            ) : (
              <ChevronDown
                size={15}
                className="shrink-0 text-muted-foreground"
              />
            )}
          </span>
        </Button>
        {canReview && (
          <SimpleTooltip label="查看改动（只读预览）">
            <Button
              variant="ghost"
              onClick={() => setReviewOpen((v) => !v)}
              aria-expanded={reviewOpen}
              aria-label="查看改动"
              className={`h-auto shrink-0 rounded-none px-3 py-2.5 text-xs hover:bg-accent/50 ${
                reviewOpen
                  ? "bg-accent/40 text-foreground"
                  : "text-muted-foreground"
              }`}
            >
              <Diff size={14} className="mr-1.5 shrink-0" />
              查看改动
            </Button>
          </SimpleTooltip>
        )}
      </div>
      {expanded && (
        // 无行间横线（统一两卡列表语言）：单行可点行有 hover 底色 + 图标锚点，保持现有密度。
        <ul className="border-t border-border">
          {artifacts.map((a) => (
            <FileRow
              key={`${a.op}:${a.path}`}
              artifact={a}
              conversationId={conversationId}
              turnKey={turnKey}
              onOpen={() => openArtifact(a)}
              opensFullPreview={!!openInAppPreview && isHtmlPath(a.path)}
            />
          ))}
        </ul>
      )}
      {reviewOpen && canReview && (
        <TurnFileChangesReview
          artifacts={artifacts}
          conversationId={conversationId}
          messageId={turnKey ?? null}
        />
      )}
    </div>
  );
}
