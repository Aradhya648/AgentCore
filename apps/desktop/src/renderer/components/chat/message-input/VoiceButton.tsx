import { IconButton } from "@/components/ui";
import { Loader2, Mic, Square } from "lucide-react";
import type { VoiceInputState } from "./useVoiceInput";

export function VoiceButton({
  state,
  onClick,
}: {
  state: VoiceInputState;
  onClick: () => void;
}) {
  const isRecording = state === "recording";
  const isProcessing = state === "processing";

  return (
    <IconButton
      size="md"
      onClick={onClick}
      disabled={isProcessing}
      aria-label={
        isRecording ? "停止录音" : isProcessing ? "转写中" : "语音输入"
      }
      aria-pressed={isRecording}
      className={
        isRecording
          ? "animate-pulse bg-destructive/10 text-destructive hover:bg-destructive/15 hover:text-destructive"
          : undefined
      }
    >
      {isProcessing ? (
        <Loader2 size={16} className="animate-spin" />
      ) : isRecording ? (
        <Square size={14} />
      ) : (
        <Mic size={16} />
      )}
    </IconButton>
  );
}
