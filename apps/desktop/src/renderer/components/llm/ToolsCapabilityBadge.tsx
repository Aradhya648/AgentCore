import { AlertTriangle, Wrench } from "lucide-react";

/** Probe result for tool-calling support (设置 · 模型配置). */
export function ToolsCapabilityBadge({
  supportsTools,
}: {
  supportsTools: boolean | null | undefined;
}) {
  if (supportsTools === true) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-success">
        <Wrench size={14} />
        支持工具调用
      </span>
    );
  }
  if (supportsTools === false) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <AlertTriangle size={14} />
        仅对话
      </span>
    );
  }
  return <span className="text-xs text-muted-foreground">未测试能力</span>;
}
