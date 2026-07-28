// @vitest-environment jsdom
/**
 * EscalationCard · browser_login 薄切片：
 * - pending + browserLogin → 标题「需要你登录」+ CTA「打开浏览器」
 * - mount 时自动 showBrowser()（揭示右坞壳）；按钮保留作兜底
 * - 主操作「已登录，继续」走 decideEscalation answer（不 auto-resume）
 * - 「打开浏览器」调无参 showBrowser()（tab 恒对当前会话，不传第二份 id）
 */

import { TooltipProvider } from "@/components/ui/tooltip";
import type { RunEscalation } from "@/stores/execution";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EscalationCard } from "../EscalationCard";

const showBrowser = vi.fn();
const decideEscalation = vi.fn();

vi.mock("@/stores/sidePanel", () => ({
  useSidePanelStore: {
    getState: () => ({ showBrowser }),
  },
}));

vi.mock("@/services/escalation", () => ({
  decideEscalation: (...args: unknown[]) => decideEscalation(...args),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
}));

afterEach(cleanup);

beforeEach(() => {
  showBrowser.mockReset();
  decideEscalation.mockReset().mockResolvedValue("ok");
});

const loginEsc: RunEscalation = {
  id: "esc-login",
  question: "请先登录目标站点",
  assumption: "用户已登录",
  blocking: true,
  status: "pending",
  answer: null,
  kind: "normal",
  questions: [],
  browserLogin: true,
};

function renderCard(esc: RunEscalation = loginEsc) {
  const cardProps = {
    escalation: esc,
    role: "研究员",
    conversationId: "conv-1",
    interactive: true as const,
  };
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <EscalationCard {...cardProps} />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

describe("EscalationCard · browser_login", () => {
  it("shows 需要你登录 and the open-browser CTA", () => {
    renderCard();
    expect(screen.getByText(/需要你登录/)).toBeTruthy();
    expect(screen.getByText("打开浏览器")).toBeTruthy();
    expect(screen.getByText("已登录，继续")).toBeTruthy();
    expect(screen.getByText("按假设继续")).toBeTruthy();
    expect(screen.getByText("请先登录目标站点")).toBeTruthy();
    expect(
      screen.getByText(/在浏览器里完成登录后，点「已登录，继续」/),
    ).toBeTruthy();
    expect(screen.queryByText(/在直播里/)).toBeNull();
  });

  it("auto-reveals the browser shell on mount", () => {
    renderCard();
    expect(showBrowser).toHaveBeenCalledTimes(1);
  });

  it("does not re-reveal on rerender of the same escalation", () => {
    const { rerender } = renderCard();
    expect(showBrowser).toHaveBeenCalledTimes(1);
    rerender(
      <MemoryRouter>
        <TooltipProvider>
          <EscalationCard
            escalation={loginEsc}
            role="研究员"
            conversationId="conv-1"
            interactive
          />
        </TooltipProvider>
      </MemoryRouter>,
    );
    expect(showBrowser).toHaveBeenCalledTimes(1);
  });

  it("reveals again via CTA as a fallback", () => {
    renderCard();
    expect(showBrowser).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("打开浏览器"));
    expect(showBrowser).toHaveBeenCalledTimes(2);
  });

  it("resolves with answer「已登录，继续」on primary click", async () => {
    renderCard();
    await act(async () => {
      fireEvent.click(screen.getByText("已登录，继续"));
    });
    expect(decideEscalation).toHaveBeenCalledWith("conv-1", "esc-login", {
      kind: "answer",
      answer: "已登录，继续",
    });
  });

  it("does not use the browser-login chrome for a normal pending escalate", () => {
    renderCard({ ...loginEsc, browserLogin: undefined });
    expect(screen.queryByText(/需要你登录/)).toBeNull();
    expect(screen.queryByText("打开浏览器直播")).toBeNull();
    expect(screen.getByText(/请你拍板/)).toBeTruthy();
    expect(showBrowser).not.toHaveBeenCalled();
  });
});
