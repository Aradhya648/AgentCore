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
import { BROWSER_PARTITION, normalizeBrowserBounds } from "../browser/paths";
import {
  WORKSPACE_PARTITION,
  WORKSPACE_SCHEME,
  buildWorkspaceUrl,
  isWorkspaceBrowserUrl,
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

describe("BROWSER_PARTITION / WORKSPACE_PARTITION (L1b)", () => {
  it("are non-persistent and mutually distinct from preview", () => {
    expect(BROWSER_PARTITION).toBe("agentcore-browser");
    expect(WORKSPACE_PARTITION).toBe("agentcore-browser-workspace");
    expect(BROWSER_PARTITION.startsWith("persist:")).toBe(false);
    expect(WORKSPACE_PARTITION.startsWith("persist:")).toBe(false);
    expect(BROWSER_PARTITION).not.toBe(WORKSPACE_PARTITION);
    expect(BROWSER_PARTITION).not.toBe("agentcore-preview");
    expect(WORKSPACE_PARTITION).not.toBe("agentcore-preview");
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
