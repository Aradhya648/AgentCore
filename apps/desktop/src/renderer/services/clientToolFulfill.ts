import { ApiError } from "@/services/api";
import { resolveInteraction } from "@/services/interaction";

/** Result envelope posted as `ResolveClientToolInteraction` (sans `kind`). */
export type ClientToolResultEnvelope =
  | { ok: true; value: unknown }
  | {
      ok: false;
      error: { kind: string; detail: string; [key: string]: unknown };
    };

type FulfilledEntry = {
  result: ClientToolResultEnvelope;
  resolved: boolean;
  resolveGate: Promise<void> | null;
};

/** In-flight perform+resolve for a request_id (join waiters). */
const inFlight = new Map<string, Promise<void>>();

/** Successfully performed side effects — skip re-run; may still resolve. */
const fulfilled = new Map<string, FulfilledEntry>();

/** Test-only: clear process-local fulfillment state. */
export function resetClientToolFulfillmentForTests(): void {
  inFlight.clear();
  fulfilled.clear();
}

async function tryResolve(
  conversationId: string,
  requestId: string,
  result: ClientToolResultEnvelope,
  logLabel: string,
): Promise<boolean> {
  try {
    await resolveInteraction(conversationId, requestId, {
      kind: "client_tool",
      ...result,
    });
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return true; // stale — no-op
    console.error(`[${logLabel}] 回填失败`, err);
    return false;
  }
}

/**
 * Desktop client_tool fulfillment gate (attach rehang safety).
 *
 * Same `request_id` already in-flight or successfully fulfilled in this process →
 * skip the side effect. Still retries resolve when the first settle has not landed.
 * Failed side effects are not cached, so a later delivery may re-perform.
 */
export async function fulfillClientToolOnce(opts: {
  requestId: string;
  conversationId: string;
  logLabel: string;
  perform: () => Promise<ClientToolResultEnvelope>;
}): Promise<void> {
  const { requestId, conversationId, logLabel, perform } = opts;

  const pending = inFlight.get(requestId);
  if (pending) await pending;

  const cached = fulfilled.get(requestId);
  if (cached) {
    if (cached.resolved) return;
    if (cached.resolveGate) {
      await cached.resolveGate;
      return;
    }
    const gate = (async () => {
      cached.resolved = await tryResolve(
        conversationId,
        requestId,
        cached.result,
        logLabel,
      );
    })();
    cached.resolveGate = gate;
    try {
      await gate;
    } finally {
      cached.resolveGate = null;
    }
    return;
  }

  if (inFlight.has(requestId)) {
    await inFlight.get(requestId);
    return fulfillClientToolOnce(opts);
  }

  const run = (async () => {
    const result = await perform();
    if (result.ok) {
      fulfilled.set(requestId, {
        result,
        resolved: false,
        resolveGate: null,
      });
    }
    const settled = await tryResolve(
      conversationId,
      requestId,
      result,
      logLabel,
    );
    if (result.ok) {
      const entry = fulfilled.get(requestId);
      if (entry) entry.resolved = settled;
    }
  })();

  inFlight.set(requestId, run);
  try {
    await run;
  } finally {
    inFlight.delete(requestId);
  }
}
