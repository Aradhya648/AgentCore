/**
 * Host main-process op unit tests (no Electron shell side effects for ping/info).
 */
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  ipcMain: { handle: vi.fn() },
  shell: { openExternal: vi.fn(async () => undefined) },
}));

import { shell } from "electron";
import { runHostOp } from "../host-service";

describe("runHostOp", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("host_ping returns ok envelope", async () => {
    const result = await runHostOp({ op: "host_ping" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.ok).toBe(true);
      expect(result.value.platform).toBeTruthy();
    }
  });

  it("host_info returns machine facts", async () => {
    const result = await runHostOp({ op: "host_info" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.platform).toBeTruthy();
      expect(typeof result.value.total_mem_mb).toBe("number");
    }
  });

  it("host_network_summary returns iface summary without scan note", async () => {
    const result = await runHostOp({ op: "host_network_summary" });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.note).toBe("local_iface_summary_no_port_scan");
      expect(Array.isArray(result.value.adapters)).toBe(true);
    }
  });

  it("host_open_settings rejects unknown panel", async () => {
    const result = await runHostOp({
      op: "host_open_settings",
      args: { panel: "bluetooth" },
    });
    expect(result.ok).toBe(false);
  });

  it("host_open_settings accepts display panel on win32", async () => {
    if (process.platform !== "win32") {
      const result = await runHostOp({
        op: "host_open_settings",
        args: { panel: "display" },
      });
      // Non-Win: whitelist accepts, OS may stub.
      expect(result.ok).toBe(true);
      return;
    }
    const result = await runHostOp({
      op: "host_open_settings",
      args: { panel: "display" },
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.panel).toBe("display");
      expect(result.value.uri).toBe("ms-settings:display");
    }
    expect(shell.openExternal).toHaveBeenCalledWith("ms-settings:display");
  });

  it("host_service_restart rejects unknown service", async () => {
    const result = await runHostOp({
      op: "host_service_restart",
      args: { service: "Spooler" },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("HostServiceNotAllowlisted");
    }
  });

  it("host_service_restart allowlisted Audiosrv has real impl or honest failure", async () => {
    const result = await runHostOp({
      op: "host_service_restart",
      args: { service: "Audiosrv" },
    });
    if (process.platform !== "win32") {
      expect(result.ok).toBe(false);
      if (!result.ok) {
        expect(result.error.kind).toBe("HostServiceRestartStub");
      }
      return;
    }
    // Win: Restart-Service may need elevation — accept success or clear error.
    if (result.ok) {
      expect(result.value.service).toBe("Audiosrv");
      expect(result.value.restarted).toBe(true);
    } else {
      expect(result.error.kind).toBe("HostServiceRestartError");
      expect(result.error.detail.length).toBeGreaterThan(0);
    }
  });

  it("host_audio_set_default rejects missing device", async () => {
    const result = await runHostOp({ op: "host_audio_set_default", args: {} });
    expect(result.ok).toBe(false);
  });

  it("host_audio_set_default rejects unknown device", async () => {
    const result = await runHostOp({
      op: "host_audio_set_default",
      args: { device_name: "__agentcore_no_such_device__" },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      if (process.platform === "win32") {
        // Prefer unknown-device reject; probe failure is also an honest fail-closed.
        expect(["HostAudioDeviceUnknown", "HostAudioProbeError"]).toContain(
          result.error.kind,
        );
      } else {
        expect(result.error.kind).toBe("HostAudioSetDefaultStub");
      }
    }
  });

  it("unknown op fails honestly", async () => {
    const result = await runHostOp({ op: "host_wipe_disk" });
    expect(result.ok).toBe(false);
  });

  it("host_shell rejects empty command", async () => {
    const result = await runHostOp({ op: "host_shell", args: { command: "  " } });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("HostShellEmptyCommand");
    }
  });

  it("host_shell fuse blocks rm -rf /", async () => {
    const result = await runHostOp({
      op: "host_shell",
      args: { command: "rm -rf /" },
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("HostShellFuse");
    }
  });

  it("host_shell runs a trivial command", async () => {
    const command =
      process.platform === "win32" ? "Write-Output 'p3ok'" : "echo p3ok";
    const result = await runHostOp({
      op: "host_shell",
      args: { command, timeout_seconds: 15 },
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.timed_out).toBe(false);
      expect(result.value.exit_code).toBe(0);
      expect(String(result.value.stdout)).toContain("p3ok");
    }
  });

  it("host_shell times out and reports honestly", async () => {
    const command =
      process.platform === "win32"
        ? "Start-Sleep -Seconds 5"
        : "sleep 5";
    const result = await runHostOp({
      op: "host_shell",
      args: { command, timeout_seconds: 1 },
    });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.value.timed_out).toBe(true);
      expect(result.value.exit_code).toBeNull();
    }
  }, 15_000);
});
