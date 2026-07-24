/**
 * Workspace mode control for the open conversation (双模式工作区 §七/§八).
 * Logic + popover live in {@link WorkspaceModeControl}; this file keeps the
 * dock-panel mount site stable.
 */
import { WorkspaceModeControl } from "./WorkspaceModeControl";

export function WorkspaceModeBar({
  conversationId,
}: {
  conversationId: string;
}) {
  return <WorkspaceModeControl conversationId={conversationId} />;
}
