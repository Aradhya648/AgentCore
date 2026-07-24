import type { ContextBlockWire } from "@/types/events";

/** Inputs needed to pick the run-detail 「任务」header (continuation rounds prefer wire blocks). */
export interface RunTaskSectionInput {
  continuesRunId: string | null;
  task: string;
  receivedContext: ReadonlyArray<
    Pick<ContextBlockWire, "channel" | "body" | "heading">
  >;
}

/** What the run-detail top 「任务」Section should show. */
export interface RunTaskSection {
  /** Section title — task-block heading, 「本轮焦点」, or 「任务」. */
  title: string;
  /** Verbatim body shown under the title. */
  body: string;
  /**
   * True when a `channel="task"` block was promoted to the header — the
   * 「收到的上下文」list must drop that block so it is not shown twice.
   */
  promotedTask: boolean;
}

/**
 * Pick the top task section for a run detail panel.
 *
 * Continuation runs (`continuesRunId != null`): prefer the wire `task` block (this
 * beat's real instruction), then `round_focus` (legacy), then `run.task`.
 * Cold-start runs keep showing `run.task` as 「任务」, but still promote+filter a
 * wire `task` block so 「收到的上下文」does not repeat the same instruction.
 */
export function selectRunTaskSection(run: RunTaskSectionInput): RunTaskSection {
  const taskBlock = run.receivedContext.find((b) => b.channel === "task");

  if (run.continuesRunId == null) {
    return {
      title: "任务",
      body: run.task,
      promotedTask: taskBlock != null,
    };
  }

  if (taskBlock) {
    const heading = taskBlock.heading.trim();
    return {
      title: heading || "任务",
      body: taskBlock.body,
      promotedTask: true,
    };
  }

  const roundFocus = run.receivedContext.find(
    (b) => b.channel === "round_focus",
  );
  if (roundFocus) {
    return {
      title: "本轮焦点",
      body: roundFocus.body,
      promotedTask: false,
    };
  }

  return { title: "任务", body: run.task, promotedTask: false };
}

/**
 * Blocks for 「收到的上下文」after promoting a task block to the header.
 * Drops every `channel="task"` block when one was promoted; otherwise returns
 * the input unchanged.
 */
export function receivedContextForList<T extends { channel: string }>(
  blocks: readonly T[],
  promotedTask: boolean,
): T[] {
  if (!promotedTask) return [...blocks];
  return blocks.filter((b) => b.channel !== "task");
}
