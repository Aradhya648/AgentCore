import { Input, Textarea } from "@/components/ui";
import type {
  WorkflowDefNode,
  WorkflowDefinition,
} from "@/services/workflowDefinition";

export function WorkflowNodeInspector({
  definition,
  selectedId,
  onChange,
}: {
  definition: WorkflowDefinition;
  selectedId: string | null;
  onChange: (next: WorkflowDefinition) => void;
}) {
  const node = definition.nodes.find((n) => n.id === selectedId) ?? null;

  if (!node) {
    return (
      <div className="flex h-full flex-col justify-center px-4 text-sm text-muted-foreground">
        选中画布上的节点以编辑属性。
      </div>
    );
  }

  const patch = (next: WorkflowDefNode) => {
    onChange({
      ...definition,
      nodes: definition.nodes.map((n) => (n.id === next.id ? next : n)),
    });
  };

  if (node.kind === "human_gate") {
    return (
      <div className="space-y-4 p-4">
        <div>
          <p className="text-sm font-medium text-foreground">等人关卡</p>
          <p className="mt-1 text-xs text-muted-foreground">
            前驱步骤完成后暂停，等人确认再继续。
          </p>
        </div>
        <label className="block" htmlFor="wf-gate-label">
          <span className="mb-1 block text-xs text-muted-foreground">标签</span>
          <Input
            id="wf-gate-label"
            className="w-full"
            value={node.label}
            maxLength={80}
            placeholder="例如：审初稿"
            onChange={(e) => patch({ ...node, label: e.target.value })}
          />
        </label>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      <div>
        <p className="text-sm font-medium text-foreground">队员步骤</p>
        <p className="mt-1 text-xs text-muted-foreground">
          展开为一条委派任务；依赖由连线决定。
        </p>
      </div>
      <label className="block" htmlFor="wf-role">
        <span className="mb-1 block text-xs text-muted-foreground">角色</span>
        <Input
          id="wf-role"
          className="w-full"
          value={node.role}
          maxLength={80}
          placeholder="例如：调研员"
          onChange={(e) => patch({ ...node, role: e.target.value })}
        />
      </label>
      <label className="block" htmlFor="wf-task">
        <span className="mb-1 block text-xs text-muted-foreground">
          任务说明
        </span>
        <Textarea
          id="wf-task"
          className="w-full text-sm"
          rows={5}
          value={node.task}
          maxLength={2000}
          placeholder="这步要完成什么？"
          onChange={(e) => patch({ ...node, task: e.target.value })}
        />
      </label>
      <label className="block" htmlFor="wf-deliverable">
        <span className="mb-1 block text-xs text-muted-foreground">
          交付形式（可选）
        </span>
        <Input
          id="wf-deliverable"
          className="w-full"
          value={node.deliverable?.form ?? ""}
          maxLength={120}
          placeholder="例如：简报 Markdown"
          onChange={(e) =>
            patch({
              ...node,
              deliverable: e.target.value.trim()
                ? { form: e.target.value }
                : undefined,
            })
          }
        />
      </label>
    </div>
  );
}
