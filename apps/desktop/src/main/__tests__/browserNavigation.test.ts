import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  LOCAL_BROWSER_BLANK,
  isAllowedLocalBrowserUrl,
  isAllowedWebBrowserUrl,
  isAllowedWorkspaceBrowserUrl,
  isNavigableLocalBrowserUrl,
  resolveBridgeNavigateKind,
} from "../browser/navigation-policy";
import {
  BROWSER_PARTITION_PREFIX,
  browserPartitionFor,
  normalizeBrowserBounds,
} from "../browser/paths";
import {
  WORKSPACE_PARTITION_PREFIX,
  WORKSPACE_SCHEME,
  buildWorkspaceUrl,
  isWorkspaceBrowserUrl,
  resolveWorkspaceProtocolRequest,
  workspacePartitionFor,
} from "../browser/workspace-paths";

describe("isAllowedWebBrowserUrl", () => {
  it("allows http(s) including localhost", () => {
    expect(isAllowedWebBrowserUrl("https://example.com")).toBe(true);
    expect(isAllowedWebBrowserUrl("http://localhost:3000/app")).toBe(true);
  });

  it("rejects workspace and file schemes", () => {
    expect(isAllowedWebBrowserUrl("workspace://c1/a.html")).toBe(false);
    expect(isAllowedWebBrowserUrl("file:///C:/Windows")).toBe(false);
  });
});

describe("isAllowedWorkspaceBrowserUrl", () => {
  it("allows workspace:// and about:blank", () => {
    expect(isAllowedWorkspaceBrowserUrl("workspace://c1/site/index.html")).toBe(
      true,
    );
    expect(isAllowedWorkspaceBrowserUrl(LOCAL_BROWSER_BLANK)).toBe(true);
  });

  it("rejects http(s) top-level (外链不进工作区 partition)", () => {
    expect(isAllowedWorkspaceBrowserUrl("https://example.com")).toBe(false);
    expect(isAllowedWorkspaceBrowserUrl("preview://c1/a.html")).toBe(false);
  });
});

describe("isAllowedLocalBrowserUrl", () => {
  it("allows http(s) including localhost", () => {
    expect(isAllowedLocalBrowserUrl("https://example.com")).toBe(true);
    expect(isAllowedLocalBrowserUrl("http://localhost:3000/app")).toBe(true);
    expect(isAllowedLocalBrowserUrl("https://127.0.0.1/")).toBe(true);
  });

  it("allows about:blank for empty tabs", () => {
    expect(isAllowedLocalBrowserUrl(LOCAL_BROWSER_BLANK)).toBe(true);
  });

  it("allows workspace scheme (L1b)", () => {
    expect(isAllowedLocalBrowserUrl("workspace://conv/a.html")).toBe(true);
  });

  it("rejects file and other dangerous schemes", () => {
    expect(isAllowedLocalBrowserUrl("file:///C:/Windows")).toBe(false);
    expect(isAllowedLocalBrowserUrl("javascript:alert(1)")).toBe(false);
    expect(isAllowedLocalBrowserUrl("data:text/html,hi")).toBe(false);
    expect(isAllowedLocalBrowserUrl("preview://conv/a.html")).toBe(false);
    expect(isAllowedLocalBrowserUrl("")).toBe(false);
  });
});

describe("isNavigableLocalBrowserUrl", () => {
  it("requires http(s) or workspace (not about:blank)", () => {
    expect(isNavigableLocalBrowserUrl("https://example.com")).toBe(true);
    expect(isNavigableLocalBrowserUrl("workspace://c1/x.html")).toBe(true);
    expect(isNavigableLocalBrowserUrl(LOCAL_BROWSER_BLANK)).toBe(false);
    expect(isNavigableLocalBrowserUrl("file:///tmp/x")).toBe(false);
  });
});

