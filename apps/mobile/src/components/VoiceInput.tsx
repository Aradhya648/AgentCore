// 语音输入 UI (手机端) —— 麦克风按钮 + 录音态提示条。纯展示叶子；状态机/转写逻辑在
// @/lib/useVoiceInput。样式走手机 styles.css (.voice-*) + design-tokens 语义色，不复用桌面类。
import type { VoiceInputState } from "@/lib/useVoiceInput";
import { Loader2, Mic, Square, X } from "lucide-react";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** composer 行内的麦克风按钮：idle=麦克风、recording=停止方块 (脉冲红)、processing=转圈。 */
export function VoiceButton({
  state,
  disabled,
  onClick,
}: {
  state: VoiceInputState;
  disabled?: boolean;
  onClick: () => void;
}) {
  const isRecording = state === "recording";
  const isProcessing = state === "processing";
  return (
    <button
      type="button"
      className={`voice-btn${isRecording ? " voice-btn-recording" : ""}`}
      onClick={onClick}
      disabled={disabled || isProcessing}
      aria-label={
        isRecording ? "停止录音" : isProcessing ? "转写中" : "语音输入"
      }
      aria-pressed={isRecording}
    >
      {isProcessing ? (
        <Loader2 size={18} className="voice-spin" />
      ) : isRecording ? (
        <Square size={16} />
      ) : (
        <Mic size={18} />
      )}
    </button>
  );
}

function Waveform() {
  return (
    <span className="voice-wave" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className="voice-wave-bar"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  );
}

/** 录音态提示条 (composer 上方)：红点 + 时长 + 波形 + interim 实时文本 + 取消。 */
export function VoiceRecordingBar({
  duration,
  interimText,
  onCancel,
}: {
  duration: number;
  interimText: string;
  onCancel: () => void;
}) {
  return (
    <div className="voice-bar" aria-live="polite">
      <div className="voice-bar-head">
        <span className="voice-dot" aria-hidden />
        <span className="voice-time">{formatDuration(duration)}</span>
        <Waveform />
        <span className="voice-hint">聆听中，点停止填入草稿</span>
        <button
          type="button"
          className="voice-cancel"
          onClick={onCancel}
          aria-label="取消录音"
        >
          <X size={16} />
        </button>
      </div>
      {interimText && <div className="voice-interim">{interimText}</div>}
    </div>
  );
}
