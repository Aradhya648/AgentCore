import { beforeEach, describe, expect, it } from "vitest";
import {
  type BackgroundProcessView,
  useBackgroundProcessStore,
} from "../backgroundProcesses";

const store = () => useBackgroundProcessStore.getState();

const proc = (
  over: Partial<BackgroundProcessView> = {},
): BackgroundProcessView => ({
  process_id: "p1",
  conversation_id: "c1",
  command: "pnpm dev",
  status: "running",
  started_at: new Date().toISOString(),
  output: "",
  ...over,
});

beforeEach(() => {
  useBackgroundProcessStore.setState({
    byConversation: {},
    selectedId: null,
    subscribed: true, // skip real IPC subscribe in unit tests
  });
});

describe("showTabFor / processesFor", () => {
  it("hides tab when conversation has no processes", () => {
    expect(store().showTabFor("c1")).toBe(false);
    expect(store().showTabFor(null)).toBe(false);
  });

  it("returns a stable empty array when conversation is absent", () => {
    const a = store().processesFor("missing");
    const b = store().processesFor("missing");
    const c = store().processesFor(null);
    expect(a).toEqual([]);
    expect(a).toBe(b);
    expect(a).toBe(c);
  });

  it("shows tab once a process is recorded (including exited)", () => {
    store().applyEvent({
      type: "started",
      process_id: "p1",
      conversation_id: "c1",
      item: {
        process_id: "p1",
        command: "pnpm dev",
        status: "running",
        started_at: new Date().toISOString(),
      },
    });
    expect(store().showTabFor("c1")).toBe(true);
    store().applyEvent({
      type: "exited",
      process_id: "p1",
      conversation_id: "c1",
      exit_code: 0,
    });
    expect(store().showTabFor("c1")).toBe(true);
    expect(store().processesFor("c1")[0]?.status).toBe("exited");
  });
});

describe("applyEvent output", () => {
  it("appends stripped chunks to the matching process", () => {
    useBackgroundProcessStore.setState({
      byConversation: { c1: [proc()] },
      selectedId: "p1",
      subscribed: true,
    });
    store().applyEvent({
      type: "output",
      process_id: "p1",
      conversation_id: "c1",
      chunk: "\u001b[32mready\u001b[0m\n",
    });
    expect(store().processesFor("c1")[0]?.output).toBe("ready\n");
  });
});
