// 非阻塞提问卡 (ask_user blocking=false; 前端技术与架构 §七 · 手机端全新实现，对标桌面
// components/chat/NonBlockingAskCard.tsx)。AI 在回合中途问了你一句、但没阻塞（已按默认继续），
// 把问题 + 建议选项呈现在它时间线的原位；点任一选项即「回填输入框」（不自动发，留你改），不回
// 复则保持默认。只消费 fold 的旁路 {@link extractAsks} 内容（不入 ProjectedTurn、不触发
// conformance），你的答复随下一条消息发出——故连新 API 都不需要。
import type { NonBlockingAsk } from "@/protocol/fold";
import type { AskOption } from "@agentcore/contract-types";
import { CircleHelp, CornerDownLeft } from "lucide-react";

export function NonBlockingAskCard({
  ask,
  onFill,
}: {
  ask: NonBlockingAsk;
  onFill: (text: string) => void;
}) {
  const multi = ask.questions.length > 1;
  // 多问时把题干并进回填文本（「题干：选项」）以免歧义，单问时只回填选项值——与桌面一致。
  const pick = (prompt: string, value: string) =>
    onFill(multi && prompt ? `${prompt}：${value}` : value);

  return (
    <div className="ask">
      <div className="ask-head">
        <CircleHelp size={14} className="ask-icon" aria-hidden />
        <span>想跟你确认（不阻塞 · 已按默认继续）</span>
      </div>
      <div className="ask-q">{ask.question}</div>
      {ask.context && <div className="ask-context">{ask.context}</div>}

      {ask.assumptions.length > 0 && (
        <div className="ask-assume">
          <div className="ask-assume-label">我先按这些默认推进</div>
          {ask.assumptions.map((a) => (
            <div key={a.id} className="ask-assume-row">
              <span className="ask-assume-k">{a.label}</span>
              <span className="ask-assume-v">{a.value}</span>
            </div>
          ))}
        </div>
      )}

      {ask.questions.map((q) => {
        // 统一 chip 形：选择题用其 options；文本题把 default 当作唯一 chip（无默认则不出 chip）。
        const chips: AskOption[] =
          q.kind === "text"
            ? q.default
              ? [{ label: q.default }]
              : []
            : q.options;
        return (
          <div key={q.id} className="ask-question">
            <div className="ask-prompt">{q.prompt}</div>
            {chips.length > 0 && (
              <div className="ask-chips">
                {chips.map((opt) => {
                  const isDefault = !!q.default && opt.label === q.default;
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      className="ask-chip"
                      onClick={() => pick(q.prompt, opt.label)}
                    >
                      <span>{opt.label}</span>
                      {opt.recommended && (
                        <span className="ask-badge ask-badge-rec">推荐</span>
                      )}
                      {isDefault && <span className="ask-badge">默认</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}

      {ask.styleOptions.length > 0 && (
        <div className="ask-chips">
          {ask.styleOptions.map((s) => (
            <button
              key={s.id}
              type="button"
              className="ask-chip"
              onClick={() => pick("风格", s.label)}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {ask.formatOptions.length > 0 && (
        <div className="ask-chips">
          {ask.formatOptions.map((s) => (
            <button
              key={s.id}
              type="button"
              className="ask-chip"
              onClick={() => pick("形态", s.label)}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      <div className="ask-hint">
        <CornerDownLeft size={12} className="ask-icon" aria-hidden />
        <span>点选项即回填到输入框，可改后发送；不回复就按默认继续。</span>
      </div>
    </div>
  );
}
