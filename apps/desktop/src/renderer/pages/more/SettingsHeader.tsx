import type { ReactNode } from "react";

/**
 * 设置子页统一页头：标题 + 可选描述 + 右上操作槽。
 *
 * 各子页过去各写一遍 `<h1 text-xl> + <p text-sm muted>`、操作按钮摆放各异；
 * 收口到这里后排版只有一处来源，新子页直接复用、对齐天然一致。
 * `description`/`action` 收 ReactNode，便于放动态文案（如 BYOK 分支）或按钮。
 */
export function SettingsHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && (
          <p className="mt-2 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
