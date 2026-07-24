// @vitest-environment jsdom
import { Markdown } from "@/components/Markdown";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

describe("Markdown evidenceLedger (#rN)", () => {
  it("rewrites #rN from turn evidenceLedger when citations[].id is missing", () => {
    render(
      <Markdown
        content="见 #r5"
        citations={[]}
        evidenceLedger={[
          {
            id: "#r5",
            url: "https://ledger.example/r5",
            title: "Ledger R5",
            site: "ledger.example",
            tier: "media",
          },
        ]}
      />,
    );
    expect(screen.queryByText(/#r5/)).toBeNull();
    expect(
      screen.getByRole("link", { name: /来源 .*（#r5）/ }).getAttribute("href"),
    ).toBe("https://ledger.example/r5");
  });
});
