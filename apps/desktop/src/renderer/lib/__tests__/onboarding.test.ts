import {
  type DraftEmptyInput,
  STARTER_TASK_CHIPS,
  hasSeenTip,
  markTipSeen,
  resolveDraftEmptyKind,
  shouldCenterDraftComposer,
  shouldShowTip,
} from "@/lib/onboarding";
import {
  __clearMemoryUiStorageForTests,
  __setUiStorageBackendForTests,
} from "@/lib/uiStorage";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const memory = new Map<string, string>();

beforeEach(() => {
  memory.clear();
  __setUiStorageBackendForTests({
    getItem: (k) => memory.get(k) ?? null,
    setItem: (k, v) => {
      memory.set(k, v);
    },
    removeItem: (k) => {
      memory.delete(k);
    },
    keys: () => [...memory.keys()],
  });
});

afterEach(() => {
  __setUiStorageBackendForTests(null);
  __clearMemoryUiStorageForTests();
});

describe("resolveDraftEmptyKind", () => {
  const base: DraftEmptyInput = { conversationCount: 0 };

  it("starter_chips for a keyless brand-new user (no access gate)", () => {
    expect(resolveDraftEmptyKind(base)).toBe("starter_chips");
  });

  it("returning once the user has any conversation", () => {
    expect(resolveDraftEmptyKind({ conversationCount: 3 })).toBe("returning");
  });
});

describe("shouldCenterDraftComposer", () => {
  it("centers an empty draft (keyless included — no access gate)", () => {
    expect(
      shouldCenterDraftComposer({
        isDraft: true,
        hasMessages: false,
      }),
    ).toBe(true);
  });

  it("never centers once messages exist", () => {
    expect(
      shouldCenterDraftComposer({
        isDraft: true,
        hasMessages: true,
      }),
    ).toBe(false);
  });

  it("never centers a persisted conversation still loading history", () => {
    // 回归护栏：切换到已有对话会先出现「有 conversationId(isDraft=false) 但消息尚未
    // 异步加载完」的空窗口。若在此居中，输入框会「弹到中间、加载完再飞回底栏」= 跳动。
    // 未知 messageCount（列表未命中）的已落库对话一律底栏。
    expect(
      shouldCenterDraftComposer({
        isDraft: false,
        hasMessages: false,
      }),
    ).toBe(false);
  });

  it("centers a persisted conversation known to be empty (demo-tape 绑定空会话)", () => {
    // 演示磁带 prepare 建的是已落库(isDraft=false)、0 消息的空会话；回放开始时应显示
    // 真实产品的居中欢迎卡片，而非直接底栏。messageCount===0 是「确定为空」的可靠信号。
    expect(
      shouldCenterDraftComposer({
        isDraft: false,
        hasMessages: false,
        knownEmptyPersisted: true,
      }),
    ).toBe(true);
  });
});

describe("starter chips", () => {
  it("ships exactly three Chinese multi-agent starter tasks", () => {
    expect(STARTER_TASK_CHIPS).toHaveLength(3);
    for (const chip of STARTER_TASK_CHIPS) {
      expect(chip.length).toBeGreaterThan(10);
      expect(/[\u4e00-\u9fff]/.test(chip)).toBe(true);
    }
  });
});

describe("contextual tip seen", () => {
  it("shows each tip only once until marked", () => {
    expect(shouldShowTip("inline_team_graph")).toBe(true);
    expect(hasSeenTip("inline_team_graph")).toBe(false);
    markTipSeen("inline_team_graph");
    expect(shouldShowTip("inline_team_graph")).toBe(false);
    expect(hasSeenTip("inline_team_graph")).toBe(true);
  });
});
