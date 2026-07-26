// @vitest-environment jsdom
/**
 * Render + interaction tests for the mobile 离线恢复 card (结构化挂起 2b / 挂起即收口 ②).
 *
 * ResumeCard is the SINGLE durable surface for a turn that paused at a checkpoint and then
 * lost its live stream — surfaced on reopen, and (under ②, post flag-on) the moment a live
 * stream ENDS at a checkpoint (message_end finish_reason=paused → ChatPage.refreshPaused).
 * Unlike PauseCard it reads a PERSISTED PausedTurnSummary and asks the parent to drive a
 * fresh resume stream. These assert the two kind branches (ask_user / plan_review), that the
 * note rides along, and the plan_review-only 调整 gating — coverage the durable path lacked.
 * The block comment keeps the @vitest-environment directive file-leading past organizeImports.
 */

import type { PausedTurnSummary } from "@/api/turn";
import { ResumeCard } from "@/components/ResumeCard";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(cleanup);

function summary(over: Partial<PausedTurnSummary> = {}): PausedTurnSummary {
  return {
    message_id: "m-server-1",
    checkpoint_id: "cp1",
    kind: "ask_user",
    user_message: "做 A 还是 B？",
    user_message_id: "u1",
    question: "先做 A 还是 B?",
    context: "两条路线各有取舍。",
    // 契约序列化必带（服务端带默认值恒输出；仅 team_preview 开工卡才有具体值）
    form: "",
    motion: "",
    primitive: "delegate",
    max_rounds: 0,
    thorough: true,
    offer_research_first: false,
    research_first_recommended: false,
    ...over,
  };
}

describe("ResumeCard · ask_user", () => {
  it("renders the offline headline, the original request, question + context", () => {
    render(<ResumeCard paused={summary()} onResume={vi.fn()} />);
    expect(screen.getByText("需要你拍板（已离线保留）")).toBeTruthy();
    expect(screen.getByText("做 A 还是 B？")).toBeTruthy();
    expect(screen.getByText("先做 A 还是 B?")).toBeTruthy();
    expect(screen.getByText("两条路线各有取舍。")).toBeTruthy();
    // ask_user has no 调整 (that is plan_review-only steer).
    expect(screen.queryByText("调整")).toBeNull();
  });

  it("继续 submits continue with the trimmed note", () => {
    const onResume = vi.fn();
    render(<ResumeCard paused={summary()} onResume={onResume} />);
    fireEvent.change(screen.getByPlaceholderText(/可选/), {
      target: { value: "  选 A  " },
    });
    fireEvent.click(screen.getByText("继续"));
    expect(onResume).toHaveBeenCalledWith("continue", "选 A", [], null, null);
  });

  it("停止 submits stop", () => {
    const onResume = vi.fn();
    render(<ResumeCard paused={summary()} onResume={onResume} />);
    fireEvent.click(screen.getByText("停止"));
    expect(onResume).toHaveBeenCalledWith("stop", "", [], null, null);
  });

  it("proposal_pick chip 选择映射进 selected", () => {
    const onResume = vi.fn();
    render(
      <ResumeCard
        paused={summary({
          intent: "proposal_pick",
          questions: [
            {
              id: "q0",
              prompt: "选方案",
              kind: "choice",
              multiple: false,
              options: [{ label: "方案 A" }, { label: "方案 B" }],
            },
          ],
        })}
        onResume={onResume}
      />,
    );
    fireEvent.click(screen.getByText("方案 A"));
    fireEvent.click(screen.getByText("继续"));
    expect(onResume).toHaveBeenCalledWith(
      "continue",
      "方案 A",
      ["方案 A"],
      null,
      null,
    );
  });

  it("organize_plan 确认=全保留（无勾选 UI 时 selected 含全部选项）", () => {
    const onResume = vi.fn();
    render(
      <ResumeCard
        paused={summary({
          intent: "organize_plan",
          questions: [
            {
              id: "q0",
              prompt: "保留哪些操作",
              kind: "choice",
              multiple: true,
              options: [
                { label: "a → b", op: "move", source: "a", destination: "b" },
                { label: "删 x", op: "delete", path: "x" },
              ],
            },
          ],
        })}
        onResume={onResume}
      />,
    );
    fireEvent.click(screen.getByText("继续"));
    expect(onResume).toHaveBeenCalledWith(
      "continue",
      "",
      ["a → b", "删 x"],
      null,
      null,
    );
  });

  it("style_options continue 直传 style_id 与 selected sN", () => {
    const onResume = vi.fn();
    render(
      <ResumeCard
        paused={summary({
          style_options: [
            { id: "s0", label: "深色科技" },
            { id: "s1", label: "简约商务" },
          ],
        })}
        onResume={onResume}
      />,
    );
    fireEvent.click(screen.getByText("简约商务"));
    fireEvent.click(screen.getByText("继续"));
    expect(onResume).toHaveBeenCalledWith(
      "continue",
      "风格：简约商务",
      ["s1"],
      "s1",
      null,
    );
  });

  it("format_options continue 直传 format_id 与 selected fN", () => {
    const onResume = vi.fn();
    render(
      <ResumeCard
        paused={summary({
          format_options: [
            { id: "f0", label: "PowerPoint（.pptx）" },
            { id: "f1", label: "Marp Markdown" },
          ],
        })}
        onResume={onResume}
      />,
    );
    fireEvent.click(screen.getByText("Marp Markdown"));
    fireEvent.click(screen.getByText("继续"));
    expect(onResume).toHaveBeenCalledWith(
      "continue",
      "形态：Marp Markdown",
      ["f1"],
      null,
      "f1",
    );
  });
});

