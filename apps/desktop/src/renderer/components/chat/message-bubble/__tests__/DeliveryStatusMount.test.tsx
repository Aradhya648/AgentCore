// @vitest-environment jsdom
/**
 * 用户面第①步：AssistantMessage 挂载闸——delivered/notes 静默；
 * partial/blocked 仅轻提示（无验收卡、无动作按钮、无缺口明细）。
 */
import type { DeliveryStatusPayload } from "@/types/events";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DeliveryStatusMount } from "../DeliveryStatusMount";

afterEach(() => {
  cleanup();
});

function payload(
  partial: Pick<DeliveryStatusPayload, "state" | "summary"> &
    Partial<DeliveryStatusPayload>,
): DeliveryStatusPayload {
  return {
    execution_id: "exec-1",
    delivered_files: [],
    gaps: [
      {
        role: "验收",
        description: "course.pptx 未生成（云端无执行环境）",
      },
    ],
    actions: [
      {
        kind: "bind_local_folder",
        description: "绑定本机执行环境后可继续生成产物。",
      },
    ],
    ...partial,
  };
}

describe("DeliveryStatusMount", () => {
  it("delivered：不出现验收卡与轻提示", () => {
    const { container } = render(
      <DeliveryStatusMount
        status={payload({
          state: "delivered",
          summary: "已交付 2 个文件",
          delivered_files: ["a.md", "b.md"],
          gaps: [],
          actions: [],
        })}
      />,
    );
    expect(container.childElementCount).toBe(0);
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByTestId("delivery-shortfall-hint")).toBeNull();
    expect(screen.queryByTestId("delivery-status-bound")).toBeNull();
  });

  it("notes：不出现验收卡与轻提示", () => {
    const { container } = render(
      <DeliveryStatusMount
        status={payload({
          state: "notes",
          summary: "已交付 1 个文件；另有 1 处备注",
          gaps: [
            {
              role: "分区",
              description: "交接说明不够完整",
              severity: "warning",
              reason: "degraded_handoff",
            },
          ],
          actions: [],
        })}
      />,
    );
    expect(container.childElementCount).toBe(0);
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByText("有备注")).toBeNull();
    expect(screen.queryByTestId("delivery-shortfall-hint")).toBeNull();
  });

  it("partial：仅一句轻提示，无动作按钮与缺口明细", () => {
    render(
      <DeliveryStatusMount
        status={payload({
          state: "partial",
          summary: "已交付 2 个文件；1 项缺口",
        })}
      />,
    );
    const hint = screen.getByTestId("delivery-shortfall-hint");
    expect(hint.textContent).toBe("已交付 2 个文件；1 项缺口");
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByText("部分未满足")).toBeNull();
    expect(screen.queryByText(/course\.pptx 未生成/)).toBeNull();
    expect(
      screen.queryByRole("button", { name: "绑定本机执行环境" }),
    ).toBeNull();
    expect(screen.queryByTestId("delivery-status-bound")).toBeNull();
  });

  it("blocked：仅一句轻提示，无动作按钮", () => {
    render(
      <DeliveryStatusMount
        status={payload({
          state: "blocked",
          summary: "未能交付：1 项缺口",
          delivered_files: [],
          actions: [{ kind: "future_kind", description: "未来的提示行" }],
        })}
      />,
    );
    expect(screen.getByTestId("delivery-shortfall-hint").textContent).toBe(
      "未能交付：1 项缺口",
    );
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByText("未满足")).toBeNull();
    expect(screen.queryByText("未来的提示行")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("null：不渲染", () => {
    const { container } = render(<DeliveryStatusMount status={null} />);
    expect(container.childElementCount).toBe(0);
  });
});
