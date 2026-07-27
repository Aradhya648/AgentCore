/**
 * 「本项目记忆」的两栏编辑器：**同屏**编辑 *全局画像* 与 *当前项目画像*，并标注各自归属
 * （Agent记忆与知识系统 §1.6）。
 *
 * 为什么两栏而非单文件：注入时这两层是**叠加**的——全局画像对所有对话生效，本项目画像只在
 * 这个项目内**附加**在全局之后（Agent记忆与知识系统 §二）。把两层并排摆出来，用户一眼看清
 * 「哪条是所有对话都记得的、哪条只此项目记得」，并能就地把放错层的事实搬到另一层。
 *
 * 实现上不另造编辑器：左右各是一例 {@link MarkdownFileEditor}（`embedded` 隐去各自的返回键），
 * 分别指向全局 / 本项目的画像合成路径——读写 / CAS / 自动保存 / AI 改写全部照旧、互不串扰
 * （两层是不同文件，各自独立基线）。本壳只提供单一返回键 + 组合标题 + 归属标注 + 搬层纠错。
 */

import {
  MarkdownFileEditor,
  type MarkdownFileEditorApi,
} from "@/components/files/MarkdownFileEditor";
import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { FileSource } from "@/lib/fileSource";
import { notifyActionError, notifyInfo } from "@/lib/toast";
import { ApiError } from "@/services/api";
import {
  type MemoryMoveDirection,
  moveMemoryBullet,
} from "@/services/memory";
import {
  GLOBAL_PROFILE_PATH,
  memoryProjectProfilePath,
} from "@/services/sources/memorySource";
import { ArrowLeftRight, ChevronLeft, Layers, Loader2 } from "lucide-react";
import { useCallback, useRef, useState } from "react";

/** Nearest `## section` above `from` in markdown; null when none. */
function sectionAtOffset(md: string, from: number): string | null {
  const before = md.slice(0, from);
  const matches = [...before.matchAll(/^##\s+(.+)$/gm)];
  if (matches.length === 0) return null;
  return (matches[matches.length - 1]?.[1] ?? "").trim() || null;
}

/** Strip a leading list marker from a selected bullet line. */
function bulletText(selection: string): string {
  return selection
    .replace(/^\s*[-*+]\s+/, "")
    .replace(/^<!--\s*ts:[^>]+-->\s*/i, "")
    .replace(/\s*<!--\s*ts:[^>]+-->\s*$/i, "")
    .trim();
}

export function MemoryProfileSplitEditor({
  source,
  folderId,
  projectName,
  onClose,
}: {
  /** The path-aware memory {@link FileSource}; each pane addresses a different leaf path. */
  source: FileSource;
  /** The project (= cloud workspace folderId) whose 画像 layer the right pane edits. */
  folderId: string;
  /** Display name of that project, for the 归属 label (falls back handled by caller). */
  projectName: string;
  onClose: () => void;
}) {
  const projectPath = memoryProjectProfilePath(folderId);
  const globalApi = useRef<MarkdownFileEditorApi | null>(null);
  const projectApi = useRef<MarkdownFileEditorApi | null>(null);
  const [busy, setBusy] = useState<"to_project" | "to_global" | null>(null);

  const runMove = useCallback(
    async (direction: MemoryMoveDirection) => {
      if (busy) return;
      const sourceApi =
        direction === "to_project" ? globalApi.current : projectApi.current;
      const targetApi =
        direction === "to_project" ? projectApi.current : globalApi.current;
      if (!sourceApi) return;

      await sourceApi.saveIfDirty();
      const md = sourceApi.getValue();
      const ctx = sourceApi.getSelectionContext();
      if (!md || !ctx?.selection.trim()) {
        notifyInfo("请先切换到编辑，选中要搬的那一条 bullet");
        return;
      }
      const section = sectionAtOffset(md, ctx.from);
      if (!section) {
        notifyInfo("选区需要落在某个 ## 小节内");
        return;
      }
      if (section === "纠正记录" && direction === "to_project") {
        notifyInfo("「纠正记录」只属于全局，不能移到本项目");
        return;
      }
      if (section === "项目约束" && direction === "to_global") {
        notifyInfo("「项目约束」只属于本项目，不能移到全局");
        return;
      }
      const content = bulletText(ctx.selection);
      if (!content) {
        notifyInfo("请选中一条有内容的 bullet");
        return;
      }

      setBusy(direction);
      try {
        const result = await moveMemoryBullet({
          content,
          section,
          folderId,
          direction,
          kind: "profile",
          sourceBaseline: sourceApi.getBaselineEtag(),
          targetBaseline: targetApi?.getBaselineEtag() ?? null,
        });
        if (result.conflict) {
          notifyInfo("记忆刚被更新，请稍后再试搬层");
          sourceApi.reload();
          targetApi?.reload();
          return;
        }
        notifyInfo(
          direction === "to_project" ? "已移到本项目" : "已移到全局",
        );
        sourceApi.reload();
        targetApi?.reload();
      } catch (e) {
        notifyActionError(
          "搬层失败",
          e instanceof ApiError ? (e.serverMessage ?? e.message) : e,
        );
      } finally {
        setBusy(null);
      }
    },
    [busy, folderId],
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border pl-1 pr-2.5">
        <SimpleTooltip label="返回文件列表">
          <IconButton onClick={onClose} aria-label="返回文件列表">
            <ChevronLeft size={16} />
          </IconButton>
        </SimpleTooltip>
        <Layers size={13} className="shrink-0 text-primary" />
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-foreground">
          画像 · 全局 + 本项目
        </span>
        <span className="hidden shrink-0 text-xs text-muted-foreground xl:inline">
          注入时叠加：全局对所有对话生效，本项目仅在「{projectName}」内附加
        </span>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col border-r border-border">
          <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border px-2.5">
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              全局
            </span>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void runMove("to_project")}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
              title="将选中的 bullet 移到本项目画像"
            >
              {busy === "to_project" ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <ArrowLeftRight size={12} />
              )}
              移到本项目
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <MarkdownFileEditor
              embedded
              apiRef={globalApi}
              source={source}
              path={GLOBAL_PROFILE_PATH}
              name="全局画像 · 所有对话共享"
              onClose={onClose}
            />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-8 shrink-0 items-center gap-2 border-b border-border px-2.5">
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              本项目 · {projectName}
            </span>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void runMove("to_global")}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:opacity-50"
              title="将选中的 bullet 移到全局画像"
            >
              {busy === "to_global" ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <ArrowLeftRight size={12} />
              )}
              移到全局
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <MarkdownFileEditor
              embedded
              apiRef={projectApi}
              source={source}
              path={projectPath}
              name={`本项目画像 · 仅「${projectName}」`}
              onClose={onClose}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
