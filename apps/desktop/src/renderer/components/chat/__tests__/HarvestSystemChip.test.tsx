// @vitest-environment jsdom
import { MessageBubble } from "@/components/chat/message-bubble";
import {
  EXECUTION_HARVEST_ORIGIN,
  isExecutionHarvestMessage,
} from "@/lib/executionHarvest";
import type { Message } from "@/stores/conversation";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

// jsdom 缺 Element.prototype.scrollIntoView；MessageBubble focus 效应会调它。
beforeAll(() => {
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  cleanup();
});

function userMsg(content: string, origin?: string | null): Message {
  return {
    id: "u-harvest",
    role: "user",
    content,
    createdAt: "2026-01-01T00:00:00Z",
    executionId: null,
    isStreaming: false,
    ...(origin != null ? { origin } : {}),
  };
}

describe("execution_harvest 隐藏合成行", () => {
  it("isExecutionHarvestMessage：origin 或【系统收口】前缀", () => {
    expect(
      isExecutionHarvestMessage(userMsg("hi", EXECUTION_HARVEST_ORIGIN)),
    ).toBe(true);
    expect(
      isExecutionHarvestMessage(
        userMsg("【系统收口】后台团队任务已全部完成。请综合…"),
      ),
    ).toBe(true);
    expect(isExecutionHarvestMessage(userMsg("普通提问"))).toBe(false);
  });

  it("MessageBubble：harvest 不渲染芯片也不走用户气泡", () => {
    const { container } = render(
      <MessageBubble
        message={userMsg(
          "【系统收口】后台团队任务已全部完成。请综合队员产出。",
        )}
      />,
    );
    expect(container.childElementCount).toBe(0);
    expect(screen.queryByTestId("harvest-system-chip")).toBeNull();
    expect(screen.queryByText(/请综合队员产出/)).toBeNull();
  });
});
