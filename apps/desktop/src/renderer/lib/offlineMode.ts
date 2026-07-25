/**
 * N4-A 只读离线 — single predicate for soft-offline UI (composer / files / send).
 *
 * Driven by ambient {@link useServerHealthStore}; mid-session outages no longer
 * blank the AuthGate when a session is already authenticated.
 */
import { useServerHealthStore } from "@/stores/serverHealth";

export function isReadOnlyOffline(): boolean {
  return useServerHealthStore.getState().status === "offline";
}

export function useReadOnlyOffline(): boolean {
  return useServerHealthStore((s) => s.status === "offline");
}
