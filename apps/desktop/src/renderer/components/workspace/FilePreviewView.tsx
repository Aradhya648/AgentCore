import { FileAuditSection } from "@/components/audit/FileAuditTrail";
import { Markdown } from "@/components/chat/Markdown";
import { FilePreviewBody } from "@/components/files/FilePreviewBody";
import { Centered, InlineError } from "@/components/files/parts";
import { Button, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useFileAudit } from "@/hooks/useFileAudit";
import {
  type FilePreviewResult,
  type FileSource,
  isHtmlPath,
  isMarkdownPath,
} from "@/lib/fileSource";
import { notifyActionError, notifyError } from "@/lib/toast";
import { LocalFsError } from "@/services/sources/localRootSource";
import { useConversationStore } from "@/stores/conversation";
import {
  AppWindow,
  ChevronLeft,
  Download,
  ExternalLink,
  FileText,
  FolderSearch,
  Globe,
  Loader2,
  Pencil,
  Save,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

/**
 * In-panel preview of one file from a {@link FileSource}, with opt-in editing for
 * whole text files. Takes over the files section (with a back arrow); a header
 * download button (when the source can transfer) pulls the raw file. Binary /
 * oversized files fall back to a download-only notice. Saving writes the buffer
 * back through the source's `writeBytes` (gated by `caps.edit`).
 *
 * HTML 与其他文本文件一致显示源码（C+ 决策：面板内静态快照已取消，页面效果只在真浏览器
 * 环境呈现）——顶部横幅指路完整效果出口，CTA 按能力递进：「打开完整预览」（内置浏览器
 * tab）→「在浏览器打开」（系统浏览器）→「下载」（web 兜底），与标题栏图标同一套门控。
 */
export function FilePreviewView({
  source,
  path,
  name,
  onClose,
}: {
  source: FileSource;
  path: string;
  name: string;
  onClose: () => void;
}) {
  const [result, setResult] = useState<FilePreviewResult | null>(null);
  const [error, setError] = useState(false);
  const [missing, setMissing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [openingInBrowser, setOpeningInBrowser] = useState(false);
  const [openingPreview, setOpeningPreview] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const isHtml = isHtmlPath(name);
  const isMarkdown = isMarkdownPath(name);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const fileAuditState = useFileAudit(conversationId, path, !editing);

  const load = useCallback(async () => {
    setResult(null);
    setError(false);
    setMissing(false);
    setEditing(false);
    try {
      setResult(await source.read(path));
    } catch (err) {
      const notFound =
        (err instanceof LocalFsError && err.code === "not_found") ||
        (typeof err === "object" &&
          err !== null &&
          "code" in err &&
          (err as { code: unknown }).code === "not_found");
      if (notFound) {
        setMissing(true);
      } else {
        console.error(
          `[FilePreview] source.read failed ${JSON.stringify({
            path,
            sourceId: source.id,
            error: err instanceof Error ? err.message : String(err),
          })}`,
        );
        setError(true);
      }
    }
  }, [source, path]);

  useEffect(() => {
    void load();
  }, [load]);

  const onDownload = async () => {
    if (downloading || !source.download) return;
    setDownloading(true);
    try {
      await source.download(path, name);
    } catch (e) {
      notifyActionError("下载失败", e);
    } finally {
      setDownloading(false);
    }
  };

  // 系统集成（仅本地源实现这两个方法 → 按存在性显隐，不按源分支）。
  const onReveal = async () => {
    try {
      await source.revealInOsFileManager?.(path);
    } catch (e) {
      notifyActionError("无法在资源管理器中显示", e);
    }
  };
  const onOpenExternal = async () => {
    try {
      await source.openWithOsDefaultApp?.(path);
    } catch (e) {
      notifyActionError("无法用默认程序打开", e);
    }
  };
  // 「在浏览器打开」完整效果（HTML）：本地直开磁盘文件；云端先取快照解压临时目录再开。
  // 云端要等快照 + 下载，故用 loading 态防重复点击。
  const onOpenInBrowser = async () => {
    if (openingInBrowser || !source.openInBrowser) return;
    setOpeningInBrowser(true);
    try {
      await source.openInBrowser(path);
    } catch (e) {
      notifyActionError("无法在浏览器打开", e);
    } finally {
      setOpeningInBrowser(false);
    }
  };
  // 应用内「完整预览」内置浏览器 tab：主进程经 preview:// 代理会话工作区字节，主窗口内嵌
  // 隔离 WebContents 里完整跑 JS + 相对资源。云端源专属（openInAppPreview 仅对话侧栏云端源挂）。
  const onOpenInAppPreview = async () => {
    if (openingPreview || !source.openInAppPreview) return;
    setOpeningPreview(true);
    try {
      await source.openInAppPreview(path);
    } catch (e) {
      notifyActionError("无法打开完整预览", e);
    } finally {
      setOpeningPreview(false);
    }
  };

  // Editing is offered only for a whole text file on a source that can write it
  // back: a truncated preview would drop its tail on save, so oversized/binary
  // stay read-only (download).
  const canEdit =
    result?.kind === "text" &&
    !result.truncated &&
    source.caps.edit &&
    !!source.writeBytes;
  const dirty = editing && result?.kind === "text" && draft !== result.text;

  const startEdit = () => {
    if (result?.kind === "text" && !result.truncated) {
      setDraft(result.text);
      setEditing(true);
    }
  };

  const onSave = useCallback(async () => {
    if (saving || !source.writeBytes) return;
    setSaving(true);
    try {
      await source.writeBytes(path, new Blob([draft]));
      setResult({ kind: "text", text: draft, truncated: false });
      setEditing(false);
    } catch {
      notifyError("保存失败");
    } finally {
      setSaving(false);
    }
  }, [saving, source, path, draft]);

  // Confirm before discarding unsaved edits (back to list, or cancel editing).
  const requestClose = () => {
    if (dirty && !window.confirm("有未保存的改动，确定放弃并返回？")) return;
    onClose();
  };
  const cancelEdit = () => {
    if (dirty && !window.confirm("有未保存的改动，确定放弃编辑？")) return;
    setEditing(false);
  };

  // Ctrl/Cmd+S saves while editing (and swallows the browser's save dialog).
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void onSave();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing, onSave]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-border pl-1 pr-1">
        <SimpleTooltip label="返回文件列表">
          <IconButton onClick={requestClose} aria-label="返回文件列表">
            <ChevronLeft size={16} />
          </IconButton>
        </SimpleTooltip>
        <FileText size={13} className="shrink-0 text-muted-foreground" />
        <SimpleTooltip label={path}>
          <span className="min-w-0 flex-1 truncate text-xs font-medium">
            {dirty && <span className="text-primary">● </span>}
            {name}
          </span>
        </SimpleTooltip>
        {editing ? (
          <>
            <Button
              className="shrink-0 disabled:opacity-60"
              disabled={saving}
              onClick={() => void onSave()}
              icon={
                saving ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Save size={13} />
                )
              }
            >
              保存
            </Button>
            <SimpleTooltip label="取消编辑">
              <IconButton onClick={cancelEdit} aria-label="取消编辑">
                <X size={14} />
              </IconButton>
            </SimpleTooltip>
          </>
        ) : (
          <>
            {canEdit && (
              <SimpleTooltip label="编辑">
                <IconButton onClick={startEdit} aria-label="编辑">
                  <Pencil size={14} />
                </IconButton>
              </SimpleTooltip>
            )}
            {isHtml && source.openInAppPreview && (
              <SimpleTooltip label="完整预览（内置浏览器 · 跑 JS）">
                <IconButton
                  disabled={openingPreview}
                  onClick={() => void onOpenInAppPreview()}
                  aria-label="完整预览"
                >
                  {openingPreview ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <AppWindow size={14} />
                  )}
                </IconButton>
              </SimpleTooltip>
            )}
            {isHtml && source.openInBrowser && (
              <SimpleTooltip label="在浏览器打开（完整效果）">
                <IconButton
                  disabled={openingInBrowser}
                  onClick={() => void onOpenInBrowser()}
                  aria-label="在浏览器打开"
                >
                  {openingInBrowser ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Globe size={14} />
                  )}
                </IconButton>
              </SimpleTooltip>
            )}
            {!isHtml && source.openWithOsDefaultApp && (
              <SimpleTooltip label="用默认程序打开">
                <IconButton
                  onClick={() => void onOpenExternal()}
                  aria-label="用默认程序打开"
                >
                  <ExternalLink size={14} />
                </IconButton>
              </SimpleTooltip>
            )}
            {source.revealInOsFileManager && (
              <SimpleTooltip label="在资源管理器中显示">
                <IconButton
                  onClick={() => void onReveal()}
                  aria-label="在资源管理器中显示"
                >
                  <FolderSearch size={14} />
                </IconButton>
              </SimpleTooltip>
            )}
            {source.download && (
              <SimpleTooltip label="下载文件">
                <IconButton
                  disabled={downloading}
                  onClick={() => void onDownload()}
                  aria-label="下载文件"
                >
                  {downloading ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Download size={14} />
                  )}
                </IconButton>
              </SimpleTooltip>
            )}
          </>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
            className="block h-full w-full resize-none border-0 bg-transparent px-3 py-2 font-mono text-xs leading-relaxed text-foreground outline-none"
          />
        ) : error ? (
          <InlineError onRetry={() => void load()} />
        ) : missing ? (
          <Centered>
            <p className="text-xs text-muted-foreground">文件不存在</p>
          </Centered>
        ) : result === null ? (
          <Centered>
            <Loader2
              size={18}
              className="animate-spin text-muted-foreground/50"
            />
          </Centered>
        ) : (
          <>
            {isHtml && result.kind === "text" && (
              <HtmlSourceNotice
                onOpenInAppPreview={
                  source.openInAppPreview
                    ? () => void onOpenInAppPreview()
                    : undefined
                }
                onOpenInBrowser={
                  source.openInBrowser
                    ? () => void onOpenInBrowser()
                    : undefined
                }
                onDownload={
                  source.download ? () => void onDownload() : undefined
                }
              />
            )}
            {isMarkdown && result.kind === "text" && !result.truncated ? (
              // 阅读优先：md 默认渲染预览（复用聊天渲染器）。截断的 md 会渲染不全 →
              // 回落源码 + FilePreviewBody 的截断提示。
              <div className="mx-auto max-w-3xl px-6 py-6">
                <Markdown content={result.text} />
              </div>
            ) : (
              <FilePreviewBody result={result} name={name} />
            )}
            {conversationId && <FileAuditSection state={fileAuditState} />}
          </>
        )}
      </div>
    </div>
  );
}

