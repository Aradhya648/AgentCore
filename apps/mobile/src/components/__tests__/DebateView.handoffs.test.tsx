// @vitest-environment jsdom
/**
 * 决策简报「留给你的」handoffs：按 kind 异质形态（问句卡 / 查证行 / 脚注）+ 可选 composer 预填。
 */

import { DebateView } from "@/components/DebateView";
import type { DebateResultPayload } from "@agentcore/contract-types";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

function debateWithHandoffs(): DebateResultPayload {
  return {
    execution_id: "exec-1",
    moderator_run_id: "moderator",
    form: "debate",
    motion: "是否采用方案 A",
    stop_reason: "converged",
    narrative_first: false,
    sides: [
      {
        key: "pro",
        name: "正方",
        stance: "pro",
        model: undefined,
        is_subject: false,
      },
      {
        key: "con",
        name: "反方",
        stance: "con",
        model: undefined,
        is_subject: false,
      },
    ],
    rounds: [],
    brief: {
      leaning: "倾向正方",
      confidence: "high",
      decisive: "证据更扎实",
      crux: "成本可否接受",
      recommendation: "先做试点",
      strongest_points: { pro: "ROI 清晰", con: "风险未清" },
      handoffs: [
        { kind: "value", text: "要不要牺牲速度" },
        { kind: "fact", text: "实际成本" },
        { kind: "question", text: "试点范围" },
        { kind: "unknown", text: "坏 kind 归脚注" },
      ],
    },
  } as DebateResultPayload;
}

describe("DebateView HandoffsBlock", () => {
  it("按形态呈现 value/fact/question，旧分类名词退场", () => {
    render(<DebateView debate={debateWithHandoffs()} />);

    expect(screen.getByText("留给你的")).toBeTruthy();
    expect(screen.getByText(/要不要牺牲速度/)).toBeTruthy();
    expect(screen.getByText("实际成本")).toBeTruthy();
    expect(screen.getByText(/只能等的：试点范围；坏 kind 归脚注/)).toBeTruthy();
    expect(screen.queryByText(/需你定夺/)).toBeNull();
    expect(screen.queryByText("事实分歧")).toBeNull();
    expect(screen.queryByText("待解问题")).toBeNull();
    // 无 onFill → 不展示行动按钮
    expect(screen.queryByRole("button", { name: "回复拍板" })).toBeNull();
    expect(screen.queryByRole("button", { name: "派查证" })).toBeNull();
  });

  it("有 onFill 时行动按钮预填 composer", () => {
    const onFill = vi.fn();
    render(<DebateView debate={debateWithHandoffs()} onFill={onFill} />);

    fireEvent.click(screen.getByRole("button", { name: "回复拍板" }));
    expect(onFill).toHaveBeenCalledWith("关于「要不要牺牲速度」，我的取舍是：");

    fireEvent.click(screen.getByRole("button", { name: "派查证" }));
    expect(onFill).toHaveBeenCalledWith("帮我查证：实际成本");
  });
});
