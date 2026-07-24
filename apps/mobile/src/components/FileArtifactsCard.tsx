import type { FileArtifact, FileOp } from "@/lib/fileArtifacts";
import { stageFileLabel } from "@/lib/stageDirs";
// 「本回合产出文件」卡（前端UX设计.md §九「回合内文件呈现」，手机端全新实现，对标桌面
// components/chat/FileArtifactsCard.tsx）。把一回合内成功的 写/改/删/移 聚合成回合级清单，
// 挂在答复正文下方；点任一可预览行 → 跳到该对话的文件页并直接打开预览（FileBrowser 的
// `openPath` 深链）。删除态无文件可看 → 该行仅留痕、不可点。卡只读已折好的运行时态、不持久
// 化，真相仍以工作区文件树为准；重载后由各回合 journal 重建。
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  FilePlus,
  FolderOpen,
  type LucideIcon,
  Pencil,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

const OP_META: Record<
  FileOp,
  { label: string; Icon: LucideIcon; cls: string; preview: boolean }
> = {
  write: { label: "写入", Icon: FilePlus, cls: "art-write", preview: true },
  edit: { label: "编辑", Icon: Pencil, cls: "art-edit", preview: true },
  delete: { label: "删除", Icon: Trash2, cls: "art-delete", preview: false },
  move: { label: "移动", Icon: ArrowRight, cls: "art-move", preview: true },
};

function ArtifactBody({ artifact }: { artifact: FileArtifact }) {
  const meta = OP_META[artifact.op];
  const dir = artifact.path.slice(
    0,
    artifact.path.length - artifact.name.length,
  );
  const stageLabel = stageFileLabel(artifact.path);
  return (
    <>
      <meta.Icon size={14} className={`artifact-icon ${meta.cls}`} />
      <span className="artifact-path">
        {artifact.op === "move" && artifact.fromPath ? (
          <span className="artifact-dir">{artifact.fromPath} → </span>
        ) : dir ? (
          <span className="artifact-dir">{dir}</span>
        ) : null}
        <span className="artifact-name">{artifact.name}</span>
      </span>
      {stageLabel && <span className="artifact-stage">{stageLabel}</span>}
      <span className={`artifact-op ${meta.cls}`}>{meta.label}</span>
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
            const canOpen = OP_META[a.op].preview && !!conversationId;
            if (!canOpen) {
              return (
                <li
                  key={`${a.op}:${a.path}`}
                  className="artifact-row artifact-static"
                >
                  <ArtifactBody artifact={a} />
                </li>
              );
            }
            return (
              <li key={`${a.op}:${a.path}`}>
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
                  <ArtifactBody artifact={a} />
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
