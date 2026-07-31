/**
 * Definition-state workflow canvas (队员步骤 / 等人关卡 + 连线).
 * Uses @xyflow/react already in the desktop app — does NOT touch projectExecution.
 */

import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  type WorkflowDefNode,
  type WorkflowDefinition,
  createAgentStepNode,
  createHumanGateNode,
} from "@/services/workflowDefinition";
import {
  Background,
  type Connection,
  type Edge,
  MarkerType,
  type Node,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import { Hand, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import {
  type WorkflowCanvasNodeData,
  workflowNodeTypes,
} from "./workflowNodes";

const NODE_W = 200;
const NODE_H = 72;
const COL_GAP = 80;
const ROW_GAP = 28;

function layoutPositions(count: number): Array<{ x: number; y: number }> {
  const cols = Math.max(1, Math.ceil(Math.sqrt(count)));
  return Array.from({ length: count }, (_, i) => ({
    x: (i % cols) * (NODE_W + COL_GAP) + 40,
    y: Math.floor(i / cols) * (NODE_H + ROW_GAP) + 40,
  }));
}

function nodeTitle(n: WorkflowDefNode): string {
  if (n.kind === "human_gate") return n.label.trim() || "等人关卡";
  return n.role.trim() || "队员步骤";
}

function nodeSubtitle(n: WorkflowDefNode): string | undefined {
  if (n.kind === "agent_step") {
    const t = n.task.trim();
    return t || undefined;
  }
  return undefined;
}

function defToFlow(def: WorkflowDefinition): {
  nodes: Node<WorkflowCanvasNodeData>[];
  edges: Edge[];
} {
  const positions = layoutPositions(def.nodes.length);
  const nodes: Node<WorkflowCanvasNodeData>[] = def.nodes.map((n, i) => ({
    id: n.id,
    type: "workflowNode",
    position: positions[i] ?? { x: 40, y: 40 },
    data: {
      kind: n.kind,
      title: nodeTitle(n),
      subtitle: nodeSubtitle(n),
    },
  }));
  const edges: Edge[] = def.edges.map((e, i) => ({
    id: `e_${e.from}_${e.to}_${i}`,
    source: e.from,
    target: e.to,
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
  }));
  return { nodes, edges };
}

function flowToDef(
  nodes: Node<WorkflowCanvasNodeData>[],
  edges: Edge[],
  defs: Map<string, WorkflowDefNode>,
): WorkflowDefinition {
  const outNodes: WorkflowDefNode[] = nodes.map((n) => {
    const prev = defs.get(n.id);
    if (prev) return prev;
    if (n.data.kind === "human_gate") {
      return createHumanGateNode({ id: n.id, label: n.data.title });
    }
    return createAgentStepNode({
      id: n.id,
      role: n.data.title,
      task: n.data.subtitle ?? "",
    });
  });
  const outEdges = edges
    .filter((e) => e.source && e.target)
    .map((e) => ({ from: e.source, to: e.target }));
  return { nodes: outNodes, edges: outEdges };
}

function WorkflowCanvasInner({
  definition,
  selectedId,
  onChange,
  onSelect,
  className,
}: {
  definition: WorkflowDefinition;
  selectedId: string | null;
  onChange: (next: WorkflowDefinition) => void;
  onSelect: (id: string | null) => void;
  className?: string;
}) {
  const defMap = useMemo(() => {
    const m = new Map<string, WorkflowDefNode>();
    for (const n of definition.nodes) m.set(n.id, n);
    return m;
  }, [definition.nodes]);

  const initial = useMemo(() => defToFlow(definition), [definition]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  // Re-hydrate when parent definition identity changes (load / reset / inspector),
  // preserving drag positions for nodes that still exist.
  useEffect(() => {
    const next = defToFlow(definition);
    setNodes((prev) => {
      const pos = new Map(prev.map((n) => [n.id, n.position]));
      return next.nodes.map((n) => ({
        ...n,
        position: pos.get(n.id) ?? n.position,
      }));
    });
    setEdges(next.edges);
  }, [definition, setEdges, setNodes]);

  useEffect(() => {
    setNodes((prev) =>
      prev.map((n) => ({ ...n, selected: n.id === selectedId })),
    );
  }, [selectedId, setNodes]);

  const emit = useCallback(
    (
      nextNodes: Node<WorkflowCanvasNodeData>[],
      nextEdges: Edge[],
      map: Map<string, WorkflowDefNode>,
    ) => {
      onChange(flowToDef(nextNodes, nextEdges, map));
    },
    [onChange],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => {
        const next = addEdge(
          {
            ...connection,
            markerEnd: {
              type: MarkerType.ArrowClosed,
              width: 16,
              height: 16,
            },
          },
          eds,
        );
        setNodes((nds) => {
          emit(nds, next, defMap);
          return nds;
        });
        return next;
      });
    },
    [defMap, emit, setEdges, setNodes],
  );

  const addNode = (kind: "agent_step" | "human_gate") => {
    const defNode =
      kind === "human_gate" ? createHumanGateNode() : createAgentStepNode();
    const pos = {
      x: 40 + nodes.length * 24,
      y: 40 + nodes.length * 24,
    };
    const flowNode: Node<WorkflowCanvasNodeData> = {
      id: defNode.id,
      type: "workflowNode",
      position: pos,
      data: {
        kind,
        title: nodeTitle(defNode),
        subtitle: nodeSubtitle(defNode),
      },
    };
    const nextDefs = new Map(defMap);
    nextDefs.set(defNode.id, defNode);
    const nextNodes = [...nodes, flowNode];
    setNodes(nextNodes);
    emit(nextNodes, edges, nextDefs);
    onSelect(defNode.id);
  };

  const onNodesDelete = useCallback(
    (deleted: Node[]) => {
      const ids = new Set(deleted.map((n) => n.id));
      const nextNodes = nodes.filter((n) => !ids.has(n.id));
      const nextEdges = edges.filter(
        (e) => !ids.has(e.source) && !ids.has(e.target),
      );
      setNodes(nextNodes);
      setEdges(nextEdges);
      const nextDefs = new Map(defMap);
      for (const id of ids) nextDefs.delete(id);
      emit(nextNodes, nextEdges, nextDefs);
      if (selectedId && ids.has(selectedId)) onSelect(null);
    },
    [defMap, edges, emit, nodes, onSelect, selectedId, setEdges, setNodes],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      const ids = new Set(deleted.map((e) => e.id));
      const nextEdges = edges.filter((e) => !ids.has(e.id));
      setEdges(nextEdges);
      emit(nodes, nextEdges, defMap);
    },
    [defMap, edges, emit, nodes, setEdges],
  );

  return (
    <div className={cn("flex h-full min-h-[420px] flex-col", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <Button
          variant="neutral"
          size="sm"
          icon={<UserRound size={14} />}
          onClick={() => addNode("agent_step")}
        >
          队员步骤
        </Button>
        <Button
          variant="neutral"
          size="sm"
          icon={<Hand size={14} />}
          onClick={() => addNode("human_gate")}
        >
          等人关卡
        </Button>
        <p className="ml-auto text-xs text-muted-foreground">
          拖拽连线建立依赖；选中后右侧可编辑
        </p>
      </div>
      <div className="min-h-0 flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={workflowNodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodesDelete={onNodesDelete}
          onEdgesDelete={onEdgesDelete}
          onSelectionChange={({ nodes: sel }) => {
            onSelect(sel[0]?.id ?? null);
          }}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          deleteKeyCode={["Backspace", "Delete"]}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} />
        </ReactFlow>
      </div>
    </div>
  );
}

export function WorkflowCanvas(props: {
  definition: WorkflowDefinition;
  selectedId: string | null;
  onChange: (next: WorkflowDefinition) => void;
  onSelect: (id: string | null) => void;
  className?: string;
}) {
  return (
    <ReactFlowProvider>
      <WorkflowCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
