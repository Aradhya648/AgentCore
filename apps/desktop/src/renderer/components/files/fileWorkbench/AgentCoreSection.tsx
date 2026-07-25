import { BrandMarkIcon } from "@/components/brand/BrandMark";
import {
  type MemoryScope,
  MemorySection,
} from "@/components/files/fileWorkbench/MemorySection";
import {
  type RuleScope,
  RuleSection,
} from "@/components/files/fileWorkbench/RuleSection";
import {
  loadAgentCoreCollapsed,
  loadAgentCoreExpanded,
  saveAgentCoreCollapsed,
  saveAgentCoreExpanded,
} from "@/components/files/fileWorkbench/storage";
import { cn } from "@/lib/utils";
import { AGENTCORE_ROOT_NAME } from "@/services/documents";
import { ChevronDown, ChevronRight, Folder, FolderOpen } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** Which convention-tree layer: GLOBAL (cloud root) or one project's. */
export type AgentCoreScope =
  | { kind: "global" }
  | { kind: "project"; folderId: string; projectName: string };

/**
 * Unified `AgentCore/{规则,记忆}/` rail section (Agent记忆与知识系统 §5.0 / §1.6).
 * Replaces the dual pinned「AI 记忆 / 你的规则」rails and per-project twin nodes.
 * Leaves still open via the memory / document sources (CAS unchanged).
 */
export function AgentCoreSection({
  scope,
  memoryActivePath,
  rulesActivePath,
  onOpenMemory,
  onOpenRule,
  onMemoryTopicDeleted,
  onRuleDeleted,
  onRuleRenamed,
  onOpenUpdates,
  indent = 0,
  forceOpen = false,
  forceOpenMemory = false,
  forceOpenMemoryTopics = false,
  onRevealApplied,
}: {
  scope: AgentCoreScope;
  memoryActivePath: string | null;
  rulesActivePath: string | null;
  onOpenMemory: (path: string, name: string) => void;
  onOpenRule: (path: string, name: string) => void;
  onMemoryTopicDeleted: (path: string) => void;
  onRuleDeleted: (path: string) => void;
  onRuleRenamed: (path: string, name: string) => void;
  /** GLOBAL-only「最近更新」feed opener. */
  onOpenUpdates?: () => void;
  indent?: number;
  /** Deep-link: expand AgentCore (and optionally memory / topics). */
  forceOpen?: boolean;
  forceOpenMemory?: boolean;
  forceOpenMemoryTopics?: boolean;
  onRevealApplied?: () => void;
}) {
  const foldKey = scope.kind === "global" ? "global" : scope.folderId;
  const [sectionOpen, setSectionOpen] = useState(() =>
    scope.kind === "global"
      ? !loadAgentCoreCollapsed().has(foldKey)
      : loadAgentCoreExpanded().has(foldKey),
  );
  const revealAppliedRef = useRef(false);

  useEffect(() => {
    if (!forceOpen && !forceOpenMemory && !forceOpenMemoryTopics) {
      revealAppliedRef.current = false;
      return;
    }
    if (revealAppliedRef.current) return;
    revealAppliedRef.current = true;

    if (forceOpen || forceOpenMemory || forceOpenMemoryTopics) {
      setSectionOpen((open) => {
        if (open) return open;
        if (scope.kind === "global") {
          const set = loadAgentCoreCollapsed();
          set.delete(foldKey);
          saveAgentCoreCollapsed(set);
        } else {
          const set = loadAgentCoreExpanded();
          set.add(foldKey);
          saveAgentCoreExpanded(set);
        }
        return true;
      });
    }
    // MemorySection owns onRevealApplied when memory/topics are forced; only clear
    // here when the reveal is AgentCore-only.
    if (!forceOpenMemory && !forceOpenMemoryTopics) {
      onRevealApplied?.();
    }
  }, [
    forceOpen,
    forceOpenMemory,
    forceOpenMemoryTopics,
    scope.kind,
    foldKey,
    onRevealApplied,
  ]);

  const toggleSection = () =>
    setSectionOpen((open) => {
      const next = !open;
      if (scope.kind === "global") {
        const set = loadAgentCoreCollapsed();
        if (next) set.delete(foldKey);
        else set.add(foldKey);
        saveAgentCoreCollapsed(set);
      } else {
        const set = loadAgentCoreExpanded();
        if (next) set.add(foldKey);
        else set.delete(foldKey);
        saveAgentCoreExpanded(set);
      }
      return next;
    });

  const memoryScope: MemoryScope =
    scope.kind === "global"
      ? { kind: "global" }
      : {
          kind: "project",
          folderId: scope.folderId,
          projectName: scope.projectName,
        };
  const ruleScope: RuleScope =
    scope.kind === "global"
      ? { kind: "global" }
      : { kind: "project", folderId: scope.folderId };

  const headerPad = indent + 8;
  const childIndent = indent + 14;

  return (
    <div>
      <button
        type="button"
        onClick={toggleSection}
        aria-expanded={sectionOpen}
        style={{ paddingLeft: headerPad }}
        className={cn(
          "flex h-7 w-full items-center gap-1.5 rounded-lg pr-2 text-left text-sm text-foreground transition-colors hover:bg-accent/60",
          scope.kind === "global" && "font-medium",
        )}
      >
        {sectionOpen ? (
          <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-muted-foreground" />
        )}
        {scope.kind === "global" ? (
          <BrandMarkIcon size={14} />
        ) : sectionOpen ? (
          <FolderOpen size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <Folder size={14} className="shrink-0 text-muted-foreground" />
        )}
        <span className="min-w-0 flex-1 truncate">{AGENTCORE_ROOT_NAME}</span>
      </button>

      {sectionOpen && (
        <>
          <RuleSection
            scope={ruleScope}
            activePath={rulesActivePath}
            onOpen={onOpenRule}
            onDeleted={onRuleDeleted}
            onRenamed={onRuleRenamed}
            indent={childIndent}
          />
          <MemorySection
            scope={memoryScope}
            activePath={memoryActivePath}
            onOpen={onOpenMemory}
            onTopicDeleted={onMemoryTopicDeleted}
            onOpenUpdates={onOpenUpdates}
            indent={childIndent}
            forceOpen={forceOpenMemory}
            forceOpenTopics={forceOpenMemoryTopics}
            onRevealApplied={onRevealApplied}
          />
        </>
      )}
    </div>
  );
}
