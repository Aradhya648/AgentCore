import { Button, IconButton } from "@/components/ui";
import { hasTerminalRun } from "@/lib/capabilities";
import { copyText } from "@/lib/clipboard";
import { runTerminalBash } from "@/lib/terminalFeedback";
import { usePersistentDisclosure } from "@/stores/disclosure";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FileCode2,
  Terminal,
  WrapText,
} from "lucide-react";
import {
  type ComponentPropsWithoutRef,
  type ReactNode,
  isValidElement,
  useState,
} from "react";

/** Recursively concatenate the text of a React subtree.
 *
 * `rehype-highlight` replaces the code body with token <span>s, so the raw
 * source can't be read from a single child — it must be gathered by walking.
 * Exported so the diagram router (Markdown.tsx) can pull the raw fence body for
 * ```mermaid / ```markmap blocks.
 */
export function nodeText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (isValidElement(node)) {
    return nodeText((node.props as { children?: ReactNode }).children);
  }
  return "";
}

/** Beyond this many lines a code block collapses behind a "展开全部" toggle so a
 * long paste never dominates the bubble. */
const COLLAPSE_LINES = 24;

/** Stable-per-content fingerprint (djb2) — CodeBlock has no turn/message id (it's
 * rendered generically by Markdown's `<pre>` mapper), so the fold/wrap prefs key off
 * the code text itself; the disclosure store adds the conversation scope. */
function hashCode(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++)
    h = (Math.imul(h, 33) + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

/** The `<code>` child's props we read: its `language-x` class, and the file path
 * stashed by {@link rehypeCodeMeta} (read both casings — react-markdown may emit
 * either the hast `dataFile` or the DOM `data-file`). */
type CodeChildProps = {
  className?: string;
  dataFile?: string;
  "data-file"?: string;
};

/**
 * Custom `<pre>` for markdown fenced code: a header (filename / language + wrap
 * toggle + copy), an aligned line-number gutter, and a collapse toggle for long
 * blocks. The body defaults to no-wrap (horizontal scroll); the wrap toggle
 * switches to soft-wrap and hides the gutter (line numbers can't align once
 * lines wrap).
 */
export function CodeBlock({
  children,
  ...props
}: ComponentPropsWithoutRef<"pre">) {
  const codeProps: CodeChildProps = isValidElement(children)
    ? (children.props as CodeChildProps)
    : {};
  const className = codeProps.className ?? "";
  const lang = /language-([\w-]+)/.exec(className)?.[1] ?? "";
  const file = codeProps["data-file"] ?? codeProps.dataFile ?? "";
  const text = nodeText(children);
  // 「展开全部」+「自动换行」按代码内容指纹持久化——同一对话内同一段代码，跨切对话/刷新记住。
  const disclosureKey = `code:${hashCode(text)}`;
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = usePersistentDisclosure(
    `${disclosureKey}:wrap`,
    false,
  );
  const [expanded, setExpanded] = usePersistentDisclosure(
    `${disclosureKey}:exp`,
    false,
  );
  // Logical lines, ignoring a single trailing newline so the gutter doesn't
  // number a phantom empty last line.
  const lineCount = text.replace(/\n$/, "").split("\n").length;
  const collapsible = lineCount > COLLAPSE_LINES;
  const collapsed = collapsible && !expanded;
  const showGutter = !wrap && lineCount > 1;

  const onCopy = async () => {
    if (await copyText(text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const runnable = hasTerminalRun() && (lang === "bash" || lang === "sh");

  const onRunInTerminal = () => {
    void runTerminalBash(text);
  };

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-title">
          {file ? (
            <>
              <FileCode2 size={12} className="shrink-0" />
              <span className="code-block-file">{file}</span>
              {lang && <span className="code-block-lang">{lang}</span>}
            </>
          ) : (
            <span className="code-block-lang">{lang || "text"}</span>
          )}
        </span>
        <span className="code-block-actions">
          <IconButton
            onClick={() => setWrap((v) => !v)}
            className="code-block-action size-auto rounded-none p-0 hover:bg-transparent"
            aria-label={wrap ? "取消自动换行" : "自动换行"}
            aria-pressed={wrap}
          >
            <WrapText size={13} />
          </IconButton>
          <Button
            variant="ghost"
            onClick={onCopy}
            className="code-block-action h-auto gap-1 px-0 py-0 hover:bg-transparent"
            aria-label="复制代码"
            icon={copied ? <Check size={13} /> : <Copy size={13} />}
          >
            {copied ? "已复制" : "复制"}
          </Button>
          {runnable && (
            <Button
              variant="ghost"
              onClick={onRunInTerminal}
              className="code-block-action h-auto gap-1 px-0 py-0 hover:bg-transparent"
              aria-label="在终端运行"
              icon={<Terminal size={13} />}
            >
              在终端运行
            </Button>
          )}
        </span>
      </div>
      <div
        className={`code-block-body${wrap ? " wrap" : ""}${
          collapsed ? " collapsed" : ""
        }`}
      >
        {showGutter && (
          <span className="code-block-gutter" aria-hidden>
            {Array.from({ length: lineCount }, (_, i) => i + 1).join("\n")}
          </span>
        )}
        <pre {...props}>{children}</pre>
      </div>
      {collapsible && (
        <Button
          variant="ghost"
          onClick={() => setExpanded((v) => !v)}
          className="code-block-expand h-auto hover:bg-transparent"
          icon={expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        >
          {expanded ? "收起" : `展开全部 ${lineCount} 行`}
        </Button>
      )}
    </div>
  );
}
