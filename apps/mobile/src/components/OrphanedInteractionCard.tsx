/** Unified 已失效灰态 for orphaned interactions (提问确认统一重构 P3 · 对齐桌面). */
export function OrphanedInteractionCard({
  title,
  detail,
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <div className="pause pause-orphaned">
      <div className="pause-title">{title ?? "已失效"}</div>
      <div className="pause-context">
        {detail ?? "该确认已不可答复（回合已结束或服务已重启）。"}
      </div>
    </div>
  );
}

/** Caption for hot-path pending cards: infinite wait, no silent timeout. */
export function WaitingForDecisionHint() {
  return <div className="pause-hint">等你拍板 · 不限时</div>;
}
