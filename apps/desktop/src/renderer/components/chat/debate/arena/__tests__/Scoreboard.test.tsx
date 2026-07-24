// @vitest-environment jsdom
/**
 * 辩论室记分牌页头挂手册「?」入口（深链 collaboration?s=debate）。
 */

import { MANUAL_HELP } from "@/components/ManualHelpLink";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DebateModel } from "../../model";
import { Scoreboard } from "../Scoreboard";

vi.mock("@/components/chat/debate/ModelBadge", () => ({
  ModelBadge: () => null,
}));

function makeModel(overrides: Partial<DebateModel> = {}): DebateModel {
  return {
    form: "debate",
    motion: "是否采用方案 A",
    stopReason: null,
    moderatorRunId: null,
    narrativeFirst: false,
    rounds: [],
    brief: null,
    sides: null,
    closings: [],
    opening: null,
    settled: true,
    ...overrides,
  } as DebateModel;
}

afterEach(cleanup);

describe("Scoreboard manual help", () => {
  it("挂「看手册说明」入口，深链到辩论节", () => {
    render(
      <MemoryRouter>
        <TooltipProvider>
          <Scoreboard
            model={makeModel()}
            messageId="m1"
            hasPendingSteering={false}
            onScrollTo={() => {}}
          />
        </TooltipProvider>
      </MemoryRouter>,
    );
    const btn = screen.getByRole("button", { name: "看手册说明" });
    expect(btn.getAttribute("data-manual-help")).toBe(MANUAL_HELP.debate);
  });
});
