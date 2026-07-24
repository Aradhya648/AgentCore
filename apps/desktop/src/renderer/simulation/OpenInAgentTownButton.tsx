import { Button } from "@/components/ui";
import { hasAgentTownLauncher } from "@/lib/capabilities";
import { notifyActionError } from "@/lib/toast";
import { persistAgentTownSession } from "@/services/agentTownSession";
import { ExternalLink } from "lucide-react";
import { useState } from "react";

function formatLaunchFailure(message: string, candidates?: string[]): string {
  if (candidates?.length && !message.includes("已检查路径")) {
    return `${message}\n已检查路径：\n${candidates.map((p) => `  · ${p}`).join("\n")}`;
  }
  return message;
}

export function OpenInAgentTownButton({
  runId,
  size = "sm",
  variant = "neutral",
  onLaunchError,
}: {
  runId?: string;
  size?: "sm" | "md";
  variant?: "neutral" | "ghost" | "primary";
  /** Optional: surface failure detail in the parent (e.g. launcher page). */
  onLaunchError?: (detail: { message: string; candidates?: string[] }) => void;
}) {
  const [launching, setLaunching] = useState(false);

  if (!hasAgentTownLauncher()) return null;

  const onLaunch = async () => {
    setLaunching(true);
    try {
      await persistAgentTownSession();
      const result = await window.agentTownApi?.launch(
        runId ? { runId } : undefined,
      );
      if (!result?.ok) {
        const message = result?.message ?? "启动失败";
        const candidates = result && !result.ok ? result.candidates : undefined;
        onLaunchError?.({ message, candidates });
        notifyActionError(
          "无法打开 AgentTown",
          new Error(formatLaunchFailure(message, candidates)),
        );
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      onLaunchError?.({ message });
      notifyActionError("无法打开 AgentTown", err);
    } finally {
      setLaunching(false);
    }
  };

  return (
    <Button
      variant={variant}
      size={size}
      disabled={launching}
      onClick={() => void onLaunch()}
      title="在独立 AgentTown 客户端中观看（推荐）"
    >
      <ExternalLink size={14} className="mr-1.5 shrink-0" />
      {launching ? "启动中…" : "在 AgentTown 中打开"}
    </Button>
  );
}
