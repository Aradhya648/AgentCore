// @vitest-environment jsdom
import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import {
  MANUAL_HELP,
  ManualHelpLink,
  ManualHelpTextLink,
} from "../ManualHelpLink";

function LocationProbe() {
  const loc = useLocation();
  return (
    <div data-testid="loc">
      {loc.pathname}
      {loc.search}
    </div>
  );
}

function renderHelp(to: string) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <TooltipProvider>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <ManualHelpLink to={to} />
                <LocationProbe />
              </>
            }
          />
          <Route path="/toolbox/manual/*" element={<LocationProbe />} />
        </Routes>
      </TooltipProvider>
    </MemoryRouter>,
  );
}

function renderTextHelp(to: string, label: string) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <ManualHelpTextLink to={to} label={label} />
              <LocationProbe />
            </>
          }
        />
        <Route path="/toolbox/manual/*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe("ManualHelpLink", () => {
  it("renders a discreet help button with aria-label", () => {
    renderHelp(MANUAL_HELP.debate);
    const btn = screen.getByRole("button", { name: "看手册说明" });
    expect(btn.getAttribute("data-manual-help")).toBe(MANUAL_HELP.debate);
  });

  it("navigates to the manual deep-link on click", () => {
    renderHelp(MANUAL_HELP.checkpoint);
    fireEvent.click(screen.getByRole("button", { name: "看手册说明" }));
    expect(screen.getByTestId("loc").textContent).toBe(
      "/toolbox/manual/collaboration?s=checkpoint",
    );
  });

  it("covers autonomy / control deep-links", () => {
    renderHelp(MANUAL_HELP.autonomy);
    expect(
      screen
        .getByRole("button", { name: "看手册说明" })
        .getAttribute("data-manual-help"),
    ).toBe(MANUAL_HELP.autonomy);
    cleanup();
    renderHelp(MANUAL_HELP.control);
    fireEvent.click(screen.getByRole("button", { name: "看手册说明" }));
    expect(screen.getByTestId("loc").textContent).toBe(
      "/toolbox/manual/collaboration?s=control",
    );
  });
});

describe("ManualHelpTextLink", () => {
  it("renders label and navigates on click", () => {
    renderTextHelp(MANUAL_HELP.debate, "手册·辩论");
    const btn = screen.getByRole("button", { name: "手册·辩论" });
    expect(btn.getAttribute("data-manual-help")).toBe(MANUAL_HELP.debate);
    fireEvent.click(btn);
    expect(screen.getByTestId("loc").textContent).toBe(
      "/toolbox/manual/collaboration?s=debate",
    );
  });
});
