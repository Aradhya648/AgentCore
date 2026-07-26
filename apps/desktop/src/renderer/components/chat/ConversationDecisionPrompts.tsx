/**
 * Conversation-level decision prompts shared by chat and canvas 指挥台.
 * Unified DecisionCard shell; mounts above the composer in ChatView and in
 * CanvasDecisionPanel — mutually exclusive (canvasMode toggle), one live instance.
 *
 * Chat may omit ApprovalPrompt here and remount it flush above MessageInput
 * (composer 一体态); canvas keeps the default stack in CommandRegion.
 */
import { ApprovalPrompt } from "./ApprovalPrompt";
import { DelegationAuthorizationPrompt } from "./DelegationAuthorizationCard";
import { ResumePrompt } from "./ResumePrompt";
import { RunConfirmPrompt } from "./RunConfirmPrompt";

export function ConversationDecisionPrompts({
  omitApproval = false,
}: {
  /**
   * When true, skip {@link ApprovalPrompt} here — ChatView mounts it flush above
   * MessageInput for composer-一体态 (仍同一组件 / 同一 interactions 热路).
   */
  omitApproval?: boolean;
}) {
  return (
    <>
      <ResumePrompt />
      <DelegationAuthorizationPrompt />
      {!omitApproval && <ApprovalPrompt />}
      <RunConfirmPrompt />
    </>
  );
}
