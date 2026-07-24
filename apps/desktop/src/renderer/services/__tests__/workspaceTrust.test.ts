import { __setUiStorageBackendForTests } from "@/lib/uiStorage";
import {
  clearTrustedWorkspaceRootsForTests,
  isWorkspaceRootTrusted,
  suggestObserveForUntrustedLocal,
  trustWorkspaceRoot,
} from "@/services/workspaceTrust";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

// vitest 跑在 node 环境（无 localStorage）——给 uiStorage 装内存后端。
const memory = new Map<string, string>();

beforeEach(() => {
  memory.clear();
  __setUiStorageBackendForTests({
    getItem: (k) => memory.get(k) ?? null,
    setItem: (k, v) => {
      memory.set(k, v);
    },
    removeItem: (k) => {
      memory.delete(k);
    },
    keys: () => [...memory.keys()],
  });
});

afterEach(() => {
  clearTrustedWorkspaceRootsForTests();
  __setUiStorageBackendForTests(null);
});

describe("workspaceTrust", () => {
  it("persists trusted roots", () => {
    expect(isWorkspaceRootTrusted("C:\\proj\\foo")).toBe(false);
    trustWorkspaceRoot("C:\\proj\\foo");
    expect(isWorkspaceRootTrusted("C:/proj/foo")).toBe(true);
  });

  it("suggests observe only for untrusted non-git local roots", () => {
    expect(
      suggestObserveForUntrustedLocal({
        localRootPath: "D:\\scratch",
        isGitRepo: false,
      }),
    ).toBe(true);
    expect(
      suggestObserveForUntrustedLocal({
        localRootPath: "D:\\scratch",
        isGitRepo: true,
      }),
    ).toBe(false);
    trustWorkspaceRoot("D:\\scratch");
    expect(
      suggestObserveForUntrustedLocal({
        localRootPath: "D:\\scratch",
        isGitRepo: false,
      }),
    ).toBe(false);
  });
});
