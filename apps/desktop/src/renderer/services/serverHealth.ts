import { diagnoseOutage } from "@/services/auth";
import { useServerHealthStore } from "@/stores/serverHealth";

/**
 * Ambient backend-connectivity heartbeat.
 *
 * The app used to learn the server was down only *reactively* — either at
 * startup (AuthGate bootstrap) or when a request happened to fail. So a user had
 * no way to know the backend was unreachable **before** hitting send. This
 * monitor proactively probes `/readyz` on a cadence (via {@link diagnoseOutage},
 * the same readiness diagnosis the AuthGate uses), tightening while offline so a
 * recovery is picked up quickly, and also probes on tab focus / browser
 * online-offline events. It folds each verdict into {@link useServerHealthStore},
 * which the composer's connection indicator renders.
 *
 * `diagnoseOutage` uses a raw `fetch` (not the `api` layer), so these background
 * probes never trip the AuthGate's reactive full-screen outage takeover — the
 * ambient indicator and the hard-outage screen stay independent.
 */

/** Steady-state cadence while connected. */
const ONLINE_INTERVAL_MS = 20_000;
/** Faster cadence while offline, so a recovery is reflected quickly. */
const OFFLINE_INTERVAL_MS = 5_000;

let probeInFlight: Promise<boolean> | null = null;

/** Probe `/readyz` once (deduped) and fold the verdict into the health store. */
export async function probeServerHealth(): Promise<boolean> {
  if (probeInFlight) return probeInFlight;
  probeInFlight = (async () => {
    const reason = await diagnoseOutage(); // null = healthy
    const store = useServerHealthStore.getState();
    if (reason === null) {
      store.markOnline();
      return true;
    }
    store.markOffline(reason);
    return false;
  })().finally(() => {
    probeInFlight = null;
  });
  return probeInFlight;
}

/**
 * Start the heartbeat. Returns a disposer that stops polling and unbinds the
 * focus / online / offline listeners. Safe to call once per authenticated
 * session (the AppShell owns its lifecycle).
 */
export function startServerHealthMonitor(): () => void {
  let timer: number | undefined;
  let stopped = false;

  const loop = async () => {
    if (stopped) return;
    await probeServerHealth();
    if (stopped) return;
    const delay =
      useServerHealthStore.getState().status === "offline"
        ? OFFLINE_INTERVAL_MS
        : ONLINE_INTERVAL_MS;
    timer = window.setTimeout(() => void loop(), delay);
  };

  const probeNow = () => void probeServerHealth();
  // The browser reports a full network drop instantly — reflect it without
  // waiting for the next poll; the loop then confirms/recovers on its cadence.
  const onOffline = () =>
    useServerHealthStore.getState().markOffline("网络已断开，请检查网络连接");

  window.addEventListener("focus", probeNow);
  window.addEventListener("online", probeNow);
  window.addEventListener("offline", onOffline);

  void loop();

  return () => {
    stopped = true;
    if (timer) window.clearTimeout(timer);
    window.removeEventListener("focus", probeNow);
    window.removeEventListener("online", probeNow);
    window.removeEventListener("offline", onOffline);
  };
}
