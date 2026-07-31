import type { FileArtifact, FileOp } from "@/lib/fileArtifacts";
import { stageFileLabel } from "@/lib/stageDirs";
// 「本回合产出文件」卡（前端UX设计.md §九「回合内文件呈现」，手机端全新实现，对标桌面
// components/chat/FileArtifactsCard.tsx 语义）。主清单只认路径验收态（delivery_status.artifacts）；
// 缺字段 → 空卡。挂在答复正文下方；点任一可预览行 → 跳到该对话的文件页并直接打开预览
// （FileBrowser 的 `openPath` 深链）。删除态无文件可看 → 该行仅留痕、不可点。
// 手机 parity=simplified：无「查看改动」完整面；清单 + 深链文件页即可。
import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  FilePlus,
  FolderOpen,
  type LucideIcon,
  Trash2,
  X,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

const OP_META: Record<
  FileOp,
  { label: string; Icon: LucideIcon; cls: string; preview: boolean }
> = {
  write: { label: "写入", Icon: FilePlus, cls: "art-write", preview: true },
  edit: { label: "编辑", Icon: FilePlus, cls: "art-edit", preview: true },
  delete: { label: "删除", Icon: Trash2, cls: "art-delete", preview: false },
  move: { label: "移动", Icon: ArrowRight, cls: "art-move", preview: true },
};

function rowVisual(artifact: FileArtifact): {
  Icon: LucideIcon;
  cls: string;
  badge: string | null;
  preview: boolean;
  badgeTitle?: string;
} {
  if (artifact.acceptance === "accepted") {
    return {
      Icon: Check,
      cls: "art-accepted",
      badge: "已验收",
      preview: true,
    };
  }
  if (artifact.acceptance === "rejected") {
    const detail =
      artifact.acceptanceDetail || artifact.acceptanceReason || undefined;
    return {
      Icon: X,
      cls: "art-rejected",
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
      cls: meta.cls,
      badge: meta.label,
      preview: meta.preview,
    };
  }
  return {
    Icon: FilePlus,
    cls: "art-neutral",
    badge: null,
    preview: true,
  };
}

function ArtifactBody({
  artifact,
  visual,
}: {
  artifact: FileArtifact;
  visual: ReturnType<typeof rowVisual>;
}) {
  const dir = artifact.path.slice(
    0,
    artifact.path.length - artifact.name.length,
  );
  const stageLabel = stageFileLabel(artifact.path);
  return (
    <>
      <visual.Icon size={14} className={`artifact-icon ${visual.cls}`} />
      <span className="artifact-path">
        {artifact.op === "move" && artifact.fromPath ? (
          <span className="artifact-dir">{artifact.fromPath} → </span>
        ) : dir ? (
          <span className="artifact-dir">{dir}</span>
        ) : null}
        <span className="artifact-name">{artifact.name}</span>
      </span>
      {stageLabel && <span className="artifact-stage">{stageLabel}</span>}
      {visual.badge && (
        <span title={visual.badgeTitle} className={`artifact-op ${visual.cls}`}>
          {visual.badge}
        </span>
      )}
    </>
  );
}

export function FileArtifactsCard({
  artifacts,
  conversationId,
}: {
  artifacts: FileArtifact[];
  conversationId: string | null;
}) {
  const navigate = useNavigate();
  // 文件不多（≤4）默认展开一目了然；多了先收起，避免长清单淹没答复。
  const [expanded, setExpanded] = useState(artifacts.length <= 4);

  if (artifacts.length === 0) return null;

  const open = (a: FileArtifact) => {
    if (!conversationId) return;
    navigate(`/c/${conversationId}/files`, { state: { openPath: a.path } });
  };

  return (
    <div className="artifacts">
      <button
        type="button"
        className="artifacts-head"
        onClick={() => setExpanded((v) => !v)}
      >
        <FolderOpen size={15} className="artifacts-folder" aria-hidden />
        <span className="artifacts-title">本回合产出文件</span>
        <span className="artifacts-count">{artifacts.length}</span>
        {expanded ? (
          <ChevronUp size={15} className="artifact-go" aria-hidden />
        ) : (
          <ChevronDown size={15} className="artifact-go" aria-hidden />
        )}
      </button>
      {expanded && (
        <ul className="artifacts-list">
          {artifacts.map((a) => {
            const visual = rowVisual(a);
            const isDelete = a.op === "delete";
            const canOpen = visual.preview && !isDelete && !!conversationId;
            if (!canOpen) {
              return (
                <li
                  key={`${a.acceptance ?? a.op ?? "file"}:${a.path}`}
                  className="artifact-row artifact-static"
                >
                  <ArtifactBody artifact={a} visual={visual} />
                </li>
              );
            }
            return (
              <li key={`${a.acceptance ?? a.op ?? "file"}:${a.path}`}>
                <button
                  type="button"
                  className="artifact-row"
                  onClick={() => open(a)}
                  title={
                    stageFileLabel(a.path)
                      ? `在文件页查看案卷 ${a.path}`
                      : `在工作区查看 ${a.path}`
                  }
                >
                  <ArtifactBody artifact={a} visual={visual} />
                  <ChevronRight size={14} className="artifact-go" aria-hidden />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
