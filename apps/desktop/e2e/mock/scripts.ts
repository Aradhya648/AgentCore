/**
 * Vector scripts for e2e mock.
 *
 * §八 切段落点：运行期按事件类型识别边界（不用导出期标注）。
 * - hot（approval）：在 `*_required` 后暂停同流，等 POST interactions 再续推后续段
 * - cold（team_preview）：首段用带 `message_end(paused)` 的 finalized 向量；
 *   resume 段从 `*_resolved_continue` 的 `*_resolved` 起推（事件仍全部来自真实向量）
 */
import {
  type ConformanceEvent,
  type ConformanceFixture,
  loadFixture,
} from "./fixtures.ts";

export type ScriptKind = "complete" | "hot_gate" | "cold_gate";

export interface ScriptPlan {
  name: string;
  kind: ScriptKind;
  /** Events to push on POST .../messages (and hold open if hot_gate). */
  initial: ConformanceEvent[];
  /** Events to push after POST .../interactions (hot only). */
  continueSameStream: ConformanceEvent[];
  /** Events to push on POST .../resume (cold only). */
  resumeStream: ConformanceEvent[];
}

const HOT_REQUIRED = new Set([
  "approval_required",
  "client_tool_required",
  "escalation_required",
  "delegation_authorization_required",
]);

const COLD_REQUIRED = new Set([
  "team_preview_required",
  "plan_review_required",
  "checkpoint_required",
  "ask_user_required",
]);

function indexOfType(events: ConformanceEvent[], type: string): number {
  return events.findIndex((e) => e.type === type);
}

function splitHot(fixture: ConformanceFixture): ScriptPlan {
  const idx = fixture.events.findIndex((e) => HOT_REQUIRED.has(e.type));
  if (idx < 0) {
    throw new Error(
      `Script ${fixture.name}: expected a hot *_required boundary`,
    );
  }
  return {
    name: fixture.name,
    kind: "hot_gate",
    initial: fixture.events.slice(0, idx + 1),
    continueSameStream: fixture.events.slice(idx + 1),
    resumeStream: [],
  };
}

/**
 * Cold gate: pin finalized (paused close) for the first SSE, and the
 * resolved_continue vector's post-gate tail for POST resume.
 */
function splitColdTeamPreview(): ScriptPlan {
  const finalized = loadFixture("team_preview_finalized");
  const cont = loadFixture("team_preview_resolved_continue");
  const resolvedIdx = indexOfType(cont.events, "team_preview_resolved");
  if (resolvedIdx < 0) {
    throw new Error(
      "team_preview_resolved_continue missing team_preview_resolved",
    );
  }
  const requiredIdx = indexOfType(finalized.events, "team_preview_required");
  if (requiredIdx < 0) {
    throw new Error("team_preview_finalized missing team_preview_required");
  }
  return {
    name: "team_preview_resolved_continue",
    kind: "cold_gate",
    initial: finalized.events,
    continueSameStream: [],
    resumeStream: cont.events.slice(resolvedIdx),
  };
}

function complete(name: string): ScriptPlan {
  const fixture = loadFixture(name);
  return {
    name,
    kind: "complete",
    initial: fixture.events,
    continueSameStream: [],
    resumeStream: [],
  };
}

const PLANS: Record<string, () => ScriptPlan> = {
  single_agent_text: () => complete("single_agent_text"),
  multi_agent_delegate: () => complete("multi_agent_delegate"),
  approval_resolved_continue: () =>
    splitHot(loadFixture("approval_resolved_continue")),
  team_preview_resolved_continue: () => splitColdTeamPreview(),
};

/** Parse `__e2e_script__:<name>` from the user message; default single_agent_text. */
export function resolveScriptName(content: string): string {
  const m = /__e2e_script__:([a-z0-9_]+)/i.exec(content);
  const name = m?.[1] ?? "single_agent_text";
  if (!(name in PLANS)) {
    throw new Error(
      `Unknown e2e script "${name}". Known: ${Object.keys(PLANS).join(", ")}`,
    );
  }
  return name;
}

export function buildPlan(scriptName: string): ScriptPlan {
  const factory = PLANS[scriptName];
  if (!factory) throw new Error(`Unknown script ${scriptName}`);
  return factory();
}

/** Sanity: cold/hot scripts must have a gate event in the initial segment. */
export function assertPlanHasBoundary(plan: ScriptPlan): void {
  if (plan.kind === "complete") return;
  const types = new Set(plan.initial.map((e) => e.type));
  const ok =
    plan.kind === "hot_gate"
      ? [...HOT_REQUIRED].some((t) => types.has(t))
      : [...COLD_REQUIRED].some((t) => types.has(t));
  if (!ok) {
    throw new Error(`Script ${plan.name} initial segment missing gate event`);
  }
}
