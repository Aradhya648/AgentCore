import {
  coordinationWaitCaptainCaption,
  coordinationWaitLabel,
  waitingWorkerRoles,
} from "@/components/chat/teamSynthesisPhase";
import {
  type Execution,
  execRuntime,
  useActiveExecField,
  useExecutionStore,
} from "@/stores/execution";
import { useEffect, useState } from "react";

/** Seconds since ``startedAt`` ms, ticking once per second while active. */
export function useElapsedSince(startedAt: number | null | undefined): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (startedAt == null) {
      setElapsed(0);
      return;
    }
    const tick = () =>
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  return elapsed;
}

/**
 * Live coordination-wait chrome for StatusStrip / StreamingIndicator / graph.
 * Pass ``messageId`` when the caller is not inside {@link ExecutionScopeContext}
 * (e.g. bottom StreamingIndicator).
 */
export function useCoordinationWaitChrome(
  execution: Execution | null | undefined,
  messageId?: string | null,
) {
  const activeWait = useActiveExecField((rt) => rt.coordinationWait);
  const activeStarted = useActiveExecField(
    (rt) => rt.coordinationWaitStartedAt,
  );
  const scopedWait = useExecutionStore((s) =>
    messageId ? execRuntime(s, messageId).coordinationWait : null,
  );
  const scopedStarted = useExecutionStore((s) =>
    messageId ? execRuntime(s, messageId).coordinationWaitStartedAt : null,
  );
  const wait = messageId ? scopedWait : activeWait;
  const startedAt = messageId ? scopedStarted : activeStarted;
  const elapsedSec = useElapsedSince(wait ? startedAt : null);
  const waitingRoles = execution ? waitingWorkerRoles(execution) : [];
  const waitLabel = coordinationWaitLabel(wait, { elapsedSec, waitingRoles });
  const captainCaption = coordinationWaitCaptainCaption(wait, {
    elapsedSec,
    waitingRoles,
  });
  return {
    wait,
    startedAt,
    elapsedSec,
    waitingRoles,
    waitLabel,
    captainCaption,
  };
}
