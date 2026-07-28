/**
 * W3 session readonly root helpers (pathGuard algorithm unchanged).
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";
import type { StoredRoot } from "../fs/roots";
import { executeWorkspaceOp } from "../fs/workspace/dispatch";
import {
  buildExternalEnvFromRoots,
  buildWorkspacePythonpathEnv,
} from "../fs/workspace/exec";

const readonlyRoot: StoredRoot = {
  id: "s1",
  name: "reports",
  absPath: "C:\\tmp\\reports",
  sessionOnly: true,
  conversationId: "c1",
  readonly: true,
  alias: "reports",
};

describe("session readonly root write refusal", () => {
  it("rejects file write ops on readonly roots", async () => {
    const r = await executeWorkspaceOp(readonlyRoot, "write", {
      path: "a.txt",
      content: "x",
    });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.kind).toBe("OutsideWorkspace");
      expect(r.error.detail).toContain("只读");
    }
  });

  it.each(["execute", "process_start", "archive"] as const)(
    "rejects %s on readonly roots",
    async (op) => {
      const r = await executeWorkspaceOp(readonlyRoot, op, {});
      expect(r.ok).toBe(false);
      if (!r.ok) {
        expect(r.error.kind).toBe("OutsideWorkspace");
        expect(r.error.detail).toContain("只读");
      }
    },
  );
});

describe("session organize root mode whitelist", () => {
  const organizeRoot: StoredRoot = {
    id: "s2",
    name: "Desktop",
    absPath: "C:\\tmp\\desktop",
    sessionOnly: true,
    conversationId: "c1",
    mode: "organize",
    alias: "desktop",
  };

  it("mode gate allows move/copy/mkdir/delete under organize", async () => {
    const { sessionRootAccessError } = await import("../fs/workspace/dispatch");
    for (const op of ["mkdir", "move", "copy", "delete"] as const) {
      expect(
        sessionRootAccessError(
          organizeRoot,
          op,
          op === "mkdir" || op === "delete"
            ? { path: "Docs" }
            : { src: "a.txt", dst: "Docs/a.txt" },
        ),
      ).toBeNull();
    }
  });

  it.each(["write", "execute", "process_start", "archive"] as const)(
    "rejects %s under organize",
    async (op) => {
      const r = await executeWorkspaceOp(organizeRoot, op, {
        path: "a.txt",
        content: "x",
      });
      expect(r.ok).toBe(false);
      if (!r.ok) {
        expect(r.error.kind).toBe("OutsideWorkspace");
        expect(r.error.detail).toMatch(/整理授权|不允许/);
      }
    },
  );

  it("rejects permanent delete under organize", async () => {
    const r = await executeWorkspaceOp(organizeRoot, "delete", {
      path: "a.txt",
      permanent: true,
    });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.detail).toContain("永久删除");
    }
  });
});

describe("buildExternalEnvFromRoots conversation ownership", () => {
  const grant: StoredRoot = {
    id: "ext-1",
    name: "reports",
    absPath: "C:\\data\\reports",
    sessionOnly: true,
    conversationId: "c1",
    readonly: true,
    alias: "reports",
  };
  const otherConv: StoredRoot = {
    ...grant,
    id: "ext-2",
    conversationId: "c-other",
  };
  const permanent: StoredRoot = {
    id: "perm-1",
    name: "proj",
    absPath: "C:\\data\\proj",
  };

  const lookup = (id: string) =>
    ({ "ext-1": grant, "ext-2": otherConv, "perm-1": permanent })[id];

  it("injects only matching sessionOnly grants for the conversation", () => {
    const env = buildExternalEnvFromRoots(
      { reports: "ext-1", other: "ext-2", proj: "perm-1" },
      "c1",
      lookup,
    );
    expect(env).toEqual({ AGENTCORE_EXTERNAL_REPORTS: "C:\\data\\reports" });
  });

  it("skips organize-mode session roots from env injection", () => {
    const organize: StoredRoot = {
      ...grant,
      id: "ext-org",
      mode: "organize",
      readonly: false,
    };
    const orgLookup = (id: string) =>
      ({ "ext-1": grant, "ext-org": organize })[id];
    const env = buildExternalEnvFromRoots(
      { reports: "ext-1", desk: "ext-org" },
      "c1",
      orgLookup,
    );
    expect(env).toEqual({ AGENTCORE_EXTERNAL_REPORTS: "C:\\data\\reports" });
  });

  it("skips injection when conversation_id is empty", () => {
    const env = buildExternalEnvFromRoots({ reports: "ext-1" }, "", lookup);
    expect(env).toEqual({});
  });
});

describe("buildWorkspacePythonpathEnv (D11′)", () => {
  it("prepends cwd and existing src/lib, keeps previous PYTHONPATH", async () => {
    const { mkdtemp, mkdir, rm } = await import("node:fs/promises");
    const { tmpdir } = await import("node:os");
    const { join, delimiter } = await import("node:path");
    const root = await mkdtemp(join(tmpdir(), "ac-pp-"));
    try {
      await mkdir(join(root, "src"));
      const env = buildWorkspacePythonpathEnv(root, "keep-me");
      const parts = env.PYTHONPATH.split(delimiter);
      expect(parts[0]).toBe(root);
      expect(parts).toContain(join(root, "src"));
      expect(parts[parts.length - 1]).toBe("keep-me");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
