import {
  type ContextualTipId,
  markTipSeen,
  shouldShowTip,
} from "@/lib/onboarding";
import { X } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";

const TIP_COPY: Record<ContextualTipId, { title: string; body: string }> = {
  inline_team_graph: {
    title: "协作图",
    body: "点节点可看每个 Agent 的实时工作。",
  },
};

/**
 * 一次性情境浮层（非多步 Tour）。`active` 为真且未 seen 时出现，可随手关闭。
 */
export function ContextualTip({
  tipId,
  children,
  active = true,
  placement = "top",
}: {
  tipId: ContextualTipId;
  children: ReactNode;
  /** Host is on screen — tip only arms when true. */
  active?: boolean;
  placement?: "top" | "bottom";
}) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (active && shouldShowTip(tipId)) setVisible(true);
    if (!active) setVisible(false);
  }, [tipId, active]);

  const dismiss = () => {
    markTipSeen(tipId);
    setVisible(false);
  };

  const copy = TIP_COPY[tipId];

  return (
    <div className="relative">
      {children}
      {visible && (
        <TipBubble
          tipId={tipId}
          title={copy.title}
          body={copy.body}
          placement={placement}
          onDismiss={dismiss}
        />
      )}
    </div>
  );
}

function TipBubble({
  tipId,
  title,
  body,
  placement,
  onDismiss,
}: {
  tipId: ContextualTipId;
  title: string;
  body: string;
  placement: "top" | "bottom";
  onDismiss: () => void;
}) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: 内嵌真 <button>（关闭），<output> 语义不符——保留 aria-live 容器。
    <div
      role="status"
      data-contextual-tip={tipId}
      className={`absolute left-1/2 z-20 w-64 -translate-x-1/2 rounded-xl border border-border bg-popover px-3 py-2.5 shadow-lg ${
        placement === "top" ? "bottom-full mb-2" : "top-full mt-2"
      }`}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-foreground">{title}</p>
          <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
            {body}
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="关闭提示"
          className="shrink-0 rounded-lg p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
