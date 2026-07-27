import { Card } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { notifyError, notifySuccess } from "@/lib/toast";
import {
  getConversationHistoryAccess,
  setConversationHistoryAccess,
} from "@/services/conversationHistory";
import { getMemory, setMemoryEnabled } from "@/services/memory";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

/**
 * 记忆与历史对话设置（/more/memory）— 两个正交总开关：
 * 1. AI 记忆 → `users.memory_enabled`（`services/memory` → `/users/me/memory`）
 * 2. 允许 AI 查阅历史对话 → `conversation_history_access`
 *    （`services/conversationHistory` → `/users/me/memory/conversation-history-access`）
 *
 * 记忆「内容」在「文件」页「AI 记忆」里查看；这里只管行为闸。
 * 历史对话闸关闭 = Worker 不装配日志工具，且附件 conversation 深读拒绝。
 */
export function MemorySettings() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [historyAccess, setHistoryAccess] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [historyPending, setHistoryPending] = useState(false);

  useEffect(() => {
    let alive = true;
    getMemory()
      .then((d) => alive && setEnabled(d.enabled))
      .catch((e) => {
        if (!alive) return;
        notifyError(e, "加载记忆设置失败");
        setEnabled(true);
      });
    getConversationHistoryAccess()
      .then((d) => alive && setHistoryAccess(d.enabled))
      .catch((e) => {
        if (!alive) return;
        notifyError(e, "加载历史对话设置失败");
        // 定案默认 ON
        setHistoryAccess(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  const onToggle = async (next: boolean) => {
    setPending(true);
    try {
      const d = await setMemoryEnabled(next);
      setEnabled(d.enabled);
      notifySuccess(next ? "已启用 AI 记忆" : "已停用 AI 记忆");
    } catch (e) {
      notifyError(e, "设置失败");
    } finally {
      setPending(false);
    }
  };

  const onHistoryToggle = async (next: boolean) => {
    setHistoryPending(true);
    try {
      const d = await setConversationHistoryAccess(next);
      setHistoryAccess(d.enabled);
      notifySuccess(
        next ? "已允许 AI 查阅历史对话" : "已禁止 AI 查阅历史对话",
      );
    } catch (e) {
      notifyError(e, "设置失败");
    } finally {
      setHistoryPending(false);
    }
  };

  return (
    <div>
      <SettingsHeader
        title="AI 记忆"
        description="AI 会从对话里记下关于你的长期偏好与事实，并在后续对话中参考。也可按需派队员查阅历史对话原文（非常驻注入）。记忆内容可在「文件」页顶部的「AI 记忆」里查看、编辑或清空。"
      />

      <section className="mt-6 space-y-3">
        <Card className="flex items-start justify-between gap-4 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-foreground">
              启用 AI 记忆
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              停用后，AI
              不会再把记忆注入对话，也不会从新对话里自动更新记忆。已记住的内容会保留，重新启用即可恢复。
            </p>
          </div>
          {enabled === null ? (
            <Loader2
              size={16}
              className="mt-0.5 shrink-0 animate-spin text-muted-foreground/50"
            />
          ) : (
            <Switch
              checked={enabled}
              onCheckedChange={onToggle}
              disabled={pending}
              label="启用 AI 记忆"
            />
          )}
        </Card>

        <Card className="flex items-start justify-between gap-4 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-medium text-foreground">
              允许 AI 查阅历史对话
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              开启后，团队可按需检索并打开你账号下的历史对话原文与过程（经队员工具，非常驻塞入新会话）。关闭后队员不再装配该能力；偏好与事实仍走「AI
              记忆」。
            </p>
          </div>
          {historyAccess === null ? (
            <Loader2
              size={16}
              className="mt-0.5 shrink-0 animate-spin text-muted-foreground/50"
            />
          ) : (
            <Switch
              checked={historyAccess}
              onCheckedChange={onHistoryToggle}
              disabled={historyPending}
              label="允许 AI 查阅历史对话"
            />
          )}
        </Card>
      </section>
    </div>
  );
}
