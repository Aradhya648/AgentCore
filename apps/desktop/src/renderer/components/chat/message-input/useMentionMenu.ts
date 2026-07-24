import { hasLocalFiles } from "@/lib/capabilities";
import {
  type IndexedEntry,
  buildDirListing,
  filterEntries,
  loadFileIndex,
} from "@/lib/fileIndex";
import type { FileSource } from "@/lib/fileSource";
import { fetchMessageWindow } from "@/services/messages";
import { searchAll } from "@/services/search";
import {
  type Dispatch,
  type KeyboardEvent,
  type RefObject,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  CONV_MENTION_MSG_LIMIT,
  type PendingAttachment,
  buildMentionSources,
  detectMention,
  formatConversationContext,
} from "./composerAttachments";
import {
  pickLocalFileAttachment,
  stageRootFileAttachment,
} from "./resideAttachment";
import { resolveFolderFromIndexedEntry } from "./resolveAttachmentFolder";
import type { MenuMode } from "./types";

export type AttachmentProjectHint = {
  folderId: string;
  folderName: string;
};

export function useMentionMenu({
  conversationId,
  value,
  setValue,
  attachments,
  setAttachments,
  textareaRef,
  onAttachmentProjectHint,
}: {
  conversationId: string | null;
  value: string;
  setValue: Dispatch<SetStateAction<string>>;
  attachments: PendingAttachment[];
  setAttachments: Dispatch<SetStateAction<PendingAttachment[]>>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  /** Draft-only: @ / browse attach from a project → suggest filing into it (B4). */
  onAttachmentProjectHint?: (hint: AttachmentProjectHint) => void;
}) {
  const [menuMode, setMenuMode] = useState<MenuMode>(null);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuError, setMenuError] = useState<string | null>(null);
  const [fileIndex, setFileIndex] = useState<IndexedEntry[]>([]);
  const [dirIndex, setDirIndex] = useState<IndexedEntry[]>([]);
  const [sourceCount, setSourceCount] = useState(0);
  const [indexLoading, setIndexLoading] = useState(false);
  const [convItems, setConvItems] = useState<IndexedEntry[]>([]);
  const indexLoadedRef = useRef(false);
  const sourcesRef = useRef<Map<string, FileSource>>(new Map());
  const mentionRangeRef = useRef<{ start: number; end: number } | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);

  const entries = useMemo(
    () =>
      [...dirIndex, ...fileIndex].sort((a, b) =>
        a.display.localeCompare(b.display, "zh"),
      ),
    [dirIndex, fileIndex],
  );
  const fileItems = useMemo(
    () => filterEntries(entries, query),
    [entries, query],
  );
  const items = useMemo(
    () => [...convItems, ...fileItems],
    [convItems, fileItems],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: query/menuMode are intentional re-run keys
  useEffect(() => {
    setActiveIndex(0);
  }, [query, menuMode]);

  useEffect(() => {
    const q = query.trim();
    if (!menuMode || !q) {
      setConvItems([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void searchAll(q, { types: ["conversation"], limit: 6 })
        .then((res) => {
          if (cancelled) return;
          const section = res.sections.find((s) => s.type === "conversation");
          const candidates = (section?.items ?? []).map<IndexedEntry>((it) => ({
            sourceId: "conversation",
            sourceLabel: "对话",
            relPath: it.id,
            name: it.title || "未命名对话",
            display: it.title || "未命名对话",
            kind: "conversation",
          }));
          setConvItems(candidates);
        })
        .catch(() => {
          if (!cancelled) setConvItems([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, menuMode]);

  const ensureIndex = useCallback(async () => {
    if (indexLoadedRef.current) return;
    setIndexLoading(true);
    try {
      const sources = await buildMentionSources(conversationId);
      sourcesRef.current = new Map(sources.map((s) => [s.id, s]));
      const { files, dirs, sourceCount: count } = await loadFileIndex(sources);
      setFileIndex(files);
      setDirIndex(dirs);
      setSourceCount(count);
      indexLoadedRef.current = true;
    } catch {
      setMenuError("读取文件列表失败");
    } finally {
      setIndexLoading(false);
    }
  }, [conversationId]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: conversationId is an intentional re-run key
  useEffect(() => {
    indexLoadedRef.current = false;
    setFileIndex([]);
    setDirIndex([]);
    setSourceCount(0);
    sourcesRef.current = new Map();
  }, [conversationId]);

  const closeMenu = useCallback(() => {
    setMenuMode(null);
    setMenuError(null);
    mentionRangeRef.current = null;
  }, []);

  const openMention = useCallback(
    (start: number, end: number, q: string) => {
      mentionRangeRef.current = { start, end };
      setQuery(q);
      setMenuMode("mention");
      setMenuError(null);
      void ensureIndex();
    },
    [ensureIndex],
  );

  const openBrowse = useCallback(() => {
    if (menuMode === "browse") {
      closeMenu();
      return;
    }
    mentionRangeRef.current = null;
    setQuery("");
    setMenuMode("browse");
    setMenuError(null);
    void ensureIndex();
    requestAnimationFrame(() => searchInputRef.current?.focus());
  }, [menuMode, closeMenu, ensureIndex]);

  const syncMention = useCallback(
    (text: string, caret: number) => {
      const m = detectMention(text, caret);
      if (m) {
        openMention(m.start, caret, m.query);
      } else if (menuMode === "mention") {
        closeMenu();
      }
    },
    [menuMode, openMention, closeMenu],
  );

  const attachEntry = useCallback(
    async (entry: IndexedEntry) => {
      const key = `${entry.kind}:${entry.sourceId}:${entry.relPath}`;
      if (attachments.some((a) => a.key === key)) {
        closeMenu();
        textareaRef.current?.focus();
        return;
      }

      let next: PendingAttachment | null = null;
      if (entry.kind === "conversation") {
        let win: Awaited<ReturnType<typeof fetchMessageWindow>>;
        try {
          win = await fetchMessageWindow(entry.relPath, {
            limit: CONV_MENTION_MSG_LIMIT,
          });
        } catch {
          setMenuError("读取对话失败");
          return;
        }
        const { text, truncated } = formatConversationContext(win.messages);
        if (!text) {
          setMenuError("该对话暂无可引用的内容");
          return;
        }
        next = {
          id: crypto.randomUUID(),
          key,
          name: entry.name,
          path: "对话",
          text,
          truncated: truncated || win.hasMoreBefore,
          kind: "conversation",
          conversationId: entry.relPath,
        };
      } else if (entry.kind === "dir") {
        const listing = buildDirListing(fileIndex, entry);
        if (listing.fileCount === 0) {
          setMenuError("该目录内没有可索引的文件");
          return;
        }
        next = {
          id: crypto.randomUUID(),
          key,
          name: entry.name,
          path: entry.display,
          text: listing.text,
          truncated: listing.truncated,
          kind: "dir",
        };
      } else {
        // 文件：引用即驻留——主进程复制进工作区 attachments/（含二进制 xlsx）。
        // 本地根 sourceId = ``local:<rootId>`` 或 ``local:<rootId>:<subpath>``。
        const localMatch = /^local:([^:]+)(?::(.*))?$/.exec(entry.sourceId);
        if (localMatch && hasLocalFiles()) {
          const rootId = localMatch[1];
          const subBase = (localMatch[2] || "").replace(/^\/+|\/+$/g, "");
          const containerRel = subBase
            ? `${subBase}/${entry.relPath}`.replace(/\/+/g, "/")
            : entry.relPath;
          const staged = await stageRootFileAttachment(
            conversationId,
            rootId,
            containerRel,
          );
          if (!staged.ok) {
            setMenuError(staged.reason);
            return;
          }
          next = {
            id: crypto.randomUUID(),
            key,
            name: staged.name,
            path: staged.path,
            text: staged.text,
            truncated: staged.truncated,
            kind: "file",
            workspacePath: staged.workspacePath,
            stagingId: staged.stagingId,
            binary: staged.binary,
          };
        } else {
          const source = sourcesRef.current.get(entry.sourceId);
          if (!source) {
            setMenuError("文件来源已失效，请重试");
            return;
          }
          let res: Awaited<ReturnType<FileSource["read"]>>;
          try {
            res = await source.read(entry.relPath);
          } catch {
            setMenuError("读取文件失败");
            return;
          }
          if (res.kind !== "text") {
            setMenuError(
              res.kind === "image"
                ? "暂不支持图片附件（模型尚无视觉能力）"
                : res.kind === "too-large"
                  ? "文件过大，无法作为附件"
                  : "二进制文件请用回形针从本机选择（将驻留到工作区）",
            );
            return;
          }
          next = {
            id: crypto.randomUUID(),
            key,
            name: entry.name,
            path: entry.display,
            text: res.text,
            truncated: res.truncated,
            kind: "file",
          };
        }
      }

      const attachment = next;
      setAttachments((prev) => [...prev, attachment]);

      if (!conversationId && onAttachmentProjectHint) {
        const resolved = resolveFolderFromIndexedEntry(entry);
        if (resolved) onAttachmentProjectHint(resolved);
      }

      const range = mentionRangeRef.current;
      if (menuMode === "mention" && range) {
        const updated = value.slice(0, range.start) + value.slice(range.end);
        setValue(updated);
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (el) {
            el.focus();
            el.selectionStart = el.selectionEnd = range.start;
          }
        });
      } else {
        textareaRef.current?.focus();
      }
      closeMenu();
    },
    [
      attachments,
      conversationId,
      fileIndex,
      value,
      menuMode,
      closeMenu,
      onAttachmentProjectHint,
      setAttachments,
      setValue,
      textareaRef,
    ],
  );

  const handleAddRoot = useCallback(async () => {
    const root = await window.fsApi.addRoot();
    if (!root) return;
    indexLoadedRef.current = false;
    await ensureIndex();
  }, [ensureIndex]);

  /** 回形针 / 菜单：从本机任选文件（含工作区外），主进程驻留。 */
  const pickLocalFile = useCallback(async () => {
    setMenuError(null);
    const res = await pickLocalFileAttachment(conversationId);
    if (res === null) return;
    if (!res.ok) {
      setMenuError(res.reason);
      // 回形针直开选择器时菜单可能未开——仍把错误挂在 menuError，并确保 browse 可见。
      if (!menuMode) {
        setMenuMode("browse");
        mentionRangeRef.current = null;
      }
      return;
    }
    const key = `picked:${res.name}:${res.workspacePath ?? res.stagingId ?? res.name}`;
    if (attachments.some((a) => a.key === key)) {
      closeMenu();
      return;
    }
    setAttachments((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        key,
        name: res.name,
        path: res.path,
        text: res.text,
        truncated: res.truncated,
        kind: "file",
        workspacePath: res.workspacePath,
        stagingId: res.stagingId,
        binary: res.binary,
      },
    ]);
    closeMenu();
    textareaRef.current?.focus();
  }, [
    attachments,
    closeMenu,
    conversationId,
    menuMode,
    setAttachments,
    textareaRef,
  ]);

  const handleMenuNavKey = useCallback(
    (e: KeyboardEvent): boolean => {
      if (!menuMode) return false;
      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setActiveIndex((i) => Math.min(i + 1, Math.max(items.length - 1, 0)));
          return true;
        case "ArrowUp":
          e.preventDefault();
          setActiveIndex((i) => Math.max(i - 1, 0));
          return true;
        case "Enter":
          if (items[activeIndex]) {
            e.preventDefault();
            void attachEntry(items[activeIndex]);
            return true;
          }
          return false;
        case "Tab":
          if (items[activeIndex]) {
            e.preventDefault();
            void attachEntry(items[activeIndex]);
            return true;
          }
          return false;
        case "Escape":
          e.preventDefault();
          closeMenu();
          textareaRef.current?.focus();
          return true;
        default:
          return false;
      }
    },
    [menuMode, items, activeIndex, attachEntry, closeMenu, textareaRef],
  );

  return {
    menuMode,
    items,
    activeIndex,
    indexLoading,
    menuError,
    query,
    sourceCount,
    indexLoadedRef,
    searchInputRef,
    setQuery,
    setActiveIndex,
    openBrowse,
    syncMention,
    attachEntry,
    closeMenu,
    handleMenuNavKey,
    handleAddRoot,
    pickLocalFile,
  };
}
