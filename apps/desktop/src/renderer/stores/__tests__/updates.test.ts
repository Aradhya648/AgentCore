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
import { notifyInfo } from "@/lib/toast";
import {
  __clearMemoryUiStorageForTests,
  __setUiStorageBackendForTests,
} from "@/lib/uiStorage";
import { fetchUpdatesPolicy } from "@/services/system";
import {
  __resetUpdatesModuleForTests,
  loadUpdatePrefs,
  shouldAutoPromptUpdate,
  startUpdates,
  useUpdatesStore,
} from "../updates";

const hasAutoUpdaterMock = vi.mocked(hasAutoUpdater);
const clientVersionMock = vi.mocked(clientVersion);
const fetchPolicyMock = vi.mocked(fetchUpdatesPolicy);
const notifyInfoMock = vi.mocked(notifyInfo);

function stubUpdaterApi() {
  const listeners: Array<(status: unknown) => void> = [];
  const onStatus = vi.fn((cb: (status: unknown) => void) => {
    listeners.push(cb);
    return () => {
      const i = listeners.indexOf(cb);
      if (i >= 0) listeners.splice(i, 1);
    };
  });
  const api = {
    configure: vi.fn(() => Promise.resolve()),
    getStatus: vi.fn(() => Promise.resolve({ phase: "idle" as const })),
    onStatus,
    check: vi.fn(() => Promise.resolve()),
    download: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn(() => Promise.resolve()),
    /** Test helper: push a status as the main process would. */
    _emit(status: unknown) {
      for (const cb of listeners) cb(status);
    },
  };
  vi.stubGlobal("window", { updaterApi: api });
  return api;
}

beforeEach(() => {
  hasAutoUpdaterMock.mockReturnValue(true);
  clientVersionMock.mockReturnValue("0.6.1");
  fetchPolicyMock.mockReset();
  notifyInfoMock.mockReset();
  __setUiStorageBackendForTests(null);
  __clearMemoryUiStorageForTests();
  // Use memory backend so prefs don't leak across tests via real localStorage.
  const mem = new Map<string, string>();
  __setUiStorageBackendForTests({
    getItem: (k) => mem.get(k) ?? null,
    setItem: (k, v) => {
      mem.set(k, v);
    },
    removeItem: (k) => {
      mem.delete(k);
    },
    keys: () => [...mem.keys()],
  });
  __resetUpdatesModuleForTests();
  useUpdatesStore.setState({
    status: { phase: "idle" },
    dialogOpen: false,
    outdatedMinVersion: null,
  });
  stubUpdaterApi();
});

afterEach(() => {
  vi.unstubAllGlobals();
  __setUiStorageBackendForTests(null);
  __clearMemoryUiStorageForTests();
});

