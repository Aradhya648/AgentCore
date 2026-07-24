import {
  TurnComposer,
  type TurnComposerVariant,
} from "./message-input/TurnComposer";

/**
 * The chat view's composer: the unified {@link TurnComposer} in its chat chrome
 * (bottom padding, default placeholder, 后台云端 offered). The canvas 命令栏
 * ({@link import("../graph/CanvasCommandBar").CanvasCommandBar}) is the SAME core in
 * canvas chrome — one composer, two skins, single draft per conversation.
 *
 * `variant` is chosen by ChatView: `bar` for the session bottom dock, `card`
 * (default) for the centered new-chat composer. Canvas keeps its own full card.
 */
export function MessageInput({
  className,
  variant = "card",
}: {
  className?: string;
  variant?: TurnComposerVariant;
}) {
  return (
    <div className={className ?? "px-4 pb-4 pt-2"}>
      <TurnComposer variant={variant} />
    </div>
  );
}
