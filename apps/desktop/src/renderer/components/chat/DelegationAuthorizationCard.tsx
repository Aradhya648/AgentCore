import {
  OrphanedInteractionCard,
  WaitingForDecisionHint,
} from "@/components/chat/OrphanedInteractionCard";
import { Badge, Button, DecisionCard, DecisionCardIcon } from "@/components/ui";
import { notifyError } from "@/lib/toast";
import { decideDelegationAuthorization } from "@/services/delegationAuth";
import { useConversationStore } from "@/stores/conversation";
import {
  type DelegationAuthView,
  useOrphanedDelegations,
  usePendingDelegations,
} from "@/stores/interactions";
import type { DelegationAuthorizationDecision } from "@/types/events";
import { CheckCheck, ListChecks, Loader2, ShieldAlert, X } from "lucide-react";
import { useState } from "react";

const TOOL_LABELS: Record<string, string> = {
  file_write: "写入文件",
  file_append: "追加文件",
  str_replace: "修改文件",
  file_delete: "删除文件",
  file_move: "移动文件",
  file_copy: "复制文件",
  mkdir: "创建目录",
  file_batch: "批量文件操作",
  code_execute: "执行代码",
  test_run: "运行测试",
  desktop_notify: "系统通知",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

export function DelegationAuthorizationPrompt() {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const pending = usePendingDelegations(conversationId);
  const orphaned = useOrphanedDelegations(conversationId);
  if (pending.length === 0 && orphaned.length === 0) return null;

  return (
    <div className="mx-4 mb-2 space-y-2">
      {orphaned.map((o) => (
        <OrphanedInteractionCard
          key={o.id}
          title="团队授权已失效"
          detail="该委派授权请求已不可答复（服务已重启或回合已结束）。"
        />
      ))}
      {pending.map((authorization) => (
        <DelegationAuthorizationCard
          key={authorization.authorizationId}
          authorization={authorization}
        />
      ))}
    </div>
  );
}

function DelegationAuthorizationCard({
  authorization,
}: {
  authorization: DelegationAuthView;
}) {
  const [clicked, setClicked] =
    useState<DelegationAuthorizationDecision | null>(null);
  const busy = authorization.resolving;

  const onDecide = (decision: DelegationAuthorizationDecision) => {
    setClicked(decision);
    void decideDelegationAuthorization(authorization, decision).catch((err) => {
      notifyError(err, "操作失败");
      setClicked(null);
    });
  };

  const spinnerOr = (
    decision: DelegationAuthorizationDecision,
    icon: React.ReactNode,
  ) =>
    busy && clicked === decision ? (
      <Loader2 size={13} className="animate-spin" />
    ) : (
      icon
    );

  return (
    <DecisionCard tone="primary" animate className="mx-0">
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="primary">
          <ShieldAlert size={16} />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-foreground">团队授权</p>
          <WaitingForDecisionHint />
          <p className="mt-0.5 text-xs text-muted-foreground">
            委派团队将可能使用中风险工具，请选择授权方式
          </p>

          {authorization.workers.length > 0 && (
            <div className="mt-2 space-y-1">
              <p className="text-xs font-medium text-foreground">团队成员</p>
              <ul className="space-y-1">
                {authorization.workers.map((worker) => (
                  <li
                    key={`${worker.role}-${worker.task}`}
                    className="rounded-lg bg-card/70 px-2 py-1.5 text-xs"
                  >
                    <span className="font-medium text-foreground">
                      {worker.role}
                    </span>
                    <span className="text-muted-foreground"> · </span>
                    <span className="text-muted-foreground">{worker.task}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {authorization.tools.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-medium text-foreground">中风险工具</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {authorization.tools.map((tool) => (
                  <Badge key={tool} tone="muted" className="font-normal">
                    {toolLabel(tool)}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pl-6">
        <Button
          variant="primary"
          icon={spinnerOr("grant_delegation", <CheckCheck size={13} />)}
          disabled={busy}
          onClick={() => onDecide("grant_delegation")}
        >
          一次性授权
        </Button>
        <Button
          variant="neutral"
          icon={spinnerOr("per_call", <ListChecks size={13} />)}
          disabled={busy}
          onClick={() => onDecide("per_call")}
        >
          逐个审批
        </Button>
        <Button
          variant="danger"
          icon={spinnerOr("deny", <X size={13} />)}
          disabled={busy}
          onClick={() => onDecide("deny")}
        >
          拒绝
        </Button>
      </div>
    </DecisionCard>
  );
}
