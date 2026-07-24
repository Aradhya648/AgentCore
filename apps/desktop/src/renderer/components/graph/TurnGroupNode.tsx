import { TeamNotesPanel } from "@/components/chat/TeamNotesPanel";
import { teamNotesDefaultExpanded } from "@/components/chat/teamNotesDefaults";
import { IconButton } from "@/components/ui";
import type { ExecutionStatus, TeamNote } from "@/stores/execution";
import { Handle, type NodeProps, Position } from "@xyflow/react";
import { AlertTriangle, Maximize2, Minimize2 } from "lucide-react";

/**
 * Compound parent for an expanded team turn on the single-layer conversation
 * canvas. Children (AgentNode / EndpointNode / SubTeamGroupNode) nest via
 * `parentId` + `extent: "parent"` — no nested ReactFlow.
 *
 * Hit-testing: the body uses `pointer-events: none` so hover/click pass through
 * to nested DAG children. Only the header chrome (+ optional team-notes footer)
 * is interactive.
 */
export interface TurnGroupData {
  messageId: string;
  taskSummary: string;
  pendingDecisions: number;
  recoverable: boolean;
  onMaximize: () => void;
  /** Fold this turn back to TurnSummaryNode (LRU window). */
  onCollapse?: () => void;
  /** When true, chrome is muted (放大态 dims non-focus turns; this group stays bright). */
  dimmed?: boolean;
  /** Turn-level note wall (`Execution.teamNotes`); empty → no footer. */
  teamNotes?: TeamNote[];
  status?: ExecutionStatus;
  [key: string]: unknown;
}

const HEADER_H = 38;
/** Reserved footer when the turn has notes (chip + scrollable list; no spine jump). */
export const TURN_GROUP_NOTES_FOOTER_H = 148;

export function TurnGroupNode({ data }: NodeProps) {
  const d = data as TurnGroupData;
  const notes = d.teamNotes ?? [];
  const hasNotes = notes.length > 0;
  return (
    <>
      <Handle
        type="target"
        position={Position.Top}
        className="!pointer-events-none !bg-border"
      />
      <div
        className={`pointer-events-none flex h-full w-full flex-col overflow-hidden rounded-xl border-2 bg-card shadow-md ${
          d.dimmed ? "border-border opacity-40" : "border-primary"
        }`}
      >
        <div
          className="pointer-events-auto flex shrink-0 items-center gap-2 border-b border-border px-3"
          style={{ height: HEADER_H }}
          onDoubleClick={(e) => e.stopPropagation()}
        >
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
            {d.taskSummary || "团队回合"}
          </span>
          {d.pendingDecisions > 0 && (
            <span className="flex shrink-0 items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              <AlertTriangle size={12} />
              待你拍板
              {d.pendingDecisions > 1 ? ` ${d.pendingDecisions}` : ""}
            </span>
          )}
          {d.recoverable && d.pendingDecisions === 0 && (
            <span className="flex shrink-0 items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
              <AlertTriangle size={12} />
              待救火
            </span>
          )}
          {d.onCollapse && (
            <IconButton
              onClick={(e) => {
                e.stopPropagation();
                d.onCollapse?.();
              }}
              aria-label="折叠回合"
              title="折叠回合"
            >
              <Minimize2 size={15} />
            </IconButton>
          )}
          <IconButton
            onClick={(e) => {
              e.stopPropagation();
              d.onMaximize();
            }}
            aria-label="放大查看"
            title="放大查看"
          >
            <Maximize2 size={15} />
          </IconButton>
        </div>
        <div className="min-h-0 flex-1" aria-hidden />
        {hasNotes && (
          <div
            className="pointer-events-auto shrink-0 bg-card"
            style={{ maxHeight: TURN_GROUP_NOTES_FOOTER_H }}
            onDoubleClick={(e) => e.stopPropagation()}
          >
            <TeamNotesPanel
              notes={notes}
              compact
              disclosureKey={`${d.messageId}:team-notes`}
              live={teamNotesDefaultExpanded(d.status, notes)}
            />
          </div>
        )}
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!pointer-events-none !bg-border"
      />
    </>
  );
}

export const TURN_GROUP_HEADER_H = HEADER_H;
/** Padding inside the compound around the ELK DAG bbox. */
export const TURN_GROUP_PAD = 16;
