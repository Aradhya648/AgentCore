import type { ConversationSummary } from "@/api/conversations";
import type { SearchSection } from "@/api/search";
import { Modal } from "@/components/Modal";
import { copyText } from "@/lib/messageExport";
// Shared conversation-management UI primitives (对话管理 · 复用于历史抽屉).
//
// Extracted from the old ConversationsPage so the 历史 drawer (ConversationDrawer) and any
// future「全部对话」page render the same touch-native menus / dialogs / search results. Pure
// presentational — no data fetching; the host owns state + the api calls.
import { type ReactNode, useState } from "react";

/** Compact recency label: time for today, else month/day. */
export function timeLabel(iso: string): string {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

/** Keyword hits grouped by section (对话 / 消息); a message hit highlights its match window. */
export function SearchResults({
  sections,
  searching,
  onOpen,
}: {
  sections: SearchSection[] | null;
  searching: boolean;
  onOpen: (id: string | null) => void;
}) {
  if (sections === null) {
    return <p className="muted hint">{searching ? "搜索中…" : ""}</p>;
  }
  if (sections.length === 0) {
    return <p className="muted hint">没有匹配结果。</p>;
  }
  return (
    <div className="list">
      {sections.map((section) => (
        <div key={section.type} className="search-section">
          <div className="search-section-title">
            {section.type === "conversation" ? "对话" : "消息"}
          </div>
          {section.items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="conv"
              onClick={() =>
                onOpen(
                  section.type === "message"
                    ? (item.conversation_id ?? null)
                    : item.id,
                )
              }
            >
              <span className="conv-title">{item.title || "新对话"}</span>
              {item.snippet && (
                <span className="conv-snippet">
                  <Highlight
                    text={item.snippet}
                    start={item.match_start ?? null}
                    end={item.match_end ?? null}
                  />
                </span>
              )}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Render a snippet with its matched span emphasised (offsets index into `text`). */
function Highlight({
  text,
  start,
  end,
}: {
  text: string;
  start: number | null;
  end: number | null;
}) {
  if (
    start === null ||
    end === null ||
    start < 0 ||
    end > text.length ||
    start >= end
  ) {
    return <>{text}</>;
  }
  return (
    <>
      {text.slice(0, start)}
      <mark className="hl">{text.slice(start, end)}</mark>
      {text.slice(end)}
    </>
  );
}

/** Bottom action sheet for one conversation's management actions (touch-native menu). */
export function ActionSheet({
  conv,
  archivedView,
  onClose,
  onRename,
  onArchive,
  onDelete,
}: {
  conv: ConversationSummary;
  archivedView: boolean;
  onClose: () => void;
  onRename: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const [copiedId, setCopiedId] = useState(false);
  return (
    <Modal className="sheet" onClose={onClose} label="对话操作">
      <div className="sheet-title">{conv.title || "新对话"}</div>
      <button type="button" className="sheet-item" onClick={onRename}>
        重命名
      </button>
      <button type="button" className="sheet-item" onClick={onArchive}>
        {archivedView ? "恢复" : "归档"}
      </button>
      <button
        type="button"
        className="sheet-item"
        onClick={() => {
          void copyText(conv.id).then((ok) => {
            if (!ok) return;
            setCopiedId(true);
            window.setTimeout(() => setCopiedId(false), 1500);
          });
        }}
      >
        {copiedId ? "已复制对话 ID" : "复制对话 ID"}
      </button>
      <button
        type="button"
        className="sheet-item sheet-danger"
        onClick={onDelete}
      >
        删除
      </button>
      <button
        type="button"
        className="sheet-item sheet-cancel"
        onClick={onClose}
      >
        取消
      </button>
    </Modal>
  );
}

/** Centered dialog to rename a conversation. */
export function RenameDialog({
  conv,
  busy,
  onClose,
  onSave,
}: {
  conv: ConversationSummary;
  busy: boolean;
  onClose: () => void;
  onSave: (title: string) => void;
}) {
  const [title, setTitle] = useState(conv.title ?? "");
  return (
    <Dialog onClose={onClose}>
      <div className="dialog-title">重命名对话</div>
      <input
        className="dialog-input"
        value={title}
        // biome-ignore lint/a11y/noAutofocus: a rename dialog should focus its field
        autoFocus
        placeholder="对话标题"
        disabled={busy}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && title.trim()) onSave(title.trim());
        }}
      />
      <div className="dialog-actions">
        <button
          type="button"
          className="link"
          disabled={busy}
          onClick={onClose}
        >
          取消
        </button>
        <button
          type="button"
          disabled={busy || !title.trim()}
          onClick={() => onSave(title.trim())}
        >
          保存
        </button>
      </div>
    </Dialog>
  );
}

/** Centered confirm dialog for a destructive action. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog onClose={onCancel}>
      <div className="dialog-title">{title}</div>
      <div className="dialog-msg">{message}</div>
      <div className="dialog-actions">
        <button
          type="button"
          className="link"
          disabled={busy}
          onClick={onCancel}
        >
          取消
        </button>
        <button
          type="button"
          className="dialog-danger"
          disabled={busy}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}

function Dialog({
  children,
  onClose,
}: {
  children: ReactNode;
  onClose: () => void;
}) {
  return (
    <Modal className="dialog" onClose={onClose} label="对话框">
      {children}
    </Modal>
  );
}
