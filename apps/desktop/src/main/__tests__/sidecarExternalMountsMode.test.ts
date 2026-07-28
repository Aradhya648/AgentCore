/**
 * Sidecar externalMounts must forward mode so organize is not degraded to readonly.
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";
import type { StoredRoot } from "../fs/roots";

/** Mirror of sidecar-service mapping (keep in sync with startTurn / resume). */
function mapExternalMounts(sessionRoots: StoredRoot[]) {
  return sessionRoots
    .filter((r) => r.alias && r.absPath)
    .map((r) => ({
      alias: r.alias as string,
      rootId: r.id,
      label: r.name,
      absPath: r.absPath,
      mode: r.mode ?? (r.readonly ? "readonly" : "readonly"),
    }));
}

describe("sidecar externalMounts mode", () => {
  it("preserves organize mode on mapped mounts", () => {
    const mounts = mapExternalMounts([
      {
        id: "r1",
        name: "Desktop",
        absPath: "C:\\Users\\me\\Desktop",
        sessionOnly: true,
        conversationId: "c1",
        mode: "organize",
        alias: "desk",
      },
    ]);
    expect(mounts).toEqual([
      {
        alias: "desk",
        rootId: "r1",
        label: "Desktop",
        absPath: "C:\\Users\\me\\Desktop",
        mode: "organize",
      },
    ]);
  });

  it("defaults missing mode to readonly", () => {
    const mounts = mapExternalMounts([
      {
        id: "r2",
        name: "reports",
        absPath: "C:\\reports",
        sessionOnly: true,
        conversationId: "c1",
        alias: "reports",
      },
    ]);
    expect(mounts[0]?.mode).toBe("readonly");
  });
});