describe("ResumeCard · plan_review", () => {
  const planReview = (
    over: Partial<PausedTurnSummary> = {},
  ): PausedTurnSummary =>
    summary({
      kind: "plan_review",
      checkpoint_id: "pr1",
      question: "",
      context: "",
      steps: [{ role: "调研", output_summary: "方案就绪" }],
      pending: [{ role: "执行" }],
      ...over,
    });

  it("renders the plan_review headline and the completed step", () => {
    render(<ResumeCard paused={planReview()} onResume={vi.fn()} />);
    expect(screen.getByText("执行已暂停 · 待你决定是否继续")).toBeTruthy();
    expect(screen.getByText("调研")).toBeTruthy();
    expect(screen.getByText("方案就绪")).toBeTruthy();
  });

  it("调整 is gated until a note is typed, then steers with it", () => {
    const onResume = vi.fn();
    render(<ResumeCard paused={planReview()} onResume={onResume} />);
    const adjust = screen.getByText("调整") as HTMLButtonElement;
    expect(adjust.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(/可选/), {
      target: { value: "换个方向" },
    });
    expect(adjust.disabled).toBe(false);
    fireEvent.click(adjust);
    expect(onResume).toHaveBeenCalledWith("adjust", "换个方向", [], null, null);
  });
});

describe("ResumeCard · team_preview", () => {
  const teamPreview = (
    over: Partial<PausedTurnSummary> = {},
  ): PausedTurnSummary =>
    summary({
      kind: "team_preview",
      checkpoint_id: "tp1",
      question: "",
      context: "",
      workers: [{ role: "调研", task: "做A" }],
      tools: ["file_write"],
      primitive: "delegate",
      ...over,
    });

  it("非 debate 仅授权并开工 + 停止，无调整 / 逐次审批", () => {
    render(<ResumeCard paused={teamPreview()} onResume={vi.fn()} />);
    expect(screen.getByText("授权并开工")).toBeTruthy();
    expect(screen.getByText("停止")).toBeTruthy();
    expect(screen.queryByText("调整")).toBeNull();
    expect(screen.queryByText("逐次审批开工")).toBeNull();
  });

  it("主按钮带嘱咐发 continue", () => {
    const onResume = vi.fn();
    render(<ResumeCard paused={teamPreview()} onResume={onResume} />);
    fireEvent.change(screen.getByPlaceholderText(/对全体队员的嘱咐/), {
      target: { value: "更简洁" },
    });
    fireEvent.click(screen.getByText("授权并开工"));
    expect(onResume).toHaveBeenCalledWith("continue", "更简洁", [], null, null);
  });

  it("debate 仅开赛 + 停止；嘱咐走 continue", () => {
    const onResume = vi.fn();
    render(
      <ResumeCard
        paused={teamPreview({
          primitive: "debate",
          workers: [],
          motion: "辩题",
          sides: [{ name: "正方", stance: "赞成" }],
        })}
        onResume={onResume}
      />,
    );
    expect(screen.getByText("开赛")).toBeTruthy();
    expect(screen.getByText("停止")).toBeTruthy();
    expect(screen.queryByText("调整")).toBeNull();
    expect(screen.queryByText("先多视角调研再辩")).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/开赛嘱咐/), {
      target: { value: "最关心成本谁买单" },
    });
    fireEvent.click(screen.getByText("开赛"));
    expect(onResume).toHaveBeenCalledWith(
      "continue",
      "最关心成本谁买单",
      [],
      null,
      null,
    );
  });

  it("开工卡不再提供 research_first 第三键（庭前取证内化）", () => {
    const onResume = vi.fn();
    render(
      <ResumeCard
        paused={teamPreview({
          primitive: "debate",
          workers: [],
          motion: "辩题",
          sides: [{ name: "正方", stance: "赞成" }],
          offer_research_first: true,
          research_first_recommended: true,
        })}
        onResume={onResume}
      />,
    );
    expect(screen.queryByText("先多视角调研再辩")).toBeNull();
    expect(screen.getByText("开赛")).toBeTruthy();
  });

  it("delegate 即使 offer_research_first 也不显示第三键", () => {
    render(
      <ResumeCard
        paused={teamPreview({ offer_research_first: true })}
        onResume={vi.fn()}
      />,
    );
    expect(screen.queryByText("先多视角调研再辩")).toBeNull();
  });
});