describe("shouldAutoPromptUpdate", () => {
  it("prompts when no prefs", () => {
    expect(shouldAutoPromptUpdate("0.7.0", {})).toBe(true);
  });

  it("suppresses skipped version and below", () => {
    expect(shouldAutoPromptUpdate("0.7.0", { skippedVersion: "0.7.0" })).toBe(
      false,
    );
    expect(shouldAutoPromptUpdate("0.6.9", { skippedVersion: "0.7.0" })).toBe(
      false,
    );
    expect(shouldAutoPromptUpdate("0.7.1", { skippedVersion: "0.7.0" })).toBe(
      true,
    );
  });

  it("suppresses snoozed version within window", () => {
    const now = 1_000_000;
    expect(
      shouldAutoPromptUpdate(
        "0.7.0",
        { snooze: { version: "0.7.0", until: now + 1000 } },
        now,
      ),
    ).toBe(false);
    expect(
      shouldAutoPromptUpdate(
        "0.7.0",
        { snooze: { version: "0.7.0", until: now - 1 } },
        now,
      ),
    ).toBe(true);
    expect(
      shouldAutoPromptUpdate(
        "0.7.1",
        { snooze: { version: "0.7.0", until: now + 1000 } },
        now,
      ),
    ).toBe(true);
  });
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

  it("skips hard gate when local is current", async () => {
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

  it("skips hard gate for clientVersion()==='dev'", async () => {
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

  it("force gate ignores persisted skip and opens dialog", () => {
    const api = stubUpdaterApi();
    startUpdates();
    api._emit({ phase: "available", version: "0.7.0" });
    useUpdatesStore.getState().skipVersion();
    expect(loadUpdatePrefs().skippedVersion).toBe("0.7.0");
    expect(useUpdatesStore.getState().dialogOpen).toBe(false);

    useUpdatesStore.setState({ outdatedMinVersion: "0.6.5" });
    api._emit({ phase: "available", version: "0.7.0" });
    expect(useUpdatesStore.getState().dialogOpen).toBe(true);
  });
});

describe("update consent dialog + prefs", () => {
  it("opens dialog on available without starting download", () => {
    const api = stubUpdaterApi();
    startUpdates();
    api._emit({
      phase: "available",
      version: "0.7.0",
      releaseNotes: "notes",
      sizeBytes: 1024,
    });
    const state = useUpdatesStore.getState();
    expect(state.dialogOpen).toBe(true);
    expect(state.status).toMatchObject({
      phase: "available",
      version: "0.7.0",
    });
    expect(api.download).not.toHaveBeenCalled();
  });

  it("remindLater closes dialog and snoozes 24h for same version", () => {
    const api = stubUpdaterApi();
    startUpdates();
    api._emit({ phase: "available", version: "0.7.0" });
    useUpdatesStore.getState().remindLater();
    expect(useUpdatesStore.getState().dialogOpen).toBe(false);
    const prefs = loadUpdatePrefs();
    expect(prefs.snooze?.version).toBe("0.7.0");
    expect(prefs.snooze?.until).toBeGreaterThan(Date.now());

    api._emit({ phase: "available", version: "0.7.0" });
    expect(useUpdatesStore.getState().dialogOpen).toBe(false);
  });

  it("skipVersion persists and suppresses auto prompt after restart-like reload", () => {
    const api = stubUpdaterApi();
    startUpdates();
    api._emit({ phase: "available", version: "0.7.0" });
    useUpdatesStore.getState().skipVersion();
    expect(useUpdatesStore.getState().dialogOpen).toBe(false);
    expect(loadUpdatePrefs().skippedVersion).toBe("0.7.0");

    // Simulate another available push (e.g. after app restart + check).
    useUpdatesStore.setState({ dialogOpen: false });
    api._emit({ phase: "available", version: "0.7.0" });
    expect(useUpdatesStore.getState().dialogOpen).toBe(false);
  });

  it("remindLater / skipVersion are no-ops under hard gate", () => {
    useUpdatesStore.setState({
      outdatedMinVersion: "0.6.5",
      dialogOpen: true,
      status: { phase: "available", version: "0.7.0" },
    });
    useUpdatesStore.getState().remindLater();
    useUpdatesStore.getState().skipVersion();
    useUpdatesStore.getState().closeUpdateDialog();
    expect(useUpdatesStore.getState().dialogOpen).toBe(true);
    expect(loadUpdatePrefs().snooze).toBeUndefined();
    expect(loadUpdatePrefs().skippedVersion).toBeUndefined();
  });

  it("download invokes updaterApi.download", async () => {
    const api = stubUpdaterApi();
    startUpdates();
    api._emit({ phase: "available", version: "0.7.0" });
    await useUpdatesStore.getState().download();
    expect(api.download).toHaveBeenCalled();
  });

  it("toasts on downloaded without auto-install", () => {
    const api = stubUpdaterApi();
    startUpdates();
    api._emit({ phase: "downloaded", version: "0.7.0" });
    expect(notifyInfoMock).toHaveBeenCalled();
    expect(api.quitAndInstall).not.toHaveBeenCalled();
  });
});
