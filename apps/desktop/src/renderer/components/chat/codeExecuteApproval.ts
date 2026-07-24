/** Heuristic risk tags for code_execute approval cards — code-derived only. */

// Must mirror the backend's `_TRUNCATION_SUFFIX` (runtime/approvals.py), which is
// appended at the very end of an over-limit preview value.
const TRUNCATION_SUFFIX = "… [truncated]";

export function isPreviewTruncated(value: string): boolean {
  return value.endsWith(TRUNCATION_SUFFIX);
}

const RISK_PATTERNS: ReadonlyArray<{ label: string; pattern: RegExp }> = [
  {
    label: "联网",
    pattern:
      /\b(requests|urllib|httpx|aiohttp|fetch|axios|curl|wget|socket|http\.client)\b|import\s+requests|from\s+urllib/i,
  },
  {
    label: "写文件",
    pattern:
      /\bopen\s*\([^)]*['"][wa+]|writeFile|writeFileSync|fs\.write|shutil\.(copy|move|rmtree)|Path\s*\([^)]*\)\.write/i,
  },
  {
    label: "安装依赖",
    pattern:
      /\b(pip\s+install|npm\s+install|pnpm\s+add|yarn\s+add|apt-get|brew\s+install|conda\s+install)\b/i,
  },
  {
    label: "子进程",
    pattern:
      /\b(subprocess|os\.system|child_process|spawn|execSync|Popen)\b|child_process\.(exec|spawn)/i,
  },
];

export function deriveCodeExecuteRiskTags(code: string): string[] {
  return RISK_PATTERNS.filter(({ pattern }) => pattern.test(code)).map(
    ({ label }) => label,
  );
}

export function codeExecuteLanguage(
  args: Record<string, unknown>,
): "python" | "javascript" | "bash" {
  const lang = args.language;
  if (lang === "javascript" || lang === "bash") return lang;
  return "python";
}

/** Build a markdown fence that won't break on backticks inside the code body. */
export function fencedCodeMarkdown(code: string, language: string): string {
  let fence = "```";
  while (code.includes(fence)) fence += "`";
  return `${fence}${language}\n${code}\n${fence}`;
}
