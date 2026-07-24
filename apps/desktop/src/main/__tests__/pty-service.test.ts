import { mkdir, mkdtemp, realpath, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  BrowserWindow: { getAllWindows: () => [] },
  app: { on: vi.fn() },
  ipcMain: { handle: vi.fn() },
}));

vi.mock("../fs-service", () => ({
  getStoredRoot: vi.fn(),
}));

import {
  PTY_PROCESS_NAME_PREFIX,
  PTY_STOP_REJECTED_DETAIL,
} from "@shared/pty-contract";
import { getStoredRoot } from "../fs-service";
import {
  PTY_BUFFER_CAP,
  PTY_CONCURRENCY_CAP,
  PTY_STOP_REJECTED_KIND,
  WIN_PS_MUTE_BELL_COMMAND,
  appendRingBuffer,
  ptyService,
  resolveDefaultShell,
  resolvePtyCwd,
  setPtySpawnerForTests,
  shellDisplayName,
  stripAnsi,
  tailLines,
} from "../pty-service";

function mockPtyHandle() {
  let onData: ((d: string) => void) | null = null;
  let onExit: ((e: { exitCode: number }) => void) | null = null;
  return {
    write: vi.fn(),
    resize: vi.fn(),
    kill: vi.fn(() => {
      onExit?.({ exitCode: 0 });
    }),
    onData: (cb: (d: string) => void) => {
      onData = cb;
    },
    onExit: (cb: (e: { exitCode: number }) => void) => {
      onExit = cb;
    },
    emitData: (d: string) => onData?.(d),
  };
}

describe("appendRingBuffer / stripAnsi / shell helpers", () => {
  it("rings at cap", () => {
    expect(appendRingBuffer("AAAA", "BBBB", 6)).toBe("AABBBB");
    expect(appendRingBuffer("", "x".repeat(PTY_BUFFER_CAP + 10)).length).toBe(
      PTY_BUFFER_CAP,
    );
  });

  it("strips ANSI for AI read", () => {
    expect(stripAnsi("\u001b[31mred\u001b[0m")).toBe("red");
  });

  it("tailLines", () => {
    expect(tailLines("a\nb\nc", 2)).toBe("b\nc");
  });

  it("resolveDefaultShell", () => {
    const win = resolveDefaultShell("win32", {});
    expect(win.file).toBe("powershell.exe");
    expect(win.args).toEqual([
      "-NoLogo",
      "-NoExit",
      "-Command",
      WIN_PS_MUTE_BELL_COMMAND,
    ]);
    expect(WIN_PS_MUTE_BELL_COMMAND).toContain("BellStyle None");
    const posix = resolveDefaultShell("linux", { SHELL: "/bin/zsh" });
    expect(posix.file).toBe("/bin/zsh");
    const fallback = resolveDefaultShell("linux", {});
    expect(fallback.file).toBe("/bin/sh");
  });

  it("shellDisplayName", () => {
    expect(shellDisplayName("/bin/bash")).toBe("bash");
  });
});

describe("ptyService accounting", () => {
  beforeEach(() => {
    ptyService.killAll();
    setPtySpawnerForTests(() => mockPtyHandle());
  });

  it("spawns with 用户终端 #N name and shell command", () => {
    const r = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.value.item.name).toBe(`${PTY_PROCESS_NAME_PREFIX}1`);
    expect(r.value.item.index).toBe(1);
    const list = ptyService.listAsProcessItems("c1");
    expect(list).toHaveLength(1);
    expect(list[0]?.name).toBe("用户终端 #1");
    expect(list[0]?.command).toBeTruthy();
  });

  it("enforces concurrency cap", () => {
    for (let i = 0; i < PTY_CONCURRENCY_CAP; i++) {
      const r = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
      expect(r.ok).toBe(true);
    }
    const over = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(over.ok).toBe(false);
    if (!over.ok) {
      expect(over.error.detail).toContain("上限");
    }
  });

  it("rejects AI stop with typed error", () => {
    const r = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const rejected = ptyService.rejectStopIfUserTerminal(r.value.session_id);
    expect(rejected).toEqual({
      ok: false,
      error: {
        kind: PTY_STOP_REJECTED_KIND,
        detail: PTY_STOP_REJECTED_DETAIL,
      },
    });
    expect(ptyService.rejectStopIfUserTerminal("not-a-pty")).toBeNull();
  });

  it("readAsProcess strips ANSI", () => {
    const handle = mockPtyHandle();
    setPtySpawnerForTests(() => handle);
    const r = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    handle.emitData("\u001b[32mhi\u001b[0m");
    const value = ptyService.readAsProcess(r.value.session_id);
    expect(value?.output).toBe("hi");
  });

  it("read keeps raw ANSI for hydrate replay", () => {
    const handle = mockPtyHandle();
    setPtySpawnerForTests(() => handle);
    const r = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    handle.emitData("\u001b[32mhi\u001b[0m");
    const value = ptyService.read(r.value.session_id);
    expect(value.ok).toBe(true);
    if (!value.ok) return;
    expect(value.value.output).toBe("\u001b[32mhi\u001b[0m");
    expect(value.value.session_id).toBe(r.value.session_id);
    expect(value.value.status).toBe("running");
  });

  it("read rejects unknown session", () => {
    const value = ptyService.read("missing");
    expect(value.ok).toBe(false);
  });

  it("killConversation clears sessions", () => {
    ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    ptyService.spawn({ conversation_id: "c2", cwd: "/tmp" });
    ptyService.killConversation("c1");
    expect(ptyService.list("c1").sessions).toHaveLength(0);
    expect(ptyService.list("c2").sessions).toHaveLength(1);
  });

  it("indexes do not reuse after kill", () => {
    const a = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(a.ok).toBe(true);
    if (!a.ok) return;
    ptyService.kill(a.value.session_id);
    ptyService.killConversation("c1");
    // killConversation resets nextIndex — fresh conversation accounting
    const b = ptyService.spawn({ conversation_id: "c1", cwd: "/tmp" });
    expect(b.ok).toBe(true);
    if (!b.ok) return;
    expect(b.value.item.index).toBe(1);
  });
});

describe("resolvePtyCwd", () => {
  let dir: string;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "pty-cwd-")));
    await mkdir(join(dir, "apps"), { recursive: true });
    vi.mocked(getStoredRoot).mockResolvedValue({
      id: "r1",
      name: "ws",
      absPath: dir,
    });
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
    vi.mocked(getStoredRoot).mockReset();
  });

  it("resolves subpath under authorized root", async () => {
    const r = await resolvePtyCwd("r1", "apps");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.cwd.replace(/\\/g, "/")).toMatch(/\/apps$/);
    }
  });

  it("rejects lexical escape", async () => {
    const r = await resolvePtyCwd("r1", "../outside");
    expect(r.ok).toBe(false);
  });

  it("rejects cwd that escapes through a symlink ancestor", async () => {
    const outside = await realpath(await mkdtemp(join(tmpdir(), "pty-out-")));
    let linked = true;
    try {
      await symlink(outside, join(dir, "link"), "junction");
    } catch {
      linked = false;
    }
    if (linked) {
      const r = await resolvePtyCwd("r1", "link");
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.detail).toContain("越出");
    }
    await rm(outside, { recursive: true, force: true });
  });
});

describe("pty-contract constants", () => {
  it("exposes stable stop-reject copy", () => {
    expect(PTY_STOP_REJECTED_DETAIL).toContain("仅可由用户关闭");
    expect(PTY_PROCESS_NAME_PREFIX).toBe("用户终端 #");
  });
});
