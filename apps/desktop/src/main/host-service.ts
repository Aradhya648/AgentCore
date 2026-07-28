/**
 * 本机 Host 能力 —— 主进程履行（Win 优先探测；mac/linux stub 同 schema）。
 *
 * 运输层对标 workspace / desktop_notify：renderer 收到 `host_op_required` 后经
 * 本 IPC 执行，再 resolveInteraction 回填；不经 BrowserBridge loopback。
 */
import {
  type HostOpInput,
  type HostOpResult,
  HOST_CHANNELS,
} from "@shared/host-contract";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import os from "node:os";
import { ipcMain, shell } from "electron";

const execFileAsync = promisify(execFile);

/** L2 panel whitelist — keep closed (Host 定案 P1). */
const OPEN_SETTINGS_PANELS = new Set([
  "sound",
  "display",
  "network",
  "apps",
  "about",
]);

/** L3 service-name whitelist — keep closed (Host 定案 P2). Canonical SCM names only. */
const SERVICE_RESTART_ALLOWLIST = new Set(["audiosrv"]);

/** P3 host_shell timeout clamp (seconds). */
const SHELL_TIMEOUT_DEFAULT = 60;
const SHELL_TIMEOUT_MAX = 120;
const SHELL_OUTPUT_MAX = 200_000;

/**
 * Heuristic fuse — not a complete security boundary (Host 定案 P3).
 * Keep in rough lockstep with server ``shell_fuse_blocks``.
 */
const SHELL_FUSE_PATTERNS: RegExp[] = [
  /\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|-[a-zA-Z]*r[a-zA-Z]*\s+)*(\/|\/\*|~|\/home)\b/i,
  /\brm\s+-rf\s+\//i,
  /\bformat\s+[a-z]:/i,
  /\bFormat-Volume\b/i,
  /\bClear-Disk\b/i,
  /\b(shutdown|poweroff|reboot|halt)\b/i,
  /\bStop-Computer\b/i,
  /\bRestart-Computer\b/i,
  /\bmkfs(\.\w+)?\b/i,
  /\bdd\s+.*\bof\s*=\s*\/dev\//i,
  /\bdel\s+\/[sq]\s+[a-z]:\\?\s*$/i,
  /\bRemove-Item\b.*-[Rr]ecurse.*[Cc]:\\/i,
  /:\(\)\s*\{\s*:\|:&\s*\}\s*;/,
  /\bcipher\s+\/w:/i,
];

function shellFuseBlocks(command: string): string | null {
  const text = command.trim();
  if (!text) return null;
  for (const pat of SHELL_FUSE_PATTERNS) {
    if (pat.test(text)) {
      return (
        "host_shell 熔断：命令匹配毁灭性启发式黑名单（格式化磁盘 / " +
        "rm -rf / / shutdown 等）。此为兜底、非完整安全边界。"
      );
    }
  }
  return null;
}

function clampShellTimeout(raw: unknown): number {
  if (raw === undefined || raw === null || raw === "") return SHELL_TIMEOUT_DEFAULT;
  const n = typeof raw === "number" ? raw : Number.parseInt(String(raw), 10);
  if (!Number.isFinite(n)) return SHELL_TIMEOUT_DEFAULT;
  return Math.max(1, Math.min(SHELL_TIMEOUT_MAX, Math.trunc(n)));
}

function truncateOut(s: string): string {
  if (s.length <= SHELL_OUTPUT_MAX) return s;
  return `${s.slice(0, SHELL_OUTPUT_MAX)}\n…[truncated]`;
}

const WIN_SETTINGS_URI: Record<string, string> = {
  sound: "ms-settings:sound",
  display: "ms-settings:display",
  network: "ms-settings:network",
  apps: "ms-settings:appsfeatures",
  about: "ms-settings:about",
};

/** Best-effort mac System Settings / Preferences deep links. */
const MAC_SETTINGS_URI: Record<string, string> = {
  sound: "x-apple.systempreferences:com.apple.preference.sound",
  display: "x-apple.systempreferences:com.apple.preference.displays",
  network: "x-apple.systempreferences:com.apple.preference.network",
  // Apps / About have no stable preference pane URI on all macOS versions.
};

const APPS_SAMPLE_LIMIT = 30;

function err(detail: string, kind = "HostOpError"): HostOpResult {
  return { ok: false, error: { kind, detail } };
}

