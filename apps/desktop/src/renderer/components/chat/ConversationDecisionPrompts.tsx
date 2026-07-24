/**
 * Conversation-level decision prompts shared by chat and canvas 指挥台.
 * Unified DecisionCard shell; mounts above the composer in ChatView and in
 * CanvasDecisionPanel — mutually exclusive (canvasMode toggle), one live instance.
 */
import { ApprovalPrompt } from "./ApprovalPrompt";
import { DelegationAuthorizationPrompt } from "./DelegationAuthorizationCard";
import { ResumePrompt } from "./ResumePrompt";
import { RunConfirmPrompt } from "./RunConfirmPrompt";

export function ConversationDecisionPrompts() {
  return (
    <>
      <ResumePrompt />
      <DelegationAuthorizationPrompt />
      <ApprovalPrompt />
      <RunConfirmPrompt />
    </>
  );
}
