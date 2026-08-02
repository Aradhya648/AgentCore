import { afterEach, describe, expect, it } from "vitest";
import {
  __resetQueuedTurnsForTests,
  clearQueuedTurns,
  listQueuedTurns,
  removeQueuedTurn,
  upsertQueuedTurn,
} from "../queuedTurns";

afterEach(() => {
  __resetQueuedTurnsForTests();
});

describe("queuedTurns store", () => {
  it("多项按 position 排序，同 queueId upsert 不丢其它项", () => {
    upsertQueuedTurn({
      queueId: "q1",
      conversationId: "c1",
      turnId: "t1",
      content: "a",
      position: 1,
      queueDepth: 2,
    });
    upsertQueuedTurn({
      queueId: "q2",
      conversationId: "c1",
      turnId: "t2",
      content: "b",
      position: 2,
      queueDepth: 2,
    });
    upsertQueuedTurn({
      queueId: "q1",
      conversationId: "c1",
      turnId: "t1",
      content: "a",
      position: 1,
      queueDepth: 3,
    });

    const list = listQueuedTurns("c1");
    expect(list.map((e) => e.queueId)).toEqual(["q1", "q2"]);
    expect(list[0]?.queueDepth).toBe(3);
  });

  it("remove 按 queue_id 只清一项", () => {
    upsertQueuedTurn({
      queueId: "q1",
      conversationId: "c1",
      turnId: "t1",
      content: "a",
      position: 1,
      queueDepth: 2,
    });
    upsertQueuedTurn({
      queueId: "q2",
      conversationId: "c1",
      turnId: "t2",
      content: "b",
      position: 2,
      queueDepth: 2,
    });
    const hit = removeQueuedTurn("c1", "q1");
    expect(hit?.turnId).toBe("t1");
    expect(listQueuedTurns("c1").map((e) => e.queueId)).toEqual(["q2"]);
  });

  it("clearConversation 清空该对话", () => {
    upsertQueuedTurn({
      queueId: "q1",
      conversationId: "c1",
      turnId: "t1",
      content: "a",
      position: 1,
      queueDepth: 1,
    });
    upsertQueuedTurn({
      queueId: "q9",
      conversationId: "c2",
      turnId: "t9",
      content: "x",
      position: 1,
      queueDepth: 1,
    });
    clearQueuedTurns("c1");
    expect(listQueuedTurns("c1")).toEqual([]);
    expect(listQueuedTurns("c2")).toHaveLength(1);
  });
});
