import { ApprovalCard } from "@/components/chat/ApprovalPrompt";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ApprovalView } from "@/stores/interactions";

const DEMO_APPROVAL: ApprovalView = {
  approvalId: "manual-demo-approval",
  conversationId: "manual-demo",
  toolCallId: "manual-demo-tc",
  toolName: "file_write",
  arguments: {
    path: "reports/week-summary.md",
    content: "# 周报摘要\n\n本周成本下降 12%，异常点已标注。\n",
  },
  resolving: false,
};

/**
 * 手册「真组件预览」：工具审批卡。
 * 复用 {@link ApprovalCard} + 手写静态 ApprovalView；按钮为空操作（不打 API）。
 */
export function ManualApprovalCardPreview() {
  return (
    <TooltipProvider>
      <div className="w-full max-w-3xl">
        <ApprovalCard approval={DEMO_APPROVAL} onDecide={() => {}} />
      </div>
    </TooltipProvider>
  );
}
