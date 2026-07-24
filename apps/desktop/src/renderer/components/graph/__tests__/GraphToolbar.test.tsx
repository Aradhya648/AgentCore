// @vitest-environment jsdom
/**
 * 协作图工具条角落挂手册「?」入口（深链 mechanism?s=legend）。
 */

import { MANUAL_HELP } from "@/components/ManualHelpLink";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { GraphToolbar } from "../GraphToolbar";

afterEach(cleanup);

describe("GraphToolbar manual help", () => {
  it("挂「看手册说明」入口，深链到图例节", () => {
    render(
      <MemoryRouter>
        <TooltipProvider>
          <div className="relative h-20 w-40">
            <GraphToolbar
              layoutKind="leftright"
              onLayoutKindChange={() => {}}
            />
          </div>
        </TooltipProvider>
      </MemoryRouter>,
    );
    const btn = screen.getByRole("button", { name: "看手册说明" });
    expect(btn.getAttribute("data-manual-help")).toBe(MANUAL_HELP.legend);
  });
});