describe("resolveBridgeNavigateKind", () => {
  it("maps http(s) → web, workspace:// → workspace", () => {
    expect(resolveBridgeNavigateKind("https://example.com")).toBe("web");
    expect(resolveBridgeNavigateKind("http://localhost:3000")).toBe("web");
    expect(resolveBridgeNavigateKind("workspace://c1/site/index.html")).toBe(
      "workspace",
    );
  });

  it("rejects relative paths and file:// (rewrite happens server-side)", () => {
    expect(resolveBridgeNavigateKind("site/index.html")).toBeNull();
    expect(resolveBridgeNavigateKind("file:///tmp/x")).toBeNull();
    expect(resolveBridgeNavigateKind("")).toBeNull();
  });
});

describe("browser / workspace partition by conversationId", () => {
  it("外网与 workspace 按 cid 切开，同 cid 两 tab 同 partition 名", () => {
    expect(browserPartitionFor("conv-a")).toBe("agentcore-browser:conv:conv-a");
    expect(browserPartitionFor("conv-b")).toBe("agentcore-browser:conv:conv-b");
    expect(browserPartitionFor("conv-a")).toBe(browserPartitionFor("Conv-A"));
    expect(workspacePartitionFor("conv-a")).toBe(
      "agentcore-browser-workspace:conv:conv-a",
    );
    expect(workspacePartitionFor("conv-b")).not.toBe(
      workspacePartitionFor("conv-a"),
    );
    expect(BROWSER_PARTITION_PREFIX.startsWith("persist:")).toBe(false);
    expect(WORKSPACE_PARTITION_PREFIX.startsWith("persist:")).toBe(false);
    expect(browserPartitionFor("c1")).not.toBe(workspacePartitionFor("c1"));
    expect(browserPartitionFor("c1")).not.toContain("agentcore-preview");
    expect(workspacePartitionFor("c1")).not.toContain("agentcore-preview");
  });

  it("缺 conversationId 抛错（不回落全局 partition）", () => {
    expect(() => browserPartitionFor("")).toThrow(/conversationId/);
    expect(() => workspacePartitionFor("  ")).toThrow(/conversationId/);
  });
});

describe("workspace protocol host === partition cid", () => {
  it("同 cid 可解析；跨 cid → 403", () => {
    expect(
      resolveWorkspaceProtocolRequest(
        "workspace://conv-a/site/index.html",
        "conv-a",
      ),
    ).toEqual({
      ok: true,
      conversationId: "conv-a",
      rel: "site/index.html",
    });
    expect(
      resolveWorkspaceProtocolRequest(
        "workspace://conv-b/site/index.html",
        "conv-a",
      ),
    ).toEqual({ ok: false, status: 403 });
  });
});

describe("buildWorkspaceUrl", () => {
  it("uses workspace scheme and encodes path", () => {
    expect(buildWorkspaceUrl("Conv-ID", "dir/a b.html")).toBe(
      "workspace://conv-id/dir/a%20b.html",
    );
    expect(WORKSPACE_SCHEME).toBe("workspace");
    expect(isWorkspaceBrowserUrl("workspace://c1/x.html")).toBe(true);
  });
});

describe("normalizeBrowserBounds", () => {
  it("rounds and clamps", () => {
    expect(
      normalizeBrowserBounds({ x: 1.2, y: 3.8, width: 100.4, height: -2 }),
    ).toEqual({ x: 1, y: 4, width: 100, height: 0 });
  });

  it("rejects malformed", () => {
    expect(normalizeBrowserBounds(null)).toBeNull();
    expect(
      normalizeBrowserBounds({ x: 0, y: 0, width: "a", height: 1 }),
    ).toBeNull();
  });
});

describe("lockPreviewNavigation 未改（M3a 禁区）", () => {
  it("preview/navigation.ts 仍只放行 preview://（未放行 http / workspace）", () => {
    const src = readFileSync(
      join(__dirname, "../preview/navigation.ts"),
      "utf8",
    );
    expect(src).toContain("lockPreviewNavigation");
    expect(src).toContain("PREVIEW_SCHEME");
    expect(src).toMatch(/target\.startsWith\(`\$\{PREVIEW_SCHEME\}:\/\//);
    expect(src).not.toContain("workspace");
    expect(src).not.toContain("http:");
    expect(src).not.toContain("BROWSER_PARTITION");
  });
});
