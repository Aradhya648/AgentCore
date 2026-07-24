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
 * （两层是不同文件，各自独立基线）。本壳只提供单一返回键 + 组合标题 + 归属标注。
 */

import { MarkdownFileEditor } from "@/components/files/MarkdownFileEditor";
import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import type { FileSource } from "@/lib/fileSource";
import {
  GLOBAL_PROFILE_PATH,
  memoryProjectProfilePath,
} from "@/services/sources/memorySource";
import { ChevronLeft, Layers } from "lucide-react";

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
          <div className="min-h-0 flex-1">
            <MarkdownFileEditor
              embedded
              source={source}
              path={GLOBAL_PROFILE_PATH}
              name="全局画像 · 所有对话共享"
              onClose={onClose}
            />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <MarkdownFileEditor
              embedded
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
