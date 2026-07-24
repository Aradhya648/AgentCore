// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { MemoryUpdateCard } from "../MemoryUpdateCard";

describe("MemoryUpdateCard", () => {
  it("renders episodic tip and semantic diff", () => {
    render(
      <MemoryRouter>
        <MemoryUpdateCard
          updates={[
            {
              id: "e1",
              createdAt: "2026-07-19T12:00:00Z",
              kind: "episodic",
              summary: "本场摘要：部署讨论",
              items: [],
            },
            {
              id: "s1",
              createdAt: "2026-07-19T13:00:00Z",
              kind: "semantic",
              items: [
                {
                  action: "add",
                  file: "画像",
                  section: "关于用户的事实",
                  scope: "global",
                  content: "用 bun",
                  target: "global/profile",
                },
              ],
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("已记下本场摘要")).toBeTruthy();
    expect(screen.getByText(/部署讨论/)).toBeTruthy();
    expect(screen.getByText("记忆已更新")).toBeTruthy();
    expect(screen.getByText("用 bun")).toBeTruthy();
  });
});
