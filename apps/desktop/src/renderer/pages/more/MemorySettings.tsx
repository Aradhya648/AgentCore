import { Switch } from "@/components/ui/Switch";
import { notifyError, notifySuccess } from "@/lib/toast";
import { getMemory, setMemoryEnabled } from "@/services/memory";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { SettingsHeader } from "./SettingsHeader";

/**
 * 记忆设置（/more/memory）— 长期 AI 记忆的**总开关**（Agent记忆与知识系统 §一）。
 *
 * 记忆「内容」是个文件，在「文件」页顶部的「AI 记忆」里查看 / 编辑 / 清空；这里只管
 * 「行为」——是否启用。停用＝既不注入对话也不再自动增长（隐私下车口）；记忆正文仍保留，
 * 重新启用即恢复。落到 `users.memory_enabled`（见 `services/memory` → `/users/me/memory`）。
 */
export function MemorySettings() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let alive = true;
    getMemory()
      .then((d) => alive && setEnabled(d.enabled))
      .catch((e) => {
        if (!alive) return;
        notifyError(e, "加载记忆设置失败");
        setEnabled(true);
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

  return (
    <div>
      <SettingsHeader
        title="AI 记忆"
        description="AI 会从对话里记下关于你的长期偏好与事实，并在后续对话中参考。记忆内容可在「文件」页顶部的「AI 记忆」里查看、编辑或清空。"
      />

      <section className="mt-6">
        <div className="flex items-start justify-between gap-4 rounded-xl border border-border bg-card px-4 py-3">
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
        </div>
      </section>
    </div>
  );
}
