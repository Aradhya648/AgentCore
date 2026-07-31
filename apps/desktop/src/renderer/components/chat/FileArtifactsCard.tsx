import { FileAuditTrail } from "@/components/audit/FileAuditTrail";
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
  Check,
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
  X,
} from "lucide-react";

/**
 * 「本回合产出文件」卡 —— 主清单只认路径验收态（delivery_status.artifacts），挂在
 * 答复正文下方（前端UX设计.md §九「回合内文件呈现」）。点任一可预览行 → 经 {@link useSidePanelStore}
 * 的 `showFile` 开右坞顶栏 File 内容 tab。例外：HTML 产物在会话具备应用内「完整预览」能力时
 * **直达**内置浏览器 tab（`preview://`）。「查看改动」聚焦右坞「改动」tab（无则先挂；与
 * {@link TurnFileChangesReview} 同源，前端UX设计.md §十）。
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

function rowVisual(artifact: FileArtifact): {
  Icon: LucideIcon;
  tone: StatusTone;
  badge: string | null;
  preview: boolean;
  badgeTitle?: string;
} {
  if (artifact.acceptance === "accepted") {
    return {
      Icon: Check,
      tone: "success",
      badge: "已验收",
      preview: true,
    };
  }
  if (artifact.acceptance === "rejected") {
    const detail =
      artifact.acceptanceDetail || artifact.acceptanceReason || undefined;
    return {
      Icon: X,
      tone: "destructive",
      badge: "未通过",
      preview: true,
      badgeTitle: detail,
    };
  }
  // 无验收态时：删除/移动仍标操作；写入/编辑不显示（勿用工具名冒充交付成功）。
  if (artifact.op === "delete" || artifact.op === "move") {
    const meta = OP_META[artifact.op];
    return {
      Icon: meta.Icon,
      tone: meta.tone,
      badge: meta.label,
      preview: meta.preview,
    };
  }
  return {
    Icon: FilePlus,
    tone: "muted",
    badge: null,
    preview: true,
  };
}

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
  const visual = rowVisual(artifact);
  const isDelete = artifact.op === "delete";
  const auditState = useFileAudit(
    conversationId,
    artifact.path,
    auditOpen && !isDelete,
  );
  const dir = artifact.path.slice(
    0,
    artifact.path.length - artifact.name.length,
  );
  const stageLabel = stageFileLabel(artifact.path);
  const body = (
    <>
      <visual.Icon
        size={14}
        className={`shrink-0 ${statusAccentText[visual.tone]}`}
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
      {visual.badge && (
        <span
          title={visual.badgeTitle}
          className={`shrink-0 rounded-full px-1.5 py-0.5 text-xs leading-none ${statusPillSoft[visual.tone]}`}
        >
          {visual.badge}
        </span>
      )}
    </>
  );

  // 删除态无可预览的文件 → 仅留痕、不可点。
  if (!visual.preview || isDelete) {
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
  const showFile = useSidePanelStore((s) => s.showFile);
  const showChanges = useSidePanelStore((s) => s.showChanges);
  // 与对话侧栏同一套能力判定：hook 只对云端会话源且 hasInAppPreview 时挂 openInAppPreview。
  const openInAppPreview =
    useConversationFileSource(conversationId)?.openInAppPreview;

  if (artifacts.length === 0) return null;

  const canReview =
    hasChangePreviews(artifacts) || (!!conversationId && !!turnKey);

  const openArtifact = (a: FileArtifact) => {
    // HTML 直达完整预览（内置浏览器 tab）；其余/无能力回落 File 内容 tab。
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
          <SimpleTooltip label="在右坞查看改动（只读）">
            <Button
              variant="ghost"
              onClick={() => showChanges(turnKey)}
              aria-label="查看改动"
              className="h-auto shrink-0 rounded-none px-3 py-2.5 text-xs text-muted-foreground hover:bg-accent/50 hover:text-foreground"
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
              key={`${a.acceptance ?? a.op ?? "file"}:${a.path}`}
              artifact={a}
              conversationId={conversationId}
              turnKey={turnKey}
              onOpen={() => openArtifact(a)}
              opensFullPreview={!!openInAppPreview && isHtmlPath(a.path)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
