import { Button } from "@/components/ui";

export function DraftWorkspaceAssignPrompt({
  attachmentProjectName,
  currentProjectName,
  onAssign,
  onKeep,
}: {
  attachmentProjectName: string;
  /** When set, user already picked a different project for this draft. */
  currentProjectName?: string | null;
  onAssign: () => void;
  onKeep: () => void;
}) {
  const message = currentProjectName
    ? `附件来自「${attachmentProjectName}」，当前将在「${currentProjectName}」工作。改为在附件所在项目？`
    : `附件来自「${attachmentProjectName}」，是否在该项目中开始本对话？`;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/40 px-3 py-2">
      <p className="min-w-0 flex-1 text-xs text-foreground">{message}</p>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button variant="neutral" size="sm" onClick={onKeep}>
          {currentProjectName ? "保持现状" : "先聊到再说"}
        </Button>
        <Button variant="primary" size="sm" onClick={onAssign}>
          改用该项目
        </Button>
      </div>
    </div>
  );
}