function ok(value: Record<string, unknown>): HostOpResult {
  return { ok: true, value };
}

async function runPowerShell(script: string, timeoutMs = 12_000): Promise<string> {
  const { stdout } = await execFileAsync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", script],
    {
      timeout: timeoutMs,
      windowsHide: true,
      encoding: "utf8",
      maxBuffer: 2_000_000,
    },
  );
  return (stdout || "").trim();
}

/** Multiline / here-string safe — avoids -Command quoting breakage. */
async function runPowerShellEncoded(
  script: string,
  timeoutMs = 12_000,
): Promise<string> {
  const encoded = Buffer.from(script, "utf16le").toString("base64");
  const { stdout } = await execFileAsync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
    {
      timeout: timeoutMs,
      windowsHide: true,
      encoding: "utf8",
      maxBuffer: 2_000_000,
    },
  );
  return (stdout || "").trim();
}

function parseJsonArray(raw: string): unknown[] {
  if (!raw) return [];
  const parsed = JSON.parse(raw) as unknown;
  return Array.isArray(parsed) ? parsed : [parsed];
}

async function hostPing(): Promise<HostOpResult> {
  return ok({
    ok: true,
    platform: process.platform,
    ts: new Date().toISOString(),
  });
}

async function hostInfo(): Promise<HostOpResult> {
  return ok({
    platform: process.platform,
    arch: process.arch,
    release: os.release(),
    hostname: os.hostname(),
    endianness: os.endianness(),
    cpus: os.cpus().length,
    total_mem_mb: Math.round(os.totalmem() / (1024 * 1024)),
    freemem_mb: Math.round(os.freemem() / (1024 * 1024)),
    uptime_s: Math.round(os.uptime()),
  });
}

async function listAudioDevicesWin(): Promise<HostOpResult> {
  // Prefer AudioEndpoint PnP names (playback/capture). Fallback to Win32_SoundDevice.
  const ps = [
    "$ErrorActionPreference='Stop'",
    "$eps = Get-PnpDevice -Class AudioEndpoint -Status OK -ErrorAction SilentlyContinue |",
    "  Select-Object -Property FriendlyName, InstanceId",
    "if ($eps) {",
    "  $eps | ForEach-Object {",
    "    [PSCustomObject]@{ name=$_.FriendlyName; id=$_.InstanceId; kind='endpoint' }",
    "  } | ConvertTo-Json -Compress -Depth 3",
    "} else {",
    "  Get-CimInstance Win32_SoundDevice |",
    "    Select-Object -Property Name, DeviceID, Status |",
    "    ForEach-Object {",
    "      [PSCustomObject]@{ name=$_.Name; id=$_.DeviceID; status=$_.Status; kind='sound_device' }",
    "    } | ConvertTo-Json -Compress -Depth 3",
    "}",
  ].join("; ");
  try {
    const raw = await runPowerShell(ps);
    if (!raw) {
      return ok({ platform: "win32", devices: [], note: "no_audio_devices" });
    }
    return ok({ platform: "win32", devices: parseJsonArray(raw) });
  } catch (e) {
    return err(
      e instanceof Error ? e.message : String(e),
      "HostAudioProbeError",
    );
  }
}

async function listAudioDevices(): Promise<HostOpResult> {
  if (process.platform === "win32") {
    return listAudioDevicesWin();
  }
  return ok({
    platform: process.platform,
    devices: [],
    stub: true,
    note: "audio_device_probe_not_implemented_on_this_os",
  });
}

type AudioDeviceRow = { name?: string; id?: string; kind?: string; status?: string };

function asDeviceRows(value: Record<string, unknown>): AudioDeviceRow[] {
  const devices = value.devices;
  if (!Array.isArray(devices)) return [];
  return devices.filter(
    (d): d is AudioDeviceRow => !!d && typeof d === "object" && !Array.isArray(d),
  ) as AudioDeviceRow[];
}

/** Map PnP AudioEndpoint InstanceId → Core Audio device id for PolicyConfig. */
function toMmDeviceId(rawId: string): string | null {
  const id = rawId.trim();
  if (!id) return null;
  // Already a Core Audio id: {0.0.0.00000000}.{guid}
  if (/^\{0\.0\.[01]\.00000000\}\./i.test(id)) return id;
  const m = id.match(/\{0\.0\.[01]\.00000000\}\.\{[0-9a-fA-F-]+\}/i);
  return m ? m[0] : null;
}

