import { isWebPreview } from "@/lib/preview";
import { type AgentAuditEvent, fetchFileAudit } from "@/services/audit";
import { useEffect, useState } from "react";

export type FileAuditState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; events: AgentAuditEvent[] }
  | { status: "empty" };

/**
 * 工作区文件归因链；404 / 网络失败 / 预览模式均落成 `empty`，不向 UI 泄漏「加载失败」。
 */
export function useFileAudit(
  conversationId: string | null,
  path: string | null,
  enabled: boolean,
): FileAuditState {
  const [state, setState] = useState<FileAuditState>({ status: "idle" });

  useEffect(() => {
    if (!enabled || isWebPreview() || !conversationId || !path) {
      setState({ status: "empty" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    void fetchFileAudit(conversationId, path)
      .then((res) => {
        if (cancelled) return;
        if (!res || res.data.length === 0) {
          setState({ status: "empty" });
          return;
        }
        setState({
          status: "ready",
          events: [...res.data].sort(
            (a, b) =>
              new Date(a.created_at).getTime() -
              new Date(b.created_at).getTime(),
          ),
        });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "empty" });
      });
    return () => {
      cancelled = true;
    };
  }, [conversationId, path, enabled]);

  return state;
}
