import { describe, expect, it } from "vitest";
import {
  receivedContextForList,
  selectRunTaskSection,
} from "../runTaskSection";

describe("selectRunTaskSection", () => {
  it("cold-start keeps run.task as 「任务」and promotes wire task for list dedupe", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: null,
        task: "开场立论全文",
        receivedContext: [
          {
            channel: "task",
            heading: "第 1 轮任务",
            body: "wire 任务（并入任务区、列表去重）",
          },
        ],
      }),
    ).toEqual({
      title: "任务",
      body: "开场立论全文",
      promotedTask: true,
    });
  });

  it("cold-start without a task block does not promote", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: null,
        task: "开场立论全文",
        receivedContext: [
          { channel: "request", heading: "原始请求", body: "…" },
        ],
      }),
    ).toEqual({
      title: "任务",
      body: "开场立论全文",
      promotedTask: false,
    });
  });

  it("revision runs prefer the task block heading + body", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: "run-1",
        task: "开场立论全文",
        receivedContext: [
          {
            channel: "opponent",
            heading: "对方论点",
            body: "…",
          },
          {
            channel: "task",
            heading: "结辩环节",
            body: "请归纳本方胜局，不添新论据。",
          },
        ],
      }),
    ).toEqual({
      title: "结辩环节",
      body: "请归纳本方胜局，不添新论据。",
      promotedTask: true,
    });
  });

  it("falls back to round_focus when no task block (legacy vectors)", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: "run-1",
        task: "开场立论全文",
        receivedContext: [
          {
            channel: "round_focus",
            heading: "本轮焦点",
            body: "聚焦争议点 X",
          },
        ],
      }),
    ).toEqual({
      title: "本轮焦点",
      body: "聚焦争议点 X",
      promotedTask: false,
    });
  });

  it("falls back to run.task when neither task nor round_focus exists", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: "run-1",
        task: "开场立论全文",
        receivedContext: [{ channel: "closing", heading: "结辩", body: "…" }],
      }),
    ).toEqual({
      title: "任务",
      body: "开场立论全文",
      promotedTask: false,
    });
  });

  it("blank task heading falls back to 「任务」", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: "run-1",
        task: "旧",
        receivedContext: [{ channel: "task", heading: "  ", body: "新指令" }],
      }),
    ).toEqual({
      title: "任务",
      body: "新指令",
      promotedTask: true,
    });
  });

  it("prefers task over coexisting round_focus", () => {
    expect(
      selectRunTaskSection({
        continuesRunId: "run-1",
        task: "旧",
        receivedContext: [
          { channel: "round_focus", heading: "本轮焦点", body: "焦点" },
          { channel: "task", heading: "质询环节", body: "请回答质询" },
        ],
      }).title,
    ).toBe("质询环节");
  });
});

describe("receivedContextForList", () => {
  it("drops task blocks only when promoted", () => {
    const blocks = [
      { channel: "opponent", body: "a" },
      { channel: "task", body: "b" },
      { channel: "closing", body: "c" },
    ];
    expect(receivedContextForList(blocks, false)).toEqual(blocks);
    expect(receivedContextForList(blocks, true)).toEqual([
      { channel: "opponent", body: "a" },
      { channel: "closing", body: "c" },
    ]);
  });

  it("cold-start promote+filter removes task from the context list", () => {
    const section = selectRunTaskSection({
      continuesRunId: null,
      task: "面板任务",
      receivedContext: [
        { channel: "request", heading: "原始请求", body: "目标" },
        { channel: "task", heading: "你的任务", body: "面板任务" },
        { channel: "dependency", heading: "前置", body: "上游" },
      ],
    });
    expect(section.promotedTask).toBe(true);
    expect(
      receivedContextForList(
        [
          { channel: "request" },
          { channel: "task" },
          { channel: "dependency" },
        ],
        section.promotedTask,
      ).map((b) => b.channel),
    ).toEqual(["request", "dependency"]);
  });
});