function isPlaybackEndpointId(mmId: string): boolean {
  // Render = 0.0.0.*; Capture = 0.0.1.*
  return /\{0\.0\.0\.00000000\}\./i.test(mmId);
}

function matchAudioDevice(
  devices: AudioDeviceRow[],
  deviceId: string,
  deviceName: string,
): AudioDeviceRow | null {
  const idNeedle = deviceId.trim().toLowerCase();
  const nameNeedle = deviceName.trim().toLowerCase();
  for (const d of devices) {
    const id = String(d.id ?? "").trim();
    const name = String(d.name ?? "").trim();
    if (idNeedle && id.toLowerCase() === idNeedle) return d;
    if (idNeedle && toMmDeviceId(id)?.toLowerCase() === idNeedle) return d;
    if (nameNeedle && name.toLowerCase() === nameNeedle) return d;
  }
  // Partial id: accept full GUID suffix after the last "." only (not loose includes).
  if (idNeedle) {
    for (const d of devices) {
      const id = String(d.id ?? "").trim();
      const mm = toMmDeviceId(id);
      const guid = (mm ?? id).split(".").pop()?.toLowerCase() ?? "";
      if (guid && (guid === idNeedle || `{${idNeedle}}` === guid || idNeedle === guid.replace(/^\{|\}$/g, ""))) {
        return d;
      }
    }
  }
  return null;
}