/**
 * HTML 源码视图顶部的指路横幅：面板内不渲染页面效果（快照已取消），完整交互效果的
 * CTA 按能力递进——「打开完整预览」（内置浏览器 tab）→「在浏览器打开」（系统浏览器）
 * →「下载」（web 兜底）；三者都无（只读源且不可传输）时仅留说明不带 CTA。
 */
function HtmlSourceNotice({
  onOpenInAppPreview,
  onOpenInBrowser,
  onDownload,
}: {
  onOpenInAppPreview?: () => void;
  onOpenInBrowser?: () => void;
  onDownload?: () => void;
}) {
  const cta = onOpenInAppPreview
    ? {
        label: "打开完整预览",
        verb: "可打开完整预览",
        onClick: onOpenInAppPreview,
      }
    : onOpenInBrowser
      ? {
          label: "在浏览器打开",
          verb: "请在浏览器打开",
          onClick: onOpenInBrowser,
        }
      : onDownload
        ? { label: "下载", verb: "请下载后在浏览器打开", onClick: onDownload }
        : null;
  const notice = cta
    ? `这是网页文件的源码，完整交互效果${cta.verb}。`
    : "这是网页文件的源码。";

  return (
    <div className="flex shrink-0 items-center gap-2 border-b border-border bg-muted/40 px-4 py-1.5 text-xs text-muted-foreground">
      <span className="min-w-0 flex-1">{notice}</span>
      {cta && (
        <button
          type="button"
          onClick={cta.onClick}
          className="shrink-0 font-medium text-primary hover:underline"
        >
          {cta.label}
        </button>
      )}
    </div>
  );
}
