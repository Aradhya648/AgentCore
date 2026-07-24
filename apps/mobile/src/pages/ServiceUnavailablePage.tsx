interface ServiceUnavailablePageProps {
  reason: string;
  onRetry: () => void;
}

/**
 * Shown when the backend can't be reached on startup, in place of a login form
 * (or an erroring chat page) that would just fail. Mirrors the desktop's
 * ServiceUnavailablePage and reuses LoginPage's centered card layout so the boot
 * experience stays consistent.
 */
export function ServiceUnavailablePage({
  reason,
  onRetry,
}: ServiceUnavailablePageProps) {
  return (
    <div className="screen center">
      <div className="card">
        <h1>AgentCore 手机端</h1>
        <p className="muted">服务暂时不可用</p>
        <div className="error">{reason}</div>
        <button type="button" onClick={onRetry}>
          重试
        </button>
      </div>
    </div>
  );
}
