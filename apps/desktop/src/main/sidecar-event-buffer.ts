/**
 * Per-turn event buffer for local-engine refresh recovery.
 *
 * Mirrors Python `EventSink._record_history` coalesce / skip / cap rules
 * (`runtime/events/sink.py`, `journal_config.py`), with one intentional
 * deviation: `message_end` / `error` are **kept** (and seal the buffer) so an
 * attach that lands in the settle micro-window still ends the bubble.
 */

export interface BufferedSidecarEvent {
  type: string;
  timestamp: string;
  payload: unknown;
}

/** Skip set = `_HISTORY_SKIP_TYPES` minus `message_end` / `error` (D2 deviation). */
const HISTORY_SKIP_TYPES = new Set([
  "tool_progress",
  "tool_use_progress",
  "run_tool_progress",
  "workspace_op_required",
  "handoff_snapshot_done",
  "handoff_job_started",
  "handoff_apply_done",
]);

const COALESCE_TURN = new Set(["content_delta", "reasoning_delta"]);
const COALESCE_RUN = new Set(["run_output_delta", "run_reasoning_delta"]);

const PROCESS_RESULT_CAP = 8000;

function capProcessResult(result: unknown): unknown {
  if (typeof result === "string" && result.length > PROCESS_RESULT_CAP) {
    return `${result.slice(0, PROCESS_RESULT_CAP)}…`;
  }
  return result;
}

function isTerminalType(type: string): boolean {
  return type === "message_end" || type === "error";
}

function clonePayload(payload: unknown): unknown {
  if (payload == null || typeof payload !== "object") return payload;
  return { ...(payload as Record<string, unknown>) };
}

/**
 * Ordered event buffer for one live sidecar turn. All methods are synchronous
 * so attach's rebind→snapshot section can stay zero-await.
 */
export class SidecarEventBuffer {
  private readonly events: BufferedSidecarEvent[] = [];
  private sealed = false;

  record(event: BufferedSidecarEvent): void {
    const type = String(event.type ?? "");
    if (!type) return;

    if (isTerminalType(type)) {
      this.events.push({
        type,
        timestamp: event.timestamp,
        payload: clonePayload(event.payload),
      });
      this.sealed = true;
      return;
    }

    if (this.sealed) return;
    if (HISTORY_SKIP_TYPES.has(type)) return;

    if (COALESCE_TURN.has(type)) {
      const payload =
        event.payload && typeof event.payload === "object"
          ? (event.payload as Record<string, unknown>)
          : {};
      const delta = String(payload.delta ?? "");
      if (!delta) return;
      const last = this.events[this.events.length - 1];
      if (last && last.type === type) {
        const lastPayload =
          last.payload && typeof last.payload === "object"
            ? (last.payload as Record<string, unknown>)
            : {};
        last.payload = {
          delta: String(lastPayload.delta ?? "") + delta,
        };
        return;
      }
      this.events.push({
        type,
        timestamp: event.timestamp,
        payload: { delta },
      });
      return;
    }

    if (COALESCE_RUN.has(type)) {
      const payload =
        event.payload && typeof event.payload === "object"
          ? (event.payload as Record<string, unknown>)
          : {};
      const delta = String(payload.delta ?? "");
      if (!delta) return;
      const runId = payload.run_id;
      const last = this.events[this.events.length - 1];
      const lastPayload =
        last?.payload && typeof last.payload === "object"
          ? (last.payload as Record<string, unknown>)
          : null;
      if (
        last &&
        last.type === type &&
        lastPayload &&
        lastPayload.run_id === runId
      ) {
        last.payload = {
          ...lastPayload,
          delta: String(lastPayload.delta ?? "") + delta,
        };
        return;
      }
      this.events.push({
        type,
        timestamp: event.timestamp,
        payload: { ...payload },
      });
      return;
    }

    if (type === "tool_use_end") {
      const payload =
        event.payload && typeof event.payload === "object"
          ? { ...(event.payload as Record<string, unknown>) }
          : {};
      payload.result = capProcessResult(payload.result);
      this.events.push({
        type,
        timestamp: event.timestamp,
        payload,
      });
      return;
    }

    this.events.push({
      type,
      timestamp: event.timestamp,
      payload: clonePayload(event.payload),
    });
  }

  /** Shallow-copy snapshot for attach replay (sync; safe inside zero-await). */
  snapshot(): BufferedSidecarEvent[] {
    return this.events.map((e) => ({
      type: e.type,
      timestamp: e.timestamp,
      payload: clonePayload(e.payload),
    }));
  }

  hasTerminal(): boolean {
    return this.sealed || this.events.some((e) => isTerminalType(e.type));
  }

  get length(): number {
    return this.events.length;
  }
}