async function setDefaultAudioWin(
  deviceId: string,
  deviceName: string,
): Promise<HostOpResult> {
  const listed = await listAudioDevicesWin();
  if (!listed.ok) return listed;
  const devices = asDeviceRows(listed.value);
  const matched = matchAudioDevice(devices, deviceId, deviceName);
  if (!matched) {
    return err(
      "device not found in host_audio_devices observation; refuse unknown device",
      "HostAudioDeviceUnknown",
    );
  }
  const mmId = toMmDeviceId(String(matched.id ?? ""));
  if (!mmId) {
    return err(
      `cannot map device id to Core Audio endpoint: ${String(matched.id ?? "")}`,
      "HostAudioDeviceIdError",
    );
  }
  if (!isPlaybackEndpointId(mmId)) {
    return err(
      "host_audio_set_default only supports playback (render) endpoints",
      "HostAudioNotPlayback",
    );
  }

  // Undocumented IPolicyConfig — no extra deps; fail honestly if COM rejects.
  const script = `
$ErrorActionPreference = 'Stop'
$mmId = '${mmId.replace(/'/g, "''")}'
$friendly = '${String(matched.name ?? "").replace(/'/g, "''")}'
if (-not ('AgentCore.PolicyConfig' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace AgentCore {
  [ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
  internal class PolicyConfigClient { }
  [Guid("F8679F50-850A-41CF-9C72-430F290290C8"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  internal interface IPolicyConfig {
    [PreserveSig] int GetMixFormat(string a, IntPtr b);
    [PreserveSig] int GetDeviceFormat(string a, int b, IntPtr c);
    [PreserveSig] int ResetDeviceFormat(string a);
    [PreserveSig] int SetDeviceFormat(string a, IntPtr b, IntPtr c);
    [PreserveSig] int GetProcessingPeriod(string a, int b, IntPtr c, IntPtr d);
    [PreserveSig] int SetProcessingPeriod(string a, IntPtr b);
    [PreserveSig] int GetShareMode(string a, IntPtr b);
    [PreserveSig] int SetShareMode(string a, IntPtr b);
    [PreserveSig] int GetPropertyValue(string a, IntPtr b, IntPtr c);
    [PreserveSig] int SetPropertyValue(string a, IntPtr b, IntPtr c);
    [PreserveSig] int SetDefaultEndpoint(
      [MarshalAs(UnmanagedType.LPWStr)] string deviceId, int role);
    [PreserveSig] int SetEndpointVisibility(string a, int b);
  }
  public static class PolicyConfig {
    public static int SetDefault(string deviceId) {
      var cfg = (IPolicyConfig)(object)new PolicyConfigClient();
      int hr = 0;
      for (int role = 0; role <= 2; role++) {
        int r = cfg.SetDefaultEndpoint(deviceId, role);
        if (r != 0) hr = r;
      }
      return hr;
    }
  }
}
'@
}
$hr = [AgentCore.PolicyConfig]::SetDefault($mmId)
if ($hr -ne 0) { throw "SetDefaultEndpoint failed HRESULT=$hr" }
[PSCustomObject]@{ set = $true; device_id = $mmId; name = $friendly } | ConvertTo-Json -Compress
`.trim();

  try {
    const raw = await runPowerShellEncoded(script, 20_000);
    if (!raw) {
      return ok({
        platform: "win32",
        set: true,
        device_id: mmId,
        name: matched.name ?? null,
      });
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return ok({ platform: "win32", ...parsed });
  } catch (e) {
    return err(
      e instanceof Error ? e.message : String(e),
      "HostAudioSetDefaultError",
    );
  }
}

async function setDefaultAudio(
  deviceId: string,
  deviceName: string,
): Promise<HostOpResult> {
  if (!deviceId.trim() && !deviceName.trim()) {
    return err("device_id or device_name is required");
  }
  if (process.platform === "win32") {
    return setDefaultAudioWin(deviceId, deviceName);
  }
  return err(
    `host_audio_set_default not implemented on ${process.platform}`,
    "HostAudioSetDefaultStub",
  );
}

async function restartServiceWin(service: string): Promise<HostOpResult> {
  // Restart-Service only — never arbitrary sc stop / start of non-allowlisted names.
  const ps = [
    "$ErrorActionPreference='Stop'",
    `$name = '${service.replace(/'/g, "''")}'`,
    "Restart-Service -Name $name -Force -ErrorAction Stop",
    "$svc = Get-Service -Name $name",
    "[PSCustomObject]@{ restarted = $true; service = $svc.Name; status = [string]$svc.Status } | ConvertTo-Json -Compress",
  ].join("; ");
  try {
    const raw = await runPowerShell(ps, 45_000);
    if (!raw) {
      return ok({ platform: "win32", restarted: true, service, status: "unknown" });
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return ok({ platform: "win32", ...parsed });
  } catch (e) {
    return err(
      e instanceof Error ? e.message : String(e),
      "HostServiceRestartError",
    );
  }
}

async function restartService(serviceRaw: string): Promise<HostOpResult> {
  const service = serviceRaw.trim();
  if (!service) return err("service is required");
  if (!SERVICE_RESTART_ALLOWLIST.has(service.toLowerCase())) {
    return err(
      `service not in allowlist: ${service} (only Audiosrv)`,
      "HostServiceNotAllowlisted",
    );
  }
  // Canonical SCM name.
  const canonical = "Audiosrv";
  if (process.platform === "win32") {
    return restartServiceWin(canonical);
  }
  return err(
    `host_service_restart not implemented on ${process.platform}`,
    "HostServiceRestartStub",
  );
}

async function hostStorageWin(): Promise<HostOpResult> {
  const ps = [
    "$ErrorActionPreference='Stop'",
    "Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" |",
    "  ForEach-Object {",
    "    [PSCustomObject]@{",
    "      device_id = $_.DeviceID",
    "      volume_name = $_.VolumeName",
    "      total_gb = [math]::Round(($_.Size / 1GB), 1)",
    "      free_gb = [math]::Round(($_.FreeSpace / 1GB), 1)",
    "      filesystem = $_.FileSystem",
    "    }",
    "  } | ConvertTo-Json -Compress -Depth 3",
  ].join("; ");
  try {
    const raw = await runPowerShell(ps);
    const volumes = raw ? parseJsonArray(raw) : [];
    return ok({
      platform: "win32",
      volumes,
      note: "fixed_local_volumes_only",
    });
  } catch (e) {
    return err(
      e instanceof Error ? e.message : String(e),
      "HostStorageProbeError",
    );
  }
}

async function hostStorage(): Promise<HostOpResult> {
  if (process.platform === "win32") {
    return hostStorageWin();
  }
  return ok({
    platform: process.platform,
    volumes: [],
    stub: true,
    note: "storage_probe_not_implemented_on_this_os",
  });
}

async function hostPowerWin(): Promise<HostOpResult> {
  const ps = [
    "$ErrorActionPreference='Stop'",
    "$batteries = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue |",
    "  ForEach-Object {",
    "    [PSCustomObject]@{",
    "      name = $_.Name",
    "      estimated_charge_remaining = $_.EstimatedChargeRemaining",
    "      battery_status = $_.BatteryStatus",
    "      estimated_run_time_min = $_.EstimatedRunTime",
    "    }",
    "  })",
    "$onAc = $batteries.Count -eq 0 -or ($batteries | Where-Object {",
    "  $_.battery_status -in @(2, 6, 7, 8, 9)",
    "} | Measure-Object).Count -gt 0",
    "[PSCustomObject]@{",
    "  on_ac = [bool]$onAc",
    "  batteries = $batteries",
    "  note = $(if ($batteries.Count -eq 0) { 'no_battery_or_desktop' } else { 'win32_battery' })",
    "} | ConvertTo-Json -Compress -Depth 4",
  ].join("; ");
  try {
    const raw = await runPowerShell(ps);
    if (!raw) {
      return ok({
        platform: "win32",
        on_ac: true,
        batteries: [],
        note: "no_battery_or_desktop",
      });
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return ok({ platform: "win32", ...parsed });
  } catch (e) {
    return err(
      e instanceof Error ? e.message : String(e),
      "HostPowerProbeError",
    );
  }
}

async function hostPower(): Promise<HostOpResult> {
  if (process.platform === "win32") {
    return hostPowerWin();
  }
  return ok({
    platform: process.platform,
    on_ac: null,
    batteries: [],
    stub: true,
    note: "power_probe_not_implemented_on_this_os",
  });
}

async function hostNetworkSummary(): Promise<HostOpResult> {
  // Local iface summary only — never port-scan or sniff.
  const ifaces = os.networkInterfaces();
  const adapters: Array<{
    name: string;
    addresses: Array<{ family: string; address: string }>;
  }> = [];
  for (const [name, addrs] of Object.entries(ifaces)) {
    if (!addrs) continue;
    const addresses = addrs
      .filter((a) => !a.internal)
      .map((a) => ({
        family: String(a.family),
        address: a.address,
      }));
    if (addresses.length === 0) continue;
    adapters.push({ name, addresses });
  }
  return ok({
    platform: process.platform,
    hostname: os.hostname(),
    adapters,
    note: "local_iface_summary_no_port_scan",
  });
}

async function hostAppsWin(): Promise<HostOpResult> {
  // Bounded Start Menu .lnk sample — not a full uninstall registry dump.
  const ps = [
    `$limit = ${APPS_SAMPLE_LIMIT}`,
    "$ErrorActionPreference='SilentlyContinue'",
    "$dirs = @(",
    "  \"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\",",
    "  \"$env:AppData\\Microsoft\\Windows\\Start Menu\\Programs\"",
    ")",
    "$names = New-Object System.Collections.Generic.HashSet[string]",
    "foreach ($d in $dirs) {",
    "  if (-not (Test-Path -LiteralPath $d)) { continue }",
    "  Get-ChildItem -LiteralPath $d -Filter '*.lnk' -Recurse -ErrorAction SilentlyContinue |",
    "    ForEach-Object { [void]$names.Add($_.BaseName) }",
    "}",
    "$sorted = $names | Sort-Object",
    "[PSCustomObject]@{",
    "  count = @($sorted).Count",
    "  sample = @($sorted | Select-Object -First $limit)",
    "  sample_limit = $limit",
    "  source = 'start_menu_lnk'",
    "  bounded = $true",
    "} | ConvertTo-Json -Compress -Depth 3",
  ].join("; ");
  try {
    const raw = await runPowerShell(ps, 20_000);
    if (!raw) {
      return ok({
        platform: "win32",
        count: 0,
        sample: [],
        sample_limit: APPS_SAMPLE_LIMIT,
        source: "start_menu_lnk",
        bounded: true,
        note: "no_start_menu_entries",
      });
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return ok({ platform: "win32", ...parsed });
  } catch (e) {
    return err(
      e instanceof Error ? e.message : String(e),
      "HostAppsProbeError",
    );
  }
}

async function hostApps(): Promise<HostOpResult> {
  if (process.platform === "win32") {
    return hostAppsWin();
  }
  // Honest stub — do not invent installed-app lists.
  return ok({
    platform: process.platform,
    count: 0,
    sample: [],
    sample_limit: APPS_SAMPLE_LIMIT,
    source: "stub",
    bounded: true,
    stub: true,
    note: "apps_probe_not_implemented_on_this_os",
  });
}

async function hostShell(
  command: string,
  timeoutSeconds: number,
): Promise<HostOpResult> {
  const cmd = command.trim();
  if (!cmd) {
    return err("command is required", "HostShellEmptyCommand");
  }
  const fuse = shellFuseBlocks(cmd);
  if (fuse) {
    return err(fuse, "HostShellFuse");
  }
  const cwd = os.homedir();
  const timeoutMs = timeoutSeconds * 1000;

  let file: string;
  let args: string[];
  if (process.platform === "win32") {
    file = "powershell.exe";
    args = ["-NoProfile", "-NonInteractive", "-Command", cmd];
  } else {
    const sh = (process.env.SHELL || "").trim() || "/bin/bash";
    file = sh;
    args = ["-lc", cmd];
  }

  return new Promise((resolve) => {
    const child = spawn(file, args, {
      cwd,
      windowsHide: true,
      env: process.env,
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try {
        child.kill("SIGKILL");
      } catch {
        /* ignore */
      }
      resolve(
        ok({
          timed_out: true,
          exit_code: null,
          stdout: truncateOut(stdout),
          stderr: truncateOut(stderr),
          cwd,
          note: `killed after ${timeoutSeconds}s`,
        }),
      );
    }, timeoutMs);

    child.stdout?.on("data", (chunk: Buffer | string) => {
      stdout += typeof chunk === "string" ? chunk : chunk.toString("utf8");
    });
    child.stderr?.on("data", (chunk: Buffer | string) => {
      stderr += typeof chunk === "string" ? chunk : chunk.toString("utf8");
    });
    child.on("error", (e) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(err(e.message || "host_shell spawn failed", "HostShellSpawnError"));
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(
        ok({
          timed_out: false,
          exit_code: code ?? null,
          stdout: truncateOut(stdout),
          stderr: truncateOut(stderr),
          cwd,
        }),
      );
    });
  });
}

async function openSettings(panel: string): Promise<HostOpResult> {
  if (!OPEN_SETTINGS_PANELS.has(panel)) {
    return err(`unsupported panel: ${panel}`);
  }
  if (process.platform === "win32") {
    const uri = WIN_SETTINGS_URI[panel];
    if (!uri) return err(`unsupported panel: ${panel}`);
    await shell.openExternal(uri);
    return ok({ opened: true, panel, uri });
  }
  if (process.platform === "darwin") {
    const uri = MAC_SETTINGS_URI[panel];
    if (!uri) {
      return ok({
        opened: false,
        panel,
        stub: true,
        note: "open_settings_panel_stub_on_mac",
      });
    }
    try {
      await shell.openExternal(uri);
      return ok({ opened: true, panel, uri });
    } catch {
      return ok({
        opened: false,
        panel,
        stub: true,
        note: "open_settings_stub_on_mac",
      });
    }
  }
  return ok({
    opened: false,
    panel,
    stub: true,
    note: "open_settings_not_implemented_on_this_os",
  });
}

export async function runHostOp(input: HostOpInput): Promise<HostOpResult> {
  const op = String(input.op || "").trim();
  const args = input.args ?? {};
  switch (op) {
    case "host_ping":
      return hostPing();
    case "host_info":
      return hostInfo();
    case "host_audio_devices":
      return listAudioDevices();
    case "host_storage":
      return hostStorage();
    case "host_power":
      return hostPower();
    case "host_network_summary":
      return hostNetworkSummary();
    case "host_apps":
      return hostApps();
    case "host_shell": {
      const command = String(args.command ?? "");
      const timeoutSeconds = clampShellTimeout(args.timeout_seconds);
      return hostShell(command, timeoutSeconds);
    }
    case "host_open_settings": {
      const panel = String(args.panel ?? "").trim().toLowerCase();
      if (!panel) return err("panel is required");
      return openSettings(panel);
    }
    case "host_audio_set_default": {
      const deviceId = String(args.device_id ?? "").trim();
      const deviceName = String(args.device_name ?? "").trim();
      return setDefaultAudio(deviceId, deviceName);
    }
    case "host_service_restart": {
      const service = String(args.service ?? "").trim();
      return restartService(service);
    }
    default:
      return err(`unknown host op: ${op}`);
  }
}

export function registerHostIpc(): void {
  ipcMain.handle(HOST_CHANNELS.runOp, async (_event, raw: unknown) => {
    if (!raw || typeof raw !== "object") {
      return err("invalid host op input");
    }
    const o = raw as Record<string, unknown>;
    const op = typeof o.op === "string" ? o.op : "";
    const args =
      o.args && typeof o.args === "object" && !Array.isArray(o.args)
        ? (o.args as Record<string, unknown>)
        : {};
    return runHostOp({ op, args });
  });
}
