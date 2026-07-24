import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", () => ({
  hasAutoUpdater: vi.fn(() => true),
}));
vi.mock("@/lib/clientBuildInfo", () => ({
  clientVersion: vi.fn(() => "0.6.1"),
}));
vi.mock("@/services/system", () => ({
  fetchUpdatesPolicy: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({
  notifyInfo: vi.fn(),
}));

import { hasAutoUpdater } from "@/lib/capabilities";
import { clientVersion } from "@/lib/clientBuildInfo";
import { fetchUpdatesPolicy } from "@/services/system";
import { startUpdates, useUpdatesStore } from "../updates";

const hasAutoUpdaterMock = vi.mocked(hasAutoUpdater);
const clientVersionMock = vi.mocked(clientVersion);
const fetchPolicyMock = vi.mocked(fetchUpdatesPolicy);

function stubUpdaterApi() {
  const onStatus = vi.fn(() => () => {});
  const api = {
    configure: vi.fn(() => Promise.resolve()),
    getStatus: vi.fn(() => Promise.resolve({ phase: "idle" as const })),
    onStatus,
    check: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn(() => Promise.resolve()),
  };
  vi.stubGlobal("window", { updaterApi: api });
  return api;
}

beforeEach(() => {
  hasAutoUpdaterMock.mockReturnValue(true);
  clientVersionMock.mockReturnValue("0.6.1");
  fetchPolicyMock.mockReset();
  useUpdatesStore.setState({
    status: { phase: "idle" },
    outdatedMinVersion: null,
    outdatedDismissed: false,
  });
  stubUpdaterApi();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("startUpdates outdated policy", () => {
  it("sets outdatedMinVersion when local is below policy floor", async () => {
    fetchPolicyMock.mockResolvedValue({
      enabled: true,
      minDesktopVersion: "0.6.5",
    });
    startUpdates();
    await vi.waitFor(() =>
      expect(useUpdatesStore.getState().outdatedMinVersion).toBe("0.6.5"),
    );
  });

  it("skips banner when local is current", async () => {
    clientVersionMock.mockReturnValue("0.6.6");
    fetchPolicyMock.mockResolvedValue({
      enabled: true,
      minDesktopVersion: "0.6.5",
    });
    startUpdates();
    await Promise.resolve();
    await Promise.resolve();
    expect(useUpdatesStore.getState().outdatedMinVersion).toBeNull();
  });

  it("skips banner for clientVersion()==='dev'", async () => {
    clientVersionMock.mockReturnValue("dev");
    fetchPolicyMock.mockResolvedValue({
      enabled: true,
      minDesktopVersion: "0.6.5",
    });
    startUpdates();
    await Promise.resolve();
    await Promise.resolve();
    expect(useUpdatesStore.getState().outdatedMinVersion).toBeNull();
  });

  it("does not poll policy on web (no auto-updater)", async () => {
    hasAutoUpdaterMock.mockReturnValue(false);
    startUpdates();
    await Promise.resolve();
    expect(fetchPolicyMock).not.toHaveBeenCalled();
  });
});
