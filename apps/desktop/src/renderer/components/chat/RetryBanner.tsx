import { Button, IconButton } from "@/components/ui";
import { statusAccentText, statusChip } from "@/components/ui/tone-presets";
import { cn } from "@/lib/utils";
import { RECONNECT_BANNER } from "@/services/turns/helpers";
import {
  useActiveError,
  useActiveErrorAction,
  useActiveRetry,
  useConversationStore,
} from "@/stores/conversation";
import { AlertTriangle, KeyRound, RotateCw, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

/**
 * Banner for a failed turn (send / regenerate transport error). Shown just above
 * the input in chat ({@link import("./ChatView")}) and in the canvas 指挥台
 * ({@link import("../graph/CanvasDecisionPanel")}, 前端UX设计.md §6.2) — in canvas
 * mode ChatView is unmounted, so without it a transport failure would be
 * invisible / unretriable there. The retry closure re-runs that exact turn; the
 * optional action routes the user to fix the cause (e.g. "去配置" → model config
 * for a missing BYOK key); dismissing only hides the banner.
 *
 * Tone: a failed turn is always red `destructive`; the optional 去配置 button is the
 * blue `primary` action that routes to fix the cause (e.g. a missing BYOK key).
 *
 * Conversation-scoped (reads the active conversation's error state) and therefore
 * self-contained wherever it mounts — mirrors {@link import("./ApprovalPrompt").ApprovalPrompt}
 * / {@link import("./ResumePrompt").ResumePrompt}.
 *
 * Reconnect drops ({@link RECONNECT_BANNER} · rejoinLiveTurn) label the button
 * 「重连」; every other retryable failure keeps 「重试」.
 */
export function RetryBanner() {
  const error = useActiveError();
  const retry = useActiveRetry();
  const action = useActiveErrorAction();
  const clearError = useConversationStore((s) => s.clearError);
  const navigate = useNavigate();
  if (!error) return null;

  const retryLabel = error === RECONNECT_BANNER ? "重连" : "重试";

  return (
    <div
      className={cn(
        "mx-4 mb-2 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm",
        statusChip.destructive,
      )}
    >
      <AlertTriangle
        size={15}
        className={cn("shrink-0", statusAccentText.destructive)}
      />
      <span className="min-w-0 flex-1">{error}</span>
      {action && (
        <Button
          variant="primary"
          className="shrink-0"
          icon={<KeyRound size={13} />}
          onClick={() => {
            clearError();
            navigate(action.href);
          }}
        >
          {action.label}
        </Button>
      )}
      {retry && (
        <Button
          variant="destructive"
          className="shrink-0"
          icon={<RotateCw size={13} />}
          onClick={() => retry()}
        >
          {retryLabel}
        </Button>
      )}
      <IconButton
        onClick={() => clearError()}
        aria-label="关闭"
        className="text-destructive/70 hover:bg-transparent hover:text-destructive"
      >
        <X size={14} />
      </IconButton>
    </div>
  );
}
