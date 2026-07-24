import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { AssistantThinking, ChatEmptyState, InputBar, UserBubble } from "../../../core/chrome/ChatBits";
import { caretVisible, entranceStyle, typeOut } from "../../../core/motion/primitives";
import { DEMO_TASK } from "../data/demo";

/*
 * 0–7s opening (scene-local 0–210 @30fps). The clean conversation page fades in
 * on its empty state, the task types into the composer character by character,
 * then Enter posts the user bubble and a 正在思考 cue bridges into the run. Mirrors
 * ChatView's flex layout exactly (message area over a max-w-3xl composer).
 */

const TYPE_START = 24; // 0.8s
const SEND_AT = 156; // ~5.2s — bubble posts, composer clears

export function OpeningMain() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const sent = frame >= SEND_AT;
  const typed = typeOut(DEMO_TASK, frame, TYPE_START, fps, 6);
  const typing = frame >= TYPE_START && frame < SEND_AT;
  const composerText = sent ? "" : typed;

  const emptyOpacity = interpolate(frame, [SEND_AT - 16, SEND_AT], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const bubble = entranceStyle(frame, SEND_AT);
  const thinking = entranceStyle(frame, SEND_AT + 24);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="relative min-h-0 flex-1">
        <div className="h-full overflow-hidden">
          {sent ? (
            <div className="mx-auto w-full max-w-3xl space-y-4 px-6 pt-10">
              <div style={{ opacity: bubble.opacity, transform: bubble.transform }}>
                <UserBubble text={DEMO_TASK} />
              </div>
              {frame >= SEND_AT + 24 && (
                <div
                  style={{
                    opacity: thinking.opacity,
                    transform: thinking.transform,
                  }}
                >
                  <AssistantThinking />
                </div>
              )}
            </div>
          ) : (
            <div style={{ opacity: emptyOpacity, height: "100%" }}>
              <ChatEmptyState />
            </div>
          )}
        </div>
      </div>
      <div className="mx-auto w-full max-w-3xl">
        <InputBar text={composerText} caret={typing && caretVisible(frame, fps)} />
      </div>
    </div>
  );
}
