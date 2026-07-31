import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  countBusyPtySessions,
  isPtySessionBusy,
  useUserTerminalStore,
} from "../userTerminals";

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifyActionError: vi.fn(),
}));

import { notifyActionError, notifyError } from "@/lib/toast";

const notifyErrorMock = vi.mocked(notifyError);
const notifyActionErrorMock = vi.mocked(notifyActionError);

function runningSession(sessionId: string, conversationId: string) {
  return {
    session_id: sessionId,
    conversation_id: conversationId,
    name: "用户终端 #1",
    shell: "bash",
    index: 1,
    status: "running" as const,
    started_at: "2026-01-01T00:00:00.000Z",
    output: "hi",
  };
}

describe("isPtySessionBusy / countBusyPtySessions", () => {
  it("treats running as busy and exited as idle", () => {
    expect(isPtySessionBusy({ status: "running" })).toBe(true);
    expect(isPtySessionBusy({ status: "exited" })).toBe(false);
    expect(
      countBusyPtySessions([
        { status: "running" },
        { status: "exited" },
        { status: "running" },
      ]),
    ).toBe(2);
  });
});

describe("useUserTerminalStore", () => {
  beforeEach(() => {
    useUserTerminalStore.setState({
      byConversation: {},
      selectedId: null,
      subscribed: true,
    });
    notifyErrorMock.mockReset();
    notifyActionErrorMock.mockReset();
    vi.unstubAllGlobals();
  });

  it("returns a stable empty array when conversation is absent", () => {
    const store = useUserTerminalStore.getState();
    const a = store.sessionsFor("missing");
    const b = store.sessionsFor("missing");
    const c = store.sessionsFor(null);
    expect(a).toEqual([]);
    expect(a).toBe(b);
    expect(a).toBe(c);
  });

  it("applyEvent started + data + exited", () => {
    const store = useUserTerminalStore.getState();
    store.applyEvent({
      type: "started",
      session_id: "s1",
      conversation_id: "c1",
      item: {
        session_id: "s1",
        conversation_id: "c1",
        name: "用户终端 #1",
        shell: "powershell.exe",
        index: 1,
        status: "running",
        started_at: "2026-01-01T00:00:00.000Z",
      },
    });
    expect(store.sessionsFor("c1")).toHaveLength(1);

    useUserTerminalStore.getState().applyEvent({
      type: "data",
      session_id: "s1",
      conversation_id: "c1",
      chunk: "hello",
    });
    expect(useUserTerminalStore.getState().sessionsFor("c1")[0]?.output).toBe(
      "hello",
    );

    useUserTerminalStore.getState().applyEvent({
      type: "exited",
      session_id: "s1",
      conversation_id: "c1",
      exit_code: 0,
    });
    expect(useUserTerminalStore.getState().sessionsFor("c1")[0]?.status).toBe(
      "exited",
    );
  });

  it("clearConversation drops only that conversation", async () => {
    useUserTerminalStore.getState().applyEvent({
      type: "started",
      session_id: "s1",
      conversation_id: "c1",
      item: {
        session_id: "s1",
        conversation_id: "c1",
        name: "用户终端 #1",
        shell: "bash",
        index: 1,
        status: "running",
        started_at: "2026-01-01T00:00:00.000Z",
      },
    });
    useUserTerminalStore.getState().applyEvent({
      type: "started",
      session_id: "s2",
      conversation_id: "c2",
      item: {
        session_id: "s2",
        conversation_id: "c2",
        name: "用户终端 #1",
        shell: "bash",
        index: 1,
        status: "running",
        started_at: "2026-01-01T00:00:00.000Z",
      },
    });

    await useUserTerminalStore.getState().killConversation("c1");
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(0);
    expect(useUserTerminalStore.getState().sessionsFor("c2")).toHaveLength(1);
  });

  it("killSession removes the session only after IPC succeeds", async () => {
    let resolveKill!: (v: {
      ok: true;
      value: {
        session_id: string;
        conversation_id: string;
        name: string;
        shell: string;
        index: number;
        status: "exited";
        started_at: string;
        exit_code: number;
      };
    }) => void;
    const kill = vi.fn(
      () =>
        new Promise<Parameters<typeof resolveKill>[0]>((r) => {
          resolveKill = r;
        }),
    );
    vi.stubGlobal("window", { ptyApi: { kill } });

    useUserTerminalStore.setState({
      byConversation: { c1: [runningSession("s1", "c1")] },
      selectedId: "s1",
      subscribed: true,
    });

    const pending = useUserTerminalStore.getState().killSession("s1");
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(1);
    expect(useUserTerminalStore.getState().selectedId).toBe("s1");

    resolveKill({
      ok: true,
      value: {
        session_id: "s1",
        conversation_id: "c1",
        name: "用户终端 #1",
        shell: "bash",
        index: 1,
        status: "exited",
        started_at: "2026-01-01T00:00:00.000Z",
        exit_code: -1,
      },
    });
    await expect(pending).resolves.toBe(true);
    expect(kill).toHaveBeenCalledWith({ session_id: "s1" });
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(0);
    expect(useUserTerminalStore.getState().selectedId).toBeNull();
  });

  it("killSession keeps the session and toasts when IPC returns ok:false", async () => {
    const kill = vi.fn(async () => ({
      ok: false as const,
      error: { kind: "WorkspaceIOError", detail: "会话不存在或已清理" },
    }));
    vi.stubGlobal("window", { ptyApi: { kill } });

    useUserTerminalStore.setState({
      byConversation: { c1: [runningSession("s1", "c1")] },
      selectedId: "s1",
      subscribed: true,
    });

    await expect(
      useUserTerminalStore.getState().killSession("s1"),
    ).resolves.toBe(false);
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(1);
    expect(useUserTerminalStore.getState().selectedId).toBe("s1");
    expect(notifyErrorMock).toHaveBeenCalled();
  });

  it("killConversation keeps sessions and toasts when IPC throws", async () => {
    const killConversation = vi.fn(async () => {
      throw new Error("ipc down");
    });
    vi.stubGlobal("window", { ptyApi: { killConversation } });

    useUserTerminalStore.setState({
      byConversation: {
        c1: [
          runningSession("s1", "c1"),
          {
            ...runningSession("s2", "c1"),
            session_id: "s2",
            index: 2,
            name: "用户终端 #2",
          },
        ],
      },
      selectedId: "s1",
      subscribed: true,
    });

    await expect(
      useUserTerminalStore.getState().killConversation("c1"),
    ).resolves.toBe(false);
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(2);
    expect(notifyActionErrorMock).toHaveBeenCalledWith(
      "关闭终端失败",
      expect.any(Error),
    );
  });

  it("killConversation clears UI after IPC resolves", async () => {
    const killConversation = vi.fn(async () => undefined);
    vi.stubGlobal("window", { ptyApi: { killConversation } });

    useUserTerminalStore.setState({
      byConversation: { c1: [runningSession("s1", "c1")] },
      selectedId: "s1",
      subscribed: true,
    });

    await expect(
      useUserTerminalStore.getState().killConversation("c1"),
    ).resolves.toBe(true);
    expect(killConversation).toHaveBeenCalledWith({ conversation_id: "c1" });
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(0);
  });

  it("loadOutput hydrates raw ANSI from ptyApi.read", async () => {
    const read = vi.fn(async () => ({
      ok: true as const,
      value: {
        session_id: "s1",
        status: "running" as const,
        output: "\u001b[32mready\u001b[0m",
      },
    }));
    vi.stubGlobal("window", { ptyApi: { read } });

    useUserTerminalStore.setState({
      byConversation: {
        c1: [
          {
            session_id: "s1",
            conversation_id: "c1",
            name: "用户终端 #1",
            shell: "bash",
            index: 1,
            status: "running",
            started_at: "2026-01-01T00:00:00.000Z",
            output: "",
          },
        ],
      },
      selectedId: "s1",
      subscribed: true,
    });

    await useUserTerminalStore.getState().loadOutput("s1");
    expect(read).toHaveBeenCalledWith({ session_id: "s1" });
    expect(useUserTerminalStore.getState().sessionsFor("c1")[0]?.output).toBe(
      "\u001b[32mready\u001b[0m",
    );
  });
});
