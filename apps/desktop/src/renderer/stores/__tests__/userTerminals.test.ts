import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUserTerminalStore } from "../userTerminals";

describe("useUserTerminalStore", () => {
  beforeEach(() => {
    useUserTerminalStore.setState({
      byConversation: {},
      selectedId: null,
      subscribed: true,
    });
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

  it("clearConversation drops only that conversation", () => {
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

    useUserTerminalStore.getState().clearConversation("c1");
    expect(useUserTerminalStore.getState().sessionsFor("c1")).toHaveLength(0);
    expect(useUserTerminalStore.getState().sessionsFor("c2")).toHaveLength(1);
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
